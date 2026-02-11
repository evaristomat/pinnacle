"""
Pipeline completo para Dota 2:
  2. Coleta odds da Pinnacle (pinnacle_dota.db)
  3. Coleta apostas com valor (bets_dota.db)
  4. Atualiza resultados das apostas

Não roda etapa 1 (histórico LoL). Use run_all.py para LoL.

Uso:
  python run_dota.py
"""
import os
import sys
import subprocess
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent
BETS_TRACKER = PROJECT_ROOT / "bets_tracker"
PINNACLE_DOTA = PROJECT_ROOT / "pinnacle_dota.db"
BETS_DOTA = BETS_TRACKER / "bets_dota.db"

GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def run_cmd(cmd: list, cwd: Path, desc: str = None, env: dict = None) -> bool:
    env = env or os.environ
    if desc:
        print(f"   Executando: {desc}")
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if r.stdout:
            print(r.stdout)
        if r.returncode != 0 and r.stderr:
            print(r.stderr, file=sys.stderr)
        return r.returncode == 0
    except Exception as e:
        print(f"{RED}   ERRO: {e}{RESET}")
        return False


def run_with_retry(cmd: list, cwd: Path, desc: str, env: dict, max_retries: int = 2, backoff: int = 5) -> bool:
    for attempt in range(max_retries + 1):
        if run_cmd(cmd, cwd=cwd, desc=desc, env=env):
            return True
        if attempt < max_retries:
            wait = backoff * (2 ** attempt)
            print(f"{YELLOW}   Retry em {wait}s...{RESET}")
            time.sleep(wait)
    return False


def print_step(num: int, total: int, text: str):
    print(f"\n{BOLD}[ETAPA {num}/{total}]{RESET} {YELLOW}{text}{RESET}")
    print("-" * 60)


