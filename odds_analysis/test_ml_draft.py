"""
Teste de análise com jogo finalizado que tem draft disponível
"""
import sqlite3
from pathlib import Path
from odds_analyzer import OddsAnalyzer, print_analysis
from config import PINNACLE_DB, HISTORY_DB

def find_game_with_draft():
    """Encontra um jogo no histórico que tenha draft disponível."""
    if not HISTORY_DB.exists():
        print("Banco histórico não encontrado!")
        return None
    
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca jogos que têm composições (draft)
    cursor.execute("""
        SELECT DISTINCT m.gameid, m.league, m.t1, m.t2, m.date, m.total_kills
        FROM matchups m
        INNER JOIN compositions c ON m.gameid = c.gameid
        WHERE m.league IN ('LCK', 'LPL', 'LEC', 'LCS', 'CBLOL')
        ORDER BY m.date DESC
        LIMIT 5
    """)
    
    games = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return games

def find_matching_pinnacle_game(history_game):
    """Tenta encontrar jogo correspondente no banco Pinnacle."""
    if not PINNACLE_DB.exists():
        return None
    
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca por times e data aproximada
    from datetime import datetime, timedelta
    game_date = datetime.strptime(history_game['date'], '%Y-%m-%d %H:%M:%S')
    date_min = (game_date - timedelta(days=1)).strftime('%Y-%m-%d')
    date_max = (game_date + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Tenta encontrar por nomes dos times
    cursor.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        WHERE (home_team LIKE ? OR away_team LIKE ? OR home_team LIKE ? OR away_team LIKE ?)
        AND start_time >= ? AND start_time <= ?
        LIMIT 1
    """, (f"%{history_game['t1']}%", f"%{history_game['t1']}%", 
          f"%{history_game['t2']}%", f"%{history_game['t2']}%",
          date_min, date_max))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def main():
    """Testa análise com jogo finalizado que tem draft."""
    from odds_analyzer import Colors
    
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}TESTE: Análise com Método ML (Draft){Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    # Encontra jogos com draft
    print(f"{Colors.BRIGHT_BLUE}Buscando jogos finalizados com draft disponível...{Colors.RESET}")
    history_games = find_game_with_draft()
    
    if not history_games:
        print(f"{Colors.YELLOW}Nenhum jogo com draft encontrado no histórico{Colors.RESET}")
        return
    
    print(f"{Colors.BRIGHT_GREEN}Encontrados {len(history_games)} jogos com draft:{Colors.RESET}")
    for i, game in enumerate(history_games, 1):
        print(f"   {Colors.CYAN}{i}.{Colors.RESET} {game['t1']} vs {game['t2']} ({game['league']}) - {game['date']} - Total Kills: {game['total_kills']}")
    
    # Tenta encontrar correspondente no Pinnacle
    print(f"\n{Colors.BRIGHT_BLUE}Buscando jogo correspondente no banco Pinnacle...{Colors.RESET}")
    analyzer = OddsAnalyzer()
    
    for history_game in history_games:
        pinnacle_game = find_matching_pinnacle_game(history_game)
        
        if pinnacle_game:
            print(f"\n{Colors.BRIGHT_GREEN}[OK] Jogo encontrado no Pinnacle!{Colors.RESET}")
            print(f"   {Colors.CYAN}Matchup ID:{Colors.RESET} {pinnacle_game['matchup_id']}")
            print(f"   {Colors.CYAN}Jogo:{Colors.RESET} {pinnacle_game['home_team']} vs {pinnacle_game['away_team']}")
            print(f"   {Colors.CYAN}Liga:{Colors.RESET} {pinnacle_game['league_name']}")
            print(f"   {Colors.CYAN}Data:{Colors.RESET} {pinnacle_game['start_time']}")
            print(f"   {Colors.CYAN}Status:{Colors.RESET} {pinnacle_game['status']}")
            
            # Analisa o jogo
            print(f"\n{Colors.BRIGHT_BLUE}Analisando jogo...{Colors.RESET}\n")
            analysis = analyzer.analyze_game(pinnacle_game['matchup_id'])
            
            if analysis:
                # Verifica se ML foi usado
                ml_used = analysis.get('ml_available_for_game', False)
                if ml_used:
                    print(f"\n{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
                    print(f"{Colors.BRIGHT_GREEN}[OK] METODO ML FOI USADO COM SUCESSO!{Colors.RESET}")
                    print(f"{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}\n")
                
                print_analysis(analysis)
                return
            else:
                print(f"{Colors.YELLOW}Erro ao analisar jogo{Colors.RESET}")
                continue
    
    # Se não encontrou no Pinnacle, testa diretamente com dados do histórico
    print(f"\n{Colors.YELLOW}Nenhum jogo correspondente encontrado no Pinnacle.{Colors.RESET}")
    print(f"{Colors.BRIGHT_BLUE}Testando busca de draft diretamente do histórico...{Colors.RESET}\n")
    
    # Testa busca de draft para um jogo do histórico
    test_game = history_games[0]
    from normalizer import get_normalizer
    normalizer = get_normalizer()
    
    league_norm = normalizer.normalize_league_name(test_game['league'])
    team1_norm = normalizer.normalize_team_name(test_game['t1'], league_norm)
    team2_norm = normalizer.normalize_team_name(test_game['t2'], league_norm)
    
    print(f"Jogo: {test_game['t1']} vs {test_game['t2']} ({test_game['league']})")
    print(f"Normalizado: {team1_norm} vs {team2_norm} ({league_norm})")
    print(f"Data: {test_game['date']}")
    
    # Busca draft
    draft_data = analyzer.get_draft_data(team1_norm, team2_norm, league_norm, test_game['date'])
    
    if draft_data:
        print(f"\n{Colors.BRIGHT_GREEN}[OK] Draft encontrado!{Colors.RESET}")
        print(f"   Time 1: {draft_data.get('top_t1')}, {draft_data.get('jung_t1')}, {draft_data.get('mid_t1')}, {draft_data.get('adc_t1')}, {draft_data.get('sup_t1')}")
        print(f"   Time 2: {draft_data.get('top_t2')}, {draft_data.get('jung_t2')}, {draft_data.get('mid_t2')}, {draft_data.get('adc_t2')}, {draft_data.get('sup_t2')}")
        
        # Testa predicao ML
        print(f"\n{Colors.BRIGHT_BLUE}Testando predicao ML com linha 25.5...{Colors.RESET}")
        ml_result = analyzer._predict_ml(draft_data, 25.5)
        
        if ml_result:
            print(f"{Colors.BRIGHT_GREEN}[OK] Predicao ML realizada!{Colors.RESET}")
            print(f"   Predicao: {ml_result['prediction']}")
            print(f"   Probabilidade OVER: {ml_result['probability_over']:.2%}")
            print(f"   Probabilidade UNDER: {ml_result['probability_under']:.2%}")
            print(f"   Confianca: {ml_result['confidence']}")
        else:
            print(f"{Colors.YELLOW}Erro ao fazer predicao ML{Colors.RESET}")
    else:
        print(f"{Colors.YELLOW}Draft nao encontrado{Colors.RESET}")

if __name__ == "__main__":
    main()
