"""
Script orquestrador que executa todo o pipeline:
1. Atualiza database_improved
2. Coleta odds da Pinnacle (com retry)
3. Coleta e salva apostas no bets_tracker
4. Atualiza resultados das apostas

Uso:
    python run_all.py                      # Pipeline completo
    python run_all.py --skip-history       # Pula dados históricos
    python run_all.py --skip-collect       # Pula coleta de apostas
    python run_all.py --skip-update        # Pula atualização de resultados
    python run_all.py --only 2             # Roda apenas etapa 2
    python run_all.py --ev-min 0.10        # EV mínimo para coleta (10%)
    python run_all.py --dry-run            # Modo seco (não salva)
"""
import sys
import os
import subprocess
import sqlite3
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Cores para output
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

TOTAL_STEPS = 4

# ============================================================================
# TELEGRAM - Notificação de resumo do pipeline
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

SEP_TELEGRAM = "────────────────────────────────"


def send_telegram_message(text: str) -> bool:
    """Envia mensagem via Telegram Bot API."""
    if not TELEGRAM_ENABLED:
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"{YELLOW}   [TELEGRAM] Erro ao enviar: {e}{RESET}")
        return False


def notify_pipeline_summary(
    results: dict,
    results_time: dict,
    pipeline_elapsed: float,
    args,
    bets_db: Path = None,
):
    """
    Envia resumo do pipeline via Telegram.

    Inclui: status de cada etapa, novos jogos/odds, bets encontradas, ROI.
    """
    if not TELEGRAM_ENABLED:
        return

    lines = [
        f"🚀 <b>PIPELINE CONCLUÍDO</b>",
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"⏱ Tempo total: {pipeline_elapsed:.0f}s",
        SEP_TELEGRAM,
    ]

    # Status de cada etapa
    step_labels = {
        'database_improved': ('1️⃣', 'Histórico'),
        'pinnacle_collect':  ('2️⃣', 'Odds Pinnacle'),
        'bets_collect':      ('3️⃣', 'Value Bets'),
        'bets_update':       ('4️⃣', 'Resultados'),
    }
    step_to_num = {
        'database_improved': 1,
        'pinnacle_collect': 2,
        'bets_collect': 3,
        'bets_update': 4,
    }

    for step, success in results.items():
        step_num = step_to_num.get(step, 0)
        ran = should_run_step(step_num, args)
        emoji, label = step_labels.get(step, ('❓', step))
        elapsed = results_time.get(step, 0)
        time_str = f" ({elapsed:.0f}s)" if elapsed > 0 else ""

        if not ran:
            lines.append(f"{emoji} {label}: ⏭ Pulada")
        elif success:
            lines.append(f"{emoji} {label}: ✅ OK{time_str}")
        else:
            lines.append(f"{emoji} {label}: ❌ Falha{time_str}")

    # Estatísticas do banco de odds (pinnacle_data.db)
    pinnacle_db = Path(__file__).parent / "pinnacle_data.db"
    if pinnacle_db.exists():
        try:
            conn = sqlite3.connect(pinnacle_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM games")
            total_games = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM markets")
            total_markets = cursor.fetchone()[0]
            conn.close()
            lines.append("")
            lines.append(f"📊 <b>Banco Pinnacle:</b> {total_games} jogos | {total_markets} markets")
        except Exception:
            pass

    # Estatísticas do banco de bets
    if bets_db and bets_db.exists():
        try:
            conn = sqlite3.connect(bets_db)
            cursor = conn.cursor()

            # Total e por status
            cursor.execute("SELECT COUNT(*) FROM bets")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM bets GROUP BY status")
            by_status = {row[0]: row[1] for row in cursor.fetchall()}

            pending = by_status.get('pending', 0)
            won = by_status.get('won', 0)
            lost = by_status.get('lost', 0)

            # ROI
            cursor.execute("""
                SELECT
                    COUNT(*) as total_resolved,
                    SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
                FROM bets
                WHERE status IN ('won', 'lost')
            """)
            roi_row = cursor.fetchone()
            conn.close()

            lines.append(f"🎯 <b>Bets:</b> {total} total | {pending} pending | {won}W-{lost}L")

            if roi_row and roi_row[0] and roi_row[0] > 0:
                total_resolved = roi_row[0]
                wins = roi_row[1] or 0
                lucro = roi_row[2] or 0
                win_rate = (wins / total_resolved * 100) if total_resolved > 0 else 0
                roi_pct = (lucro / total_resolved * 100) if total_resolved > 0 else 0

                profit_emoji = "📈" if lucro >= 0 else "📉"
                profit_sign = "+" if lucro >= 0 else ""
                roi_sign = "+" if roi_pct >= 0 else ""

                lines.append(
                    f"{profit_emoji} <b>ROI:</b> {roi_sign}{roi_pct:.1f}% | "
                    f"Lucro: {profit_sign}{lucro:.2f}u | "
                    f"WR: {win_rate:.0f}% ({total_resolved})"
                )
        except Exception:
            pass

    # Status final
    critical_steps = {'pinnacle_collect': 2, 'bets_collect': 3}
    critical_failed = [
        step for step, step_num in critical_steps.items()
        if should_run_step(step_num, args) and not results.get(step)
    ]
    if critical_failed:
        lines.append("")
        lines.append("⚠️ <b>Pipeline com falhas críticas!</b>")

    text = "\n".join(lines)
    success = send_telegram_message(text)
    if success:
        print(f"{GREEN}   [TELEGRAM] Resumo do pipeline enviado!{RESET}")
    else:
        if TELEGRAM_ENABLED:
            print(f"{YELLOW}   [TELEGRAM] Falha ao enviar resumo{RESET}")


def print_header(text: str):
    """Imprime cabeçalho formatado."""
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")


def print_step(step_num: int, total: int, description: str):
    """Imprime etapa do pipeline."""
    print(f"\n{BOLD}[ETAPA {step_num}/{total}]{RESET} {YELLOW}{description}{RESET}")
    print("-" * 70)


def run_command(cmd: list, cwd: Path = None, description: str = None, capture_output: bool = True) -> bool:
    """
    Executa um comando e retorna True se sucesso.

    Args:
        cmd: Lista com comando e argumentos
        cwd: Diretório de trabalho
        description: Descrição do comando (opcional)
        capture_output: Se False, output vai direto para terminal (preserva cores)

    Returns:
        True se sucesso, False caso contrário
    """
    if description:
        print(f"   Executando: {description}")

    try:
        if capture_output:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            if result.stdout:
                print(result.stdout)

            return True
        else:
            # Executa sem capturar output para preservar cores/formatação
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                encoding='utf-8',
                errors='replace'
            )
            return True

    except subprocess.CalledProcessError as e:
        print(f"{RED}   ERRO: {e}{RESET}")
        if capture_output and e.stdout:
            print(f"   Output: {e.stdout}")
        if capture_output and e.stderr:
            print(f"   Erro: {e.stderr}")
        return False

    except Exception as e:
        print(f"{RED}   ERRO inesperado: {e}{RESET}")
        return False