def test_opendota_jogos_do_mes(pinnacle_dota_path: Path) -> tuple:
    """
    Busca jogos do pinnacle_dota.db que já aconteceram neste mês e tenta
    encontrar cada um na OpenDota API. Retorna (total_jogos_mes, encontrados).
    """
    if not pinnacle_dota_path.exists():
        return 0, 0
    now = datetime.now(timezone.utc)
    mes_inicio = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        conn = sqlite3.connect(pinnacle_dota_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # start_time no DB pode ser ISO (2026-02-10T12:00:00 ou com Z)
        cur.execute(
            """
            SELECT league_name, home_team, away_team, start_time
            FROM games
            WHERE start_time IS NOT NULL AND start_time != ''
            ORDER BY start_time DESC
            """
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        print(f"   [AVISO] Erro ao ler pinnacle_dota.db: {e}")
        return 0, 0

    jogos_do_mes_passado = []
    for r in rows:
        st = (r["start_time"] or "").strip()
        if not st:
            continue
        try:
            if "T" in st:
                dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(st[:10], "%Y-%m-%d")
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            if dt >= mes_inicio and dt <= now:
                jogos_do_mes_passado.append({
                    "league_name": r["league_name"] or "",
                    "home_team": r["home_team"] or "",
                    "away_team": r["away_team"] or "",
                    "game_date": st[:19] if "T" in st else st[:10],
                })
        except Exception:
            continue

    if not jogos_do_mes_passado:
        return 0, 0

    sys.path.insert(0, str(BETS_TRACKER))
    try:
        from opendota_client import load_pro_matches, find_match_for_bet
    except ImportError as e:
        print(f"   [AVISO] OpenDota: {e}")
        return len(jogos_do_mes_passado), 0

    cache = load_pro_matches()
    encontrados = 0
    for j in jogos_do_mes_passado:
        r = find_match_for_bet(
            league_name=j["league_name"],
            home_team=j["home_team"],
            away_team=j["away_team"],
            game_date=j["game_date"],
            mapa=None,
            matches_cache=cache,
        )
        if r is not None:
            encontrados += 1
    return len(jogos_do_mes_passado), encontrados


def print_bets_stats(db_path: Path, title: str = "Estatísticas do Banco de Apostas"):
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bets")
        total = cur.fetchone()[0]
        if total == 0:
            conn.close()
            return
        cur.execute("SELECT status, COUNT(*) FROM bets GROUP BY status")
        by_status = dict(cur.fetchall())
        cur.execute("""
            SELECT COUNT(*) as n, SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as w,
                   SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as l,
                   SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
            FROM bets WHERE status IN ('won', 'lost')
        """)
        row = cur.fetchone()
        conn.close()
        print(f"\n{BOLD}{CYAN}{title}:{RESET}")
        print(f"   Total: {total}  |  Por status: {by_status}")
        if row and row[0] and row[0] > 0:
            n, w, l, lucro = row[0], row[1] or 0, row[2] or 0, row[3] or 0
            roi = (lucro / n * 100) if n else 0
            print(f"   Resolvidas: {n}  |  Vitórias: {w}  |  Derrotas: {l}  |  ROI: {roi:+.2f}%")
    except Exception as e:
        print(f"{YELLOW}   [AVISO] {e}{RESET}")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # Todas as etapas usam bancos Dota 2
    env = os.environ.copy()
    env["PINNACLE_DB_PATH"] = str(PINNACLE_DOTA)
    env["PINNACLE_ESPORT"] = "dota2"

    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}PIPELINE DOTA 2 - Odds + Apostas{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")
    print(f"Odds: {PINNACLE_DOTA.name}  |  Apostas: {BETS_DOTA.name}")
    print(f"Iniciado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    results = {"pinnacle_collect": False, "bets_collect": False, "bets_update": False}
    t_start = time.time()

    # --- Etapa 2: Coletar odds Dota 2 ---
    print_step(2, 4, "Coletando odds da Pinnacle (Dota 2)")
    t0 = time.time()
    results["pinnacle_collect"] = run_with_retry(
        [sys.executable, "main.py", "--esport", "dota2"],
        cwd=PROJECT_ROOT,
        desc="Buscando dados da API Pinnacle (Dota 2)",
        env=env,
    )
    if results["pinnacle_collect"]:
        print(f"{GREEN}   [OK] Odds coletadas{RESET}")
    else:
        print(f"{RED}   [ERRO] Falha ao coletar odds{RESET}")
    print(f"   Tempo: {time.time() - t0:.1f}s")

    # --- Etapa 3: Feed resultados OpenDota + apostas de valor (bets_dota.db) ---
    print_step(3, 4, "OpenDota: feed resultados + apostas de valor (bets_dota)")
    t0 = time.time()
    if not BETS_TRACKER.exists():
        print(f"{RED}   ERRO: bets_tracker não encontrado{RESET}")
    else:
        run_cmd([sys.executable, "main.py", "init"], cwd=BETS_TRACKER, env=env)
        run_cmd(
            [sys.executable, "dota_feed_results.py"],
            cwd=BETS_TRACKER,
            desc="Alimentar dota_results.db (OpenDota)",
            env=env,
        )
        results["bets_collect"] = run_cmd(
            [sys.executable, "dota_collect_value_bets.py"],
            cwd=BETS_TRACKER,
            desc="Coletar apostas de valor (bets_dota.db + pinnacle_to_result)",
            env=env,
        )
        if BETS_DOTA.exists():
            print_bets_stats(BETS_DOTA, "Apostas Dota 2")
    print(f"   Tempo: {time.time() - t0:.1f}s")

    # --- Etapa 4: Atualizar resultados das apostas (won/lost) ---
    print_step(4, 4, "Atualizar resultados das apostas (bets_dota.db)")
    t0 = time.time()
    total_mes, found_mes = test_opendota_jogos_do_mes(PINNACLE_DOTA)
    if total_mes > 0:
        print(f"   OpenDota: jogos deste mês (já realizados) no pinnacle_dota: {total_mes} | encontrados na API: {found_mes}")
    if BETS_TRACKER.exists():
        results["bets_update"] = run_cmd(
            [sys.executable, "dota_update_bet_results.py", "--summary"],
            cwd=BETS_TRACKER,
            desc="Atualizar status won/lost (pinnacle_to_result)",
            env=env,
        )
        if results["bets_update"] and BETS_DOTA.exists():
            print_bets_stats(BETS_DOTA, "Estatísticas Atualizadas")
    print(f"   Tempo: {time.time() - t0:.1f}s")

    # --- Resumo ---
    elapsed = time.time() - t_start
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}RESUMO DOTA 2{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}")
    for name, ok in results.items():
        st = f"{GREEN}[OK]{RESET}" if ok else f"{YELLOW}[FALHA]{RESET}"
        print(f"   {st} {name.replace('_', ' ').title()}")
    print(f"\n   Tempo total: {elapsed:.1f}s")
    print(f"\n{BOLD}{GREEN}Concluído.{RESET} LoL: use {BOLD}run_all.py{RESET}\n")

    return 0 if results["pinnacle_collect"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrompido{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}ERRO: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
