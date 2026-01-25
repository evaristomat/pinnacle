"""
Teste com jogo LPL de ontem: Weibo vs JD Gaming (2026-01-24).
Roda metodo empirico e depois ML, mostrando que o match (liga+times+data +-1d) e o draft funcionam.
"""
import sys
from pathlib import Path

# Garante que odds_analysis esta no path
sys.path.insert(0, str(Path(__file__).parent))

from odds_analyzer import OddsAnalyzer, print_analysis, Colors
from config import PINNACLE_DB

# Jogo LPL de "ontem": Weibo vs JD Gaming, 2026-01-24
MATCHUP_ID = 1622004894


def main():
    if not PINNACLE_DB.exists():
        print(f"{Colors.RED}Pinnacle DB nao encontrado: {PINNACLE_DB}{Colors.RESET}")
        return

    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}TESTE LPL (ontem): Weibo vs JD Gaming | matchup_id={MATCHUP_ID}{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")

    analyzer = OddsAnalyzer()

    # PASSA 1: Empirico
    print(f"\n{Colors.BRIGHT_YELLOW}[PASSA 1] METODO EMPIRICO{Colors.RESET}")
    print(f"{Colors.CYAN}{'-' * 60}{Colors.RESET}")
    emp = analyzer.analyze_game(MATCHUP_ID, force_method="probabilidade_empirica")
    if not emp or "error" in emp:
        print(f"{Colors.RED}Erro na analise empirica.{Colors.RESET}")
        return
    print_analysis(emp)

    # PASSA 2: ML
    print(f"\n\n{Colors.BRIGHT_YELLOW}[PASSA 2] METODO ML{Colors.RESET}")
    print(f"{Colors.CYAN}{'-' * 60}{Colors.RESET}")
    ml_analysis = analyzer.analyze_game(MATCHUP_ID, force_method="machinelearning")
    if not ml_analysis or "error" in ml_analysis:
        print(f"{Colors.RED}Erro na analise ML.{Colors.RESET}")
        return
    print_analysis(ml_analysis)

    # Resumo
    game_exists = ml_analysis.get("game_exists_in_history", False)
    ml_avail = ml_analysis.get("ml_available_for_game", False)
    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}RESUMO{Colors.RESET}")
    print(f"   Jogo no historico (match +-1d): {Colors.GREEN if game_exists else Colors.RED}{game_exists}{Colors.RESET}")
    print(f"   ML disponivel (draft):          {Colors.GREEN if ml_avail else Colors.RED}{ml_avail}{Colors.RESET}")
    value_emp = sum(1 for m in emp.get("markets", []) if m.get("analysis", {}).get("value"))
    value_ml = sum(1 for m in ml_analysis.get("markets", []) if m.get("analysis", {}).get("value"))
    print(f"   Apostas com valor (empirico):   {value_emp}")
    print(f"   Apostas com valor (ML):         {value_ml}")


if __name__ == "__main__":
    main()