def run_with_retry(cmd: list, cwd: Path = None, description: str = None,
                   capture_output: bool = True, max_retries: int = 2, backoff: int = 5) -> bool:
    """
    Executa comando com retry e backoff exponencial.

    Args:
        cmd: Lista com comando e argumentos
        cwd: Diretório de trabalho
        description: Descrição do comando
        capture_output: Se False, output vai direto para terminal
        max_retries: Número máximo de tentativas adicionais
        backoff: Tempo base de espera entre tentativas (segundos)

    Returns:
        True se sucesso em qualquer tentativa, False caso contrário
    """
    for attempt in range(max_retries + 1):
        success = run_command(cmd, cwd=cwd, description=description, capture_output=capture_output)
        if success:
            return True
        if attempt < max_retries:
            wait = backoff * (2 ** attempt)
            print(f"{YELLOW}   Tentativa {attempt + 1}/{max_retries + 1} falhou. Retry em {wait}s...{RESET}")
            time.sleep(wait)
    return False


def print_bets_stats(bets_db: Path, title: str = "Estatísticas do Banco de Apostas"):
    """
    Consulta bets.db e imprime estatísticas + ROI formatados.

    Args:
        bets_db: Caminho para o arquivo bets.db
        title: Título da seção de estatísticas
    """
    if not bets_db.exists():
        return

    try:
        conn = sqlite3.connect(bets_db)
        cursor = conn.cursor()

        # Total de apostas
        cursor.execute("SELECT COUNT(*) FROM bets")
        total = cursor.fetchone()[0]

        if total == 0:
            print(f"{YELLOW}   [AVISO] Banco criado mas nenhuma aposta foi salva{RESET}")
            conn.close()
            return

        # Por status
        cursor.execute("SELECT status, COUNT(*) FROM bets GROUP BY status")
        by_status = {row[0]: row[1] for row in cursor.fetchall()}

        # Por método
        try:
            cursor.execute("SELECT metodo, COUNT(*) FROM bets GROUP BY metodo")
            by_metodo = {row[0]: row[1] for row in cursor.fetchall()}
        except Exception:
            by_metodo = {}

        # ROI (apenas resolvidas)
        cursor.execute("""
            SELECT
                COUNT(*) as total_resolved,
                SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
                AVG(CASE WHEN status = 'won' THEN odd_decimal ELSE NULL END) as avg_win_odd,
                SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
            FROM bets
            WHERE status IN ('won', 'lost')
        """)
        roi_row = cursor.fetchone()
        conn.close()

        # Imprime estatísticas
        print(f"\n{BOLD}{CYAN}{title}:{RESET}")
        print(f"   {BOLD}Total de apostas:{RESET} {total}")
        print(f"   {BOLD}Por status:{RESET} {by_status}")

        if by_metodo:
            metodo_display = {}
            for metodo, count in by_metodo.items():
                if metodo == 'probabilidade_empirica':
                    metodo_display['Empírico'] = count
                elif metodo in ('ml', 'machinelearning'):
                    metodo_display['ML'] = metodo_display.get('ML', 0) + count
                else:
                    metodo_display[metodo] = count
            print(f"   {BOLD}Por método:{RESET} {metodo_display}")

        # ROI se houver apostas resolvidas
        if roi_row and roi_row[0] and roi_row[0] > 0:
            total_resolved = roi_row[0]
            wins = roi_row[1] or 0
            losses = roi_row[2] or 0
            avg_win_odd = roi_row[3] or 0
            lucro = roi_row[4] or 0
            win_rate = (wins / total_resolved * 100) if total_resolved > 0 else 0
            roi_pct = (lucro / total_resolved * 100) if total_resolved > 0 else 0

            print(f"\n{BOLD}{CYAN}ROI:{RESET}")
            print(f"   Resolvidas: {BOLD}{total_resolved}{RESET}")
            print(f"   {GREEN}Vitórias:{RESET} {BOLD}{GREEN}{wins}{RESET} ({win_rate:.1f}%)")
            print(f"   {RED}Derrotas:{RESET} {BOLD}{RED}{losses}{RESET}")
            if avg_win_odd > 0:
                print(f"   Odd média (vitórias): {BOLD}{avg_win_odd:.2f}{RESET}")
            roi_color = GREEN if roi_pct > 0 else RED if roi_pct < 0 else YELLOW
            profit_color = GREEN if lucro > 0 else RED if lucro < 0 else YELLOW
            print(f"   {BOLD}Return:{RESET} {BOLD}{roi_color}{roi_pct:+.2f}%{RESET} (lucro/total u apostadas)")
            print(f"   {BOLD}Lucro:{RESET} {BOLD}{profit_color}{lucro:+.2f} u{RESET}")

    except Exception as e:
        print(f"{YELLOW}   [AVISO] Erro ao verificar banco: {e}{RESET}")


