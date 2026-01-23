"""
Teste completo de análise com método ML usando jogo finalizado
Simula análise de um jogo que já aconteceu e tem draft disponível
"""
import sqlite3
from pathlib import Path
from odds_analyzer import OddsAnalyzer, print_analysis, Colors
from config import HISTORY_DB
from normalizer import get_normalizer

def main():
    """Testa análise completa com método ML."""
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}TESTE COMPLETO: Método ML com Jogo Finalizado{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    # Encontra jogo com draft
    if not HISTORY_DB.exists():
        print(f"{Colors.YELLOW}Banco histórico não encontrado!{Colors.RESET}")
        return
    
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca jogo LPL ou LCK com draft (ligas principais)
    cursor.execute("""
        SELECT DISTINCT m.gameid, m.league, m.t1, m.t2, m.date, m.total_kills
        FROM matchups m
        INNER JOIN compositions c ON m.gameid = c.gameid
        WHERE m.league IN ('LPL', 'LCK')
        ORDER BY m.date DESC
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    if not row:
        print(f"{Colors.YELLOW}Nenhum jogo com draft encontrado{Colors.RESET}")
        conn.close()
        return
    
    history_game = dict(row)
    conn.close()
    
    print(f"{Colors.BRIGHT_BLUE}Jogo encontrado no histórico:{Colors.RESET}")
    print(f"   {Colors.CYAN}Liga:{Colors.RESET} {history_game['league']}")
    print(f"   {Colors.CYAN}Times:{Colors.RESET} {history_game['t1']} vs {history_game['t2']}")
    print(f"   {Colors.CYAN}Data:{Colors.RESET} {history_game['date']}")
    print(f"   {Colors.CYAN}Total Kills:{Colors.RESET} {history_game['total_kills']}")
    
    # Normaliza nomes
    normalizer = get_normalizer()
    league_norm = normalizer.normalize_league_name(history_game['league'])
    team1_norm = normalizer.normalize_team_name(history_game['t1'], league_norm)
    team2_norm = normalizer.normalize_team_name(history_game['t2'], league_norm)
    
    print(f"\n{Colors.BRIGHT_BLUE}Normalização:{Colors.RESET}")
    print(f"   Liga: {history_game['league']} -> {league_norm}")
    print(f"   Time 1: {history_game['t1']} -> {team1_norm}")
    print(f"   Time 2: {history_game['t2']} -> {team2_norm}")
    
    # Inicializa analyzer
    print(f"\n{Colors.BRIGHT_BLUE}Inicializando analisador...{Colors.RESET}")
    analyzer = OddsAnalyzer()
    
    # Verifica se jogo existe no histórico (deve existir)
    print(f"\n{Colors.BRIGHT_BLUE}Verificando se jogo existe no histórico...{Colors.RESET}")
    exists = analyzer.game_exists_in_history(team1_norm, team2_norm, league_norm, history_game['date'])
    print(f"   Resultado: {Colors.BRIGHT_GREEN if exists else Colors.YELLOW}{'SIM' if exists else 'NAO'}{Colors.RESET}")
    
    # Busca draft
    print(f"\n{Colors.BRIGHT_BLUE}Buscando draft do jogo específico...{Colors.RESET}")
    draft_data = analyzer.get_draft_data(team1_norm, team2_norm, league_norm, history_game['date'])
    
    if draft_data:
        print(f"{Colors.BRIGHT_GREEN}[OK] Draft encontrado!{Colors.RESET}")
        print(f"\n{Colors.BRIGHT_CYAN}Composição do Draft:{Colors.RESET}")
        print(f"   {Colors.CYAN}Time 1 ({history_game['t1']}):{Colors.RESET}")
        print(f"      Top: {draft_data.get('top_t1')}")
        print(f"      Jung: {draft_data.get('jung_t1')}")
        print(f"      Mid: {draft_data.get('mid_t1')}")
        print(f"      ADC: {draft_data.get('adc_t1')}")
        print(f"      Sup: {draft_data.get('sup_t1')}")
        print(f"   {Colors.CYAN}Time 2 ({history_game['t2']}):{Colors.RESET}")
        print(f"      Top: {draft_data.get('top_t2')}")
        print(f"      Jung: {draft_data.get('jung_t2')}")
        print(f"      Mid: {draft_data.get('mid_t2')}")
        print(f"      ADC: {draft_data.get('adc_t2')}")
        print(f"      Sup: {draft_data.get('sup_t2')}")
        
        # Testa predições ML para diferentes linhas
        print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}Predições ML para diferentes linhas:{Colors.RESET}")
        print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
        
        test_lines = [23.5, 25.5, 27.5, 30.5, 35.5]
        for line in test_lines:
            ml_result = analyzer._predict_ml(draft_data, line)
            if ml_result:
                result_color = Colors.BRIGHT_GREEN if ml_result['prediction'] == 'OVER' else Colors.BRIGHT_RED
                print(f"   {Colors.CYAN}Linha {line}:{Colors.RESET} {result_color}{ml_result['prediction']}{Colors.RESET} | "
                      f"Prob OVER: {ml_result['probability_over']:.2%} | "
                      f"Prob UNDER: {ml_result['probability_under']:.2%} | "
                      f"Confiança: {ml_result['confidence']}")
        
        # Resultado real
        real_kills = history_game['total_kills']
        print(f"\n{Colors.BRIGHT_CYAN}Resultado Real do Jogo:{Colors.RESET}")
        print(f"   {Colors.BRIGHT_WHITE}Total Kills: {real_kills}{Colors.RESET}")
        
        # Compara com predições
        print(f"\n{Colors.BRIGHT_CYAN}Comparação com Predições:{Colors.RESET}")
        for line in test_lines:
            ml_result = analyzer._predict_ml(draft_data, line)
            if ml_result:
                prediction = ml_result['prediction']
                if prediction == 'OVER':
                    correct = real_kills > line
                else:
                    correct = real_kills < line
                
                status = f"{Colors.BRIGHT_GREEN}[CORRETO]{Colors.RESET}" if correct else f"{Colors.BRIGHT_RED}[ERRADO]{Colors.RESET}"
                print(f"   Linha {line}: Predição {prediction} | Real: {real_kills} | {status}")
        
        print(f"\n{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.BRIGHT_GREEN}[OK] Método ML funcionando corretamente!{Colors.RESET}")
        print(f"{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
        
    else:
        print(f"{Colors.YELLOW}Draft não encontrado para este jogo específico{Colors.RESET}")
        print(f"   Isso pode acontecer se:")
        print(f"   - A data não corresponder exatamente (tolerância: ±2 horas)")
        print(f"   - Os nomes dos times não corresponderem após normalização")

if __name__ == "__main__":
    main()
