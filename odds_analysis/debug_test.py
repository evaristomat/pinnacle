"""
Script de debug para testar normalização e análise
"""
from normalizer import get_normalizer
from odds_analyzer import OddsAnalyzer
import sqlite3

def main():
    print("=" * 80)
    print("DEBUG: Teste de Normalizacao e Analise")
    print("=" * 80)
    
    normalizer = get_normalizer()
    analyzer = OddsAnalyzer()
    
    # Teste 1: Normalização de liga
    print("\n1. Teste de Normalizacao de Liga:")
    test_leagues = ["LCK Cup", "LCK CL", "LCK Challengers", "LCK"]
    for league in test_leagues:
        norm = normalizer.normalize_league_name(league)
        print(f"   {league:20} -> {norm}")
    
    # Teste 2: Normalização de times
    print("\n2. Teste de Normalizacao de Times (LCKC):")
    test_teams = ["KT Rolster", "T1", "KT Rolster Challengers", "T1 Esports Academy"]
    for team in test_teams:
        norm = normalizer.normalize_team_name(team, "LCKC")
        matches = normalizer.find_team_matches(team, "LCKC")
        print(f"   {team:30} -> {norm}")
        if matches:
            print(f"      Matches: {matches[:2]}")
    
    # Teste 3: Verificar markets do jogo
    print("\n3. Verificando Markets do Jogo (1622710422):")
    matchup_id = 1622710422
    markets = analyzer.get_total_kills_markets(matchup_id)
    print(f"   Markets encontrados: {len(markets)}")
    for market in markets[:5]:
        print(f"   - {market['side']} {market['line_value']} @ {market['odd_decimal']}")
    
    # Teste 4: Buscar histórico
    print("\n4. Buscando Historico:")
    team1_norm = normalizer.normalize_team_name("KT Rolster", "LCKC")
    team2_norm = normalizer.normalize_team_name("T1", "LCKC")
    league_norm = normalizer.normalize_league_name("LCK Cup")
    
    print(f"   Time 1: KT Rolster -> {team1_norm}")
    print(f"   Time 2: T1 -> {team2_norm}")
    print(f"   Liga: LCK Cup -> {league_norm}")
    
    if all([team1_norm, team2_norm, league_norm]):
        stats = analyzer.get_historical_stats(team1_norm, team2_norm, league_norm)
        if stats:
            print(f"   OK: {stats['games']} jogos encontrados")
            print(f"   Media: {stats['mean']:.2f} kills")
        else:
            print("   Nenhum dado historico encontrado")
            
            # Tenta buscar times similares
            print("\n   Buscando times similares...")
            matches1 = normalizer.find_team_matches("KT Rolster", "LCKC")
            matches2 = normalizer.find_team_matches("T1", "LCKC")
            print(f"   KT Rolster matches: {matches1[:3]}")
            print(f"   T1 matches: {matches2[:3]}")
            
            # Tenta com os matches encontrados
            if matches1 and matches2:
                test_team1 = matches1[0][1]
                test_team2 = matches2[0][1]
                print(f"\n   Testando com: {test_team1} vs {test_team2}")
                stats2 = analyzer.get_historical_stats(test_team1, test_team2, league_norm)
                if stats2:
                    print(f"   OK: {stats2['games']} jogos encontrados")
                    print(f"   Media: {stats2['mean']:.2f} kills")
    
    # Teste 5: Análise completa
    print("\n5. Analise Completa:")
    analysis = analyzer.analyze_game(matchup_id)
    if analysis:
        if analysis.get('historical_stats'):
            print("   Analise OK!")
        else:
            print("   Analise sem dados historicos suficientes")

if __name__ == "__main__":
    main()