def compute_run_summary(pipeline_start_ts: float, base_dir: Path, bets_tracker: Path) -> dict:
    """
    Calcula se houve odds novas (jogos/markets) e apostas novas nesta execução.

    Usa o campo created_at dos bancos pinnacle_data.db e bets_tracker/bets.db
    comparando com o horário de início do pipeline.
    """
    summary = {
        "new_games": 0,
        "new_markets": 0,
        "new_bets": 0,
    }

    # Converte o timestamp de início para formatos usados nos bancos
    try:
        start_dt = datetime.fromtimestamp(pipeline_start_ts)
    except Exception:
        start_dt = datetime.now()

    # SQLite do pinnacle_data.db usa CURRENT_TIMESTAMP (YYYY-MM-DD HH:MM:SS)
    start_db_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")
    # bets.db usa datetime.now().isoformat()
    start_bets_str = start_dt.isoformat(timespec="seconds")

    # ---- Odds (pinnacle_data.db) ----
    pinnacle_db = base_dir / "pinnacle_data.db"
    if pinnacle_db.exists():
        try:
            conn = sqlite3.connect(pinnacle_db)
            cursor = conn.cursor()

            # Novos jogos
            cursor.execute(
                "SELECT COUNT(*) FROM games WHERE created_at >= ?",
                (start_db_str,),
            )
            summary["new_games"] = int(cursor.fetchone()[0] or 0)

            # Novos markets
            cursor.execute(
                "SELECT COUNT(*) FROM markets WHERE created_at >= ?",
                (start_db_str,),
            )
            summary["new_markets"] = int(cursor.fetchone()[0] or 0)

            conn.close()
        except Exception as e:
            print(f"{YELLOW}   [AVISO] Erro ao calcular resumo de odds: {e}{RESET}")

    # ---- Apostas (bets_tracker/bets.db) ----
    bets_db = bets_tracker / "bets.db"
    if bets_db.exists():
        try:
            conn = sqlite3.connect(bets_db)
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) FROM bets WHERE created_at >= ?",
                (start_bets_str,),
            )
            summary["new_bets"] = int(cursor.fetchone()[0] or 0)

            conn.close()
        except Exception as e:
            print(f"{YELLOW}   [AVISO] Erro ao calcular resumo de apostas: {e}{RESET}")

    return summary


