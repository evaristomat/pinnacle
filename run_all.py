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
import subprocess
import sqlite3
import time
import argparse
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
    """Função principal."""
    args = parse_args()

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
