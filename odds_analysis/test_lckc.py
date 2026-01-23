"""
Teste de análise com jogo da LCK Cup
"""
from odds_analyzer import OddsAnalyzer, print_analysis

def main():
    """Testa análise com jogo da LCK Cup."""
    # Importa cores
    from odds_analyzer import Colors
    
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}TESTE: Analise de Valor nas Odds - LCK Cup{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    
    analyzer = OddsAnalyzer()
    
    # Busca jogos futuros da LCK Cup
    from odds_analyzer import Colors
    
    print(f"\n{Colors.BRIGHT_BLUE}Buscando jogos futuros da LCK Cup...{Colors.RESET}")
    games = analyzer.get_upcoming_games(league_filter="LCK Cup")
    
    if not games:
        print(f"{Colors.YELLOW}Nenhum jogo futuro encontrado{Colors.RESET}")
        print(f"\n{Colors.BRIGHT_BLUE}Tentando buscar qualquer jogo da LCK...{Colors.RESET}")
        # Tenta buscar qualquer jogo da LCK (mesmo que já tenha acontecido para teste)
        import sqlite3
        from config import PINNACLE_DB
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE league_name LIKE '%LCK%' OR league_name LIKE '%Cup%'
            ORDER BY start_time DESC
            LIMIT 5
        """)
        
        games = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        if games:
            print(f"{Colors.BRIGHT_GREEN}Encontrados {len(games)} jogos (incluindo finalizados para teste){Colors.RESET}")
        else:
            print(f"{Colors.BRIGHT_RED}Nenhum jogo encontrado{Colors.RESET}")
            return
    
    # Analisa o primeiro jogo encontrado
    if games:
        from odds_analyzer import Colors
        
        print(f"\n{Colors.BRIGHT_BLUE}Jogos encontrados:{Colors.RESET}")
        for i, game in enumerate(games[:5], 1):
            status_color = Colors.BRIGHT_GREEN if game['status'] == 'scheduled' else Colors.YELLOW
            print(f"   {Colors.CYAN}{i}.{Colors.RESET} {game['home_team']} {Colors.WHITE}vs{Colors.RESET} {game['away_team']} ({Colors.BRIGHT_CYAN}{game['league_name']}{Colors.RESET}) - {status_color}{game['status']}{Colors.RESET}")
        
        # Pega o primeiro jogo da LCK Cup (não LCK CL)
        test_game = None
        for game in games:
            if 'Cup' in game['league_name']:
                test_game = game
                break
        
        if not test_game:
            test_game = games[0]  # Fallback para primeiro jogo
        
        matchup_id = test_game['matchup_id']
        
        print(f"\n{Colors.BRIGHT_BLUE}Analisando jogo:{Colors.RESET} {Colors.BRIGHT_CYAN}{test_game['home_team']}{Colors.RESET} {Colors.WHITE}vs{Colors.RESET} {Colors.BRIGHT_CYAN}{test_game['away_team']}{Colors.RESET}")
        print(f"   {Colors.CYAN}Matchup ID:{Colors.RESET} {matchup_id}")
        
        analysis = analyzer.analyze_game(matchup_id)
        
        if analysis:
            print_analysis(analysis)
        else:
            from odds_analyzer import Colors
            print(f"{Colors.BRIGHT_RED}Erro ao analisar jogo{Colors.RESET}")
    else:
        from odds_analyzer import Colors
        print(f"{Colors.BRIGHT_RED}Nenhum jogo para analisar{Colors.RESET}")

if __name__ == "__main__":
    main()