def parse_args():
    """Configura e retorna argumentos CLI."""
    parser = argparse.ArgumentParser(
        description="Pipeline completo - Sistema Pinnacle LoL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python run_all.py                      # Pipeline completo
  python run_all.py --skip-history       # Pula dados históricos
  python run_all.py --skip-collect       # Pula coleta de apostas
  python run_all.py --skip-update        # Pula atualização de resultados
  python run_all.py --only 2             # Roda apenas etapa 2
  python run_all.py --ev-min 0.10        # EV mínimo para coleta (10%)
  python run_all.py --dry-run            # Modo seco (não salva)
        """
    )
    parser.add_argument('--skip-history', action='store_true',
                        help='Pula etapa 1 (dados históricos)')
    parser.add_argument('--skip-collect', action='store_true',
                        help='Pula etapa 3 (coleta de apostas)')
    parser.add_argument('--skip-update', action='store_true',
                        help='Pula etapa 4 (atualização de resultados)')
    parser.add_argument('--only', type=int, choices=[1, 2, 3, 4],
                        help='Roda apenas a etapa N')
    parser.add_argument('--ev-min', type=float, default=None,
                        help='EV mínimo para coleta (ex: 0.05 = 5%%)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Modo seco (não salva alterações)')
    return parser.parse_args()


def should_run_step(step_num: int, args) -> bool:
    """Verifica se uma etapa deve ser executada com base nos argumentos."""
    if args.only is not None:
        return args.only == step_num

    skip_map = {
        1: args.skip_history,
        3: args.skip_collect,
        4: args.skip_update,
    }
    return not skip_map.get(step_num, False)


def main():
    """Função principal. Sempre usa LoL (pinnacle_data.db + bets.db)."""
    args = parse_args()

    # Força uso de LoL: não usar bancos do Dota mesmo que PINNACLE_ESPORT esteja setado
    os.environ.pop("PINNACLE_ESPORT", None)
    os.environ.pop("PINNACLE_DB_PATH", None)

    # Configura encoding para Windows
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    print_header("PIPELINE COMPLETO - Sistema Pinnacle LoL")
    print(f"Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.only:
        print(f"Modo: apenas etapa {args.only}")
    if args.dry_run:
        print(f"{YELLOW}Modo: DRY-RUN (sem salvar alterações){RESET}")
    print()

    # Diretórios
    BASE_DIR = Path(__file__).parent
    DATABASE_IMPROVED = BASE_DIR / "database_improved"
    BETS_TRACKER = BASE_DIR / "bets_tracker"

    results = {
        'database_improved': False,
        'pinnacle_collect': False,
        'bets_collect': False,
        'bets_update': False
    }
    results_time = {}
    pipeline_start = time.time()

    # ================================================================
    # ETAPA 1: Atualizar database_improved
    # ================================================================
    if should_run_step(1, args):
        print_step(1, TOTAL_STEPS, "Atualizando dados históricos (database_improved)")
        step_start = time.time()

        if not DATABASE_IMPROVED.exists():
            print(f"{RED}   ERRO: Pasta database_improved não encontrada!{RESET}")
        else:
            success = run_command(
                [sys.executable, "main.py", "--skip-download-if-downloaded-today-after-noon"],
                cwd=DATABASE_IMPROVED,
                description="Processando dados históricos"
            )
            results['database_improved'] = success

            if success:
                print(f"{GREEN}   [OK] Dados históricos atualizados{RESET}")
            else:
                print(f"{YELLOW}   [AVISO] Falha ao atualizar dados históricos (continuando...){RESET}")

        results_time['database_improved'] = time.time() - step_start
        print(f"   {BOLD}Tempo:{RESET} {results_time['database_improved']:.1f}s")

    # ================================================================
    # ETAPA 2: Coletar odds da Pinnacle (com retry)
    # ================================================================
    if should_run_step(2, args):
        print_step(2, TOTAL_STEPS, "Coletando odds da Pinnacle")
        step_start = time.time()

        success = run_with_retry(
            [sys.executable, "main.py"],
            cwd=BASE_DIR,
            description="Buscando dados da API Pinnacle",
            max_retries=2,
            backoff=5
        )
        results['pinnacle_collect'] = success

        if success:
            print(f"{GREEN}   [OK] Odds da Pinnacle coletadas{RESET}")
        else:
            print(f"{RED}   [ERRO] Falha ao coletar odds da Pinnacle (após retries){RESET}")
            print(f"{YELLOW}   Continuando com dados existentes...{RESET}")

        results_time['pinnacle_collect'] = time.time() - step_start
        print(f"   {BOLD}Tempo:{RESET} {results_time['pinnacle_collect']:.1f}s")

    # ================================================================
    # ETAPA 3: Coletar apostas com valor no bets_tracker
    # ================================================================
    if should_run_step(3, args):
        print_step(3, TOTAL_STEPS, "Coletando apostas com valor (bets_tracker)")
        step_start = time.time()

        if not BETS_TRACKER.exists():
            print(f"{RED}   ERRO: Pasta bets_tracker não encontrada!{RESET}")
        else:
            # Inicializa banco se necessário
            print(f"   Inicializando banco de apostas...")
            run_command(
                [sys.executable, "main.py", "init"],
                cwd=BETS_TRACKER,
                description="Inicializando banco"
            )

            # Monta comando de coleta
            collect_cmd = [sys.executable, "main.py", "collect"]
            if args.ev_min is not None:
                collect_cmd.extend(["--ev-min", str(args.ev_min)])

            # Coleta apostas
            print(f"   Coletando apostas com valor de todos os jogos...")
            success = run_command(
                collect_cmd,
                cwd=BETS_TRACKER,
                description="Coletando apostas"
            )
            results['bets_collect'] = success

            # Mostra estatísticas do banco
            bets_db = BETS_TRACKER / "bets.db"
            if bets_db.exists():
                print_bets_stats(bets_db)
            elif success:
                print(f"{GREEN}   [OK] Comando executado{RESET}")
            else:
                print(f"{YELLOW}   [AVISO] Nenhuma aposta coletada ou erro{RESET}")

        results_time['bets_collect'] = time.time() - step_start
        print(f"   {BOLD}Tempo:{RESET} {results_time['bets_collect']:.1f}s")

    # ================================================================
    # ETAPA 4: Atualizar resultados das apostas
    # ================================================================
    if should_run_step(4, args):
        print_step(4, TOTAL_STEPS, "Atualizando resultados das apostas")
        step_start = time.time()

        if BETS_TRACKER.exists():
            update_cmd = [
                sys.executable, "main.py", "update",
                "--db", "bets", "--include-pending", "--summary"
            ]
            if args.dry_run:
                update_cmd.append("--dry-run")

            success = run_command(
                update_cmd,
                cwd=BETS_TRACKER,
                description="Atualizando resultados"
            )
            results['bets_update'] = success

            if success:
                print(f"{GREEN}   [OK] Resultados atualizados{RESET}")
                bets_db = BETS_TRACKER / "bets.db"
                print_bets_stats(bets_db, "Estatísticas Atualizadas")
            else:
                print(f"{YELLOW}   [AVISO] Nenhum resultado atualizado{RESET}")

        results_time['bets_update'] = time.time() - step_start
        print(f"   {BOLD}Tempo:{RESET} {results_time['bets_update']:.1f}s")

    # ================================================================
    # Resumo final
    # ================================================================
    pipeline_elapsed = time.time() - pipeline_start
    print_header("RESUMO DO PIPELINE")

    print(f"{BOLD}Etapas executadas:{RESET}")
    step_to_num = {
        'database_improved': 1,
        'pinnacle_collect': 2,
        'bets_collect': 3,
        'bets_update': 4,
    }
    for step, success in results.items():
        step_num = step_to_num.get(step, 0)
        ran = should_run_step(step_num, args)
        if ran:
            status = f"{GREEN}[OK]{RESET}" if success else f"{YELLOW}[AVISO]{RESET}"
        else:
            status = f"{BLUE}[PULADA]{RESET}"
        step_name = step.replace('_', ' ').title()
        elapsed = results_time.get(step, 0)
        if elapsed > 0:
            print(f"   {status} {step_name} ({elapsed:.1f}s)")
        else:
            print(f"   {status} {step_name}")

    print(f"\n   {BOLD}Tempo total:{RESET} {pipeline_elapsed:.1f}s")

    # Resumo de novos dados desta execução (odds e apostas)
    run_summary = compute_run_summary(pipeline_start, BASE_DIR, BETS_TRACKER)
    print(f"\n{BOLD}Novos dados nesta execução:{RESET}")
    if run_summary["new_games"] or run_summary["new_markets"]:
        print(
            f"   Odds: {run_summary['new_games']} jogos novos, "
            f"{run_summary['new_markets']} markets novos"
        )
    else:
        print("   Odds: nenhuma odd nova (nenhum jogo/market novo criado)")

    if run_summary["new_bets"]:
        print(f"   Apostas: {run_summary['new_bets']} apostas novas salvas no bets.db")
    else:
        print("   Apostas: nenhuma aposta nova salva")

    # Estatísticas detalhadas via results_analysis.py
    if BETS_TRACKER.exists():
        bets_db = BETS_TRACKER / "bets.db"
        if bets_db.exists():
            print(f"\n{BOLD}Estatísticas Detalhadas:{RESET}")
            # Não captura output para preservar cores do Rich
            run_command(
                [sys.executable, "results_analysis.py", "--bets-db", str(bets_db)],
                cwd=BASE_DIR,
                description="Análise detalhada de resultados",
                capture_output=False
            )
        else:
            print(f"\n{YELLOW}   [AVISO] Banco de apostas não encontrado para análise{RESET}")

    # Notificação Telegram com resumo do pipeline
    bets_db = BETS_TRACKER / "bets.db"
    notify_pipeline_summary(
        results=results,
        results_time=results_time,
        pipeline_elapsed=pipeline_elapsed,
        args=args,
        bets_db=bets_db if bets_db.exists() else None,
    )

    # Exit code baseado em etapas críticas
    critical_steps = {'pinnacle_collect': 2, 'bets_collect': 3}
    critical_failed = [
        step for step, step_num in critical_steps.items()
        if should_run_step(step_num, args) and not results.get(step)
    ]

    if critical_failed:
        failed_names = ', '.join(s.replace('_', ' ').title() for s in critical_failed)
        print(f"\n{RED}{BOLD}Pipeline concluído com FALHAS críticas: {failed_names}{RESET}")
        print(f"Finalizado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        sys.exit(1)

    print(f"\n{BOLD}{GREEN}Pipeline concluído!{RESET}")
    print(f"Finalizado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Pipeline interrompido pelo usuário{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{RED}ERRO inesperado: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
