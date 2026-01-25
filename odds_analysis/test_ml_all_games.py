"""
Testa TODOS os jogos (ou --league LPL) com metodo ML.
Reporta quantos tem draft, quantos apitam (tem apostas ML: empirico + ML convergem).
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from odds_analyzer import OddsAnalyzer, Colors
from config import PINNACLE_DB


def extract_ml_bets(analysis: dict) -> list:
    """Extrai apostas com valor do metodo ML (empirico + ML convergiram)."""
    out = []
    for m in analysis.get("markets", []):
        if "error" in m or "analysis" not in m:
            continue
        a = m["analysis"]
        if a.get("empirical_prob") is None or not a.get("value"):
            continue
        if a.get("metodo") != "ml" or a.get("ml_converges") is not True:
            continue
        out.append({
            "side": m["market"]["side"],
            "line": m["market"]["line_value"],
            "odd": m["market"]["odd_decimal"],
            "ev": a["expected_value"],
            "edge": a["edge"],
        })
    return out


def main():
    ap = argparse.ArgumentParser(description="Testa ML em todos os jogos")
    ap.add_argument("--league", type=str, help="Filtrar por liga (ex: LPL, LCK)")
    args = ap.parse_args()

    if not PINNACLE_DB.exists():
        print(f"{Colors.RED}Pinnacle DB nao encontrado.{Colors.RESET}")
        return

    analyzer = OddsAnalyzer()
    games = analyzer.get_all_games(league_filter=args.league)
    if not games:
        print(f"{Colors.YELLOW}Nenhum jogo encontrado.{(f' Liga {args.league}?' if args.league else '')}{Colors.RESET}")
        return

    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}TESTE ML EM TODOS OS JOGOS{Colors.RESET}" + (f" (liga: {args.league})" if args.league else ""))
    print(f"   Total: {len(games)} jogos")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")

    with_draft = []
    with_ml_bets = []
    errors = 0

    for i, g in enumerate(games, 1):
        mid = g["matchup_id"]
        label = f"{g['home_team']} vs {g['away_team']} ({g['league_name']})"
        try:
            a = analyzer.analyze_game(mid, force_method="machinelearning")
        except Exception as e:
            print(f"   [{i}/{len(games)}] {Colors.RED}ERRO{Colors.RESET} {label}: {e}")
            errors += 1
            continue

        if not a or "error" in a:
            print(f"   [{i}/{len(games)}] {Colors.YELLOW}SEM DADOS{Colors.RESET} {label}")
            errors += 1
            continue

        ml_avail = a.get("ml_available_for_game", False)
        bets = extract_ml_bets(a)

        if ml_avail:
            with_draft.append((g, len(bets)))
        if bets:
            with_ml_bets.append((g, bets))

        if ml_avail or bets:
            status = f"{Colors.BRIGHT_GREEN}DRAFT{Colors.RESET}" if ml_avail else ""
            apita = f" {Colors.BRIGHT_GREEN}APITA ML ({len(bets)} bet(s)){Colors.RESET}" if bets else ""
            print(f"   [{i}/{len(games)}] {label} {status}{apita}")

    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}RESUMO{Colors.RESET}")
    print(f"   Jogos com draft (match +-1d + compositions): {len(with_draft)}/{len(games)}")
    print(f"   Jogos que APITAM ML (empirico + ML convergem): {len(with_ml_bets)}/{len(games)}")
    if errors:
        print(f"   Erros/sem dados: {errors}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")

    if with_ml_bets:
        print(f"\n{Colors.BRIGHT_GREEN}JOGOS COM APOSTAS ML:{Colors.RESET}")
        for g, bets in with_ml_bets:
            print(f"   {g['home_team']} vs {g['away_team']} ({g['league_name']}) {g['start_time']}")
            for b in bets:
                print(f"      {b['side']} {b['line']} @ {b['odd']:.2f}  EV={b['ev']*100:+.2f}%  edge={b['edge']:+.2f}%")


if __name__ == "__main__":
    main()
