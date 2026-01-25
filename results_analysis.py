"""
Análise detalhada de resultados das apostas.
Executa resumo geral, ROI por liga e por mapa, e melhor aposta por mapa.
"""
import sys
import argparse
import sqlite3
from pathlib import Path

# Cores para output
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(text: str):
    """Imprime cabeçalho formatado."""
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")


def print_detailed_results(bets_db: Path):
    """Imprime análise detalhada de resultados."""
    if not bets_db.exists():
        print(f"{YELLOW}   [AVISO] bets.db não encontrado para análise{RESET}")
        return

    conn = sqlite3.connect(bets_db)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT status, odd_decimal, league_name, map
        FROM bets
        WHERE status IN ('won', 'lost')
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"{YELLOW}   [AVISO] Nenhuma aposta resolvida (won/lost) para análise{RESET}")
        return

    wins = sum(1 for status, _, _, _ in rows if status == 'won')
    losses = sum(1 for status, _, _, _ in rows if status == 'lost')
    profit = sum((odd - 1) if status == 'won' else -1 for status, odd, _, _ in rows)
    total_bets = wins + losses
    roi = (profit / total_bets) if total_bets else 0
    avg_win_odd = (
        sum(odd for status, odd, _, _ in rows if status == "won") / wins
        if wins else 0
    )

    print(f"{BOLD}Resumo Geral:{RESET}")
    print(f"   Bets resolvidas: {total_bets}")
    print(f"   Vitorias: {wins}")
    print(f"   Derrotas: {losses}")
    print(f"   Win rate: {(wins / total_bets * 100):.1f}%")
    print(f"   Odd media (vitorias): {avg_win_odd:.2f}")
    print(f"   Lucro total (unidades): {profit:.2f}")
    print(f"   ROI: {roi:.2%}")

    # ROI por liga
    league_stats = {}
    for status, odd, league, _ in rows:
        league_key = league or "Desconhecida"
        stats = league_stats.setdefault(league_key, {"wins": 0, "losses": 0, "profit": 0.0})
        if status == "won":
            stats["wins"] += 1
            stats["profit"] += (odd - 1)
        else:
            stats["losses"] += 1
            stats["profit"] -= 1

    print(f"\n{BOLD}ROI por Liga:{RESET}")
    for league, stats in sorted(league_stats.items(), key=lambda x: x[1]["profit"], reverse=True):
        total = stats["wins"] + stats["losses"]
        league_roi = stats["profit"] / total if total else 0
        win_rate = (stats["wins"] / total * 100) if total else 0
        print(
            f"   {league}: {stats['wins']}W-{stats['losses']}L | "
            f"WR {win_rate:.1f}% | Lucro {stats['profit']:.2f} | ROI {league_roi:.2%}"
        )

    # ROI por mapa
    map_stats = {}
    for status, odd, _, mapa in rows:
        map_key = mapa if mapa is not None else "Sem mapa"
        stats = map_stats.setdefault(map_key, {"wins": 0, "losses": 0, "profit": 0.0})
        if status == "won":
            stats["wins"] += 1
            stats["profit"] += (odd - 1)
        else:
            stats["losses"] += 1
            stats["profit"] -= 1

    print(f"\n{BOLD}ROI por Mapa:{RESET}")
    for mapa, stats in sorted(map_stats.items(), key=lambda x: x[1]["profit"], reverse=True):
        total = stats["wins"] + stats["losses"]
        map_roi = stats["profit"] / total if total else 0
        win_rate = (stats["wins"] / total * 100) if total else 0
        print(
            f"   Mapa {mapa}: {stats['wins']}W-{stats['losses']}L | "
            f"WR {win_rate:.1f}% | Lucro {stats['profit']:.2f} | ROI {map_roi:.2%}"
        )

    # Melhor aposta por mapa (maior ROI individual)
    best_bet_by_map = {}
    for status, odd, league, mapa in rows:
        map_key = mapa if mapa is not None else "Sem mapa"
        bet_roi = (odd - 1) if status == "won" else -1
        current_best = best_bet_by_map.get(map_key)
        if current_best is None or bet_roi > current_best["roi"]:
            best_bet_by_map[map_key] = {
                "status": status,
                "odd": odd,
                "league": league or "Desconhecida",
                "roi": bet_roi
            }

    print(f"\n{BOLD}Melhor aposta por Mapa (maior ROI):{RESET}")
    for mapa, best in sorted(best_bet_by_map.items(), key=lambda x: x[1]["roi"], reverse=True):
        print(
            f"   Mapa {mapa}: {best['league']} | Odd {best['odd']:.2f} | "
            f"{best['status'].upper()} | ROI {best['roi']:.2%}"
        )


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(description="Análise detalhada de resultados")
    parser.add_argument(
        "--bets-db",
        type=str,
        default=None,
        help="Caminho para o bets.db (opcional)"
    )
    args = parser.parse_args()

    # Configura encoding para Windows
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass

    base_dir = Path(__file__).parent
    bets_db = Path(args.bets_db) if args.bets_db else (base_dir / "bets_tracker" / "bets.db")

    print_header("ANALISE DETALHADA DE RESULTADOS")
    print_detailed_results(bets_db)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Analise interrompida pelo usuario{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{RED}ERRO inesperado: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
