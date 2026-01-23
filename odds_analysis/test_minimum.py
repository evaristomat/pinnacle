"""
Teste para verificar aviso de mínimo de jogos
"""
from odds_analyzer import OddsAnalyzer, print_analysis
from normalizer import get_normalizer

def main():
    analyzer = OddsAnalyzer()
    normalizer = get_normalizer()
    
    # Simula análise com poucos jogos
    # Vamos buscar um jogo e modificar os stats para ter menos de 5
    import sqlite3
    from config import PINNACLE_DB
    
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        WHERE league_name LIKE '%LCK%'
        LIMIT 1
    """)
    
    game_row = cursor.fetchone()
    conn.close()
    
    if game_row:
        game = dict(game_row)
        matchup_id = game['matchup_id']
        
        # Analisa normalmente
        analysis = analyzer.analyze_game(matchup_id)
        
        if analysis and analysis.get('historical_stats'):
            # Modifica para testar aviso
            original_games = analysis['historical_stats']['games']
            analysis['historical_stats']['games'] = 3  # Menos que 5
            analysis['historical_stats']['meets_minimum'] = False
            
            print("=" * 80)
            print("TESTE: Aviso de minimo de jogos")
            print("=" * 80)
            print(f"Jogo original tinha {original_games} mapas")
            print(f"Simulando com apenas 3 mapas...")
            print()
            
            print_analysis(analysis)
        else:
            print("Nao foi possivel analisar o jogo")

if __name__ == "__main__":
    main()
