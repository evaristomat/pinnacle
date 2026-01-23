"""
Verifica se há jogos finalizados no banco Pinnacle que também estão no histórico
e têm draft disponível para usar método ML
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from odds_analyzer import OddsAnalyzer, Colors
from config import PINNACLE_DB, HISTORY_DB
from normalizer import get_normalizer

def find_finalized_games_in_pinnacle():
    """Busca jogos no banco Pinnacle que podem estar finalizados."""
    if not PINNACLE_DB.exists():
        print(f"{Colors.YELLOW}Banco Pinnacle não encontrado!{Colors.RESET}")
        return []
    
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca todos os jogos (independente de status)
    cursor.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        ORDER BY start_time DESC
        LIMIT 50
    """)
    
    games = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return games

def find_matching_history_game(pinnacle_game):
    """Tenta encontrar jogo correspondente no histórico."""
    if not HISTORY_DB.exists():
        return None
    
    normalizer = get_normalizer()
    league_norm = normalizer.normalize_league_name(pinnacle_game['league_name'])
    team1_norm = normalizer.normalize_team_name(pinnacle_game['home_team'], league_norm)
    team2_norm = normalizer.normalize_team_name(pinnacle_game['away_team'], league_norm)
    
    if not all([league_norm, team1_norm, team2_norm]):
        return None
    
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca jogo com tolerância de ±2 horas
    try:
        game_date = datetime.strptime(pinnacle_game['start_time'], '%Y-%m-%dT%H:%M:%S')
    except:
        try:
            game_date = datetime.strptime(pinnacle_game['start_time'], '%Y-%m-%d %H:%M:%S')
        except:
            conn.close()
            return None
    
    tolerance = timedelta(hours=2)
    date_min = (game_date - tolerance).strftime('%Y-%m-%d %H:%M:%S')
    date_max = (game_date + tolerance).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute("""
        SELECT gameid, league, t1, t2, date, total_kills
        FROM matchups
        WHERE league = ? 
        AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
        AND date >= ? AND date <= ?
        LIMIT 1
    """, (league_norm, team1_norm, team2_norm, team2_norm, team1_norm, date_min, date_max))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None

def check_draft_available(history_game):
    """Verifica se o jogo tem draft disponível."""
    if not HISTORY_DB.exists():
        return False
    
    conn = sqlite3.connect(HISTORY_DB)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) FROM compositions
        WHERE gameid = ?
    """, (history_game['gameid'],))
    
    count = cursor.fetchone()[0]
    conn.close()
    
    return count >= 2  # Precisa ter composição para ambos os times

def main():
    """Verifica jogos finalizados com odds e draft."""
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}VERIFICAÇÃO: Jogos Finalizados com Odds e Draft{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    # Busca jogos no Pinnacle
    print(f"{Colors.BRIGHT_BLUE}Buscando jogos no banco Pinnacle...{Colors.RESET}")
    pinnacle_games = find_finalized_games_in_pinnacle()
    
    if not pinnacle_games:
        print(f"{Colors.YELLOW}Nenhum jogo encontrado no banco Pinnacle{Colors.RESET}")
        return
    
    print(f"{Colors.BRIGHT_GREEN}Encontrados {len(pinnacle_games)} jogos no banco Pinnacle{Colors.RESET}\n")
    
    # Verifica cada jogo
    analyzer = OddsAnalyzer()
    normalizer = get_normalizer()
    
    matches_found = []
    matches_with_draft = []
    
    print(f"{Colors.BRIGHT_BLUE}Verificando correspondência com histórico...{Colors.RESET}\n")
    
    for i, pinnacle_game in enumerate(pinnacle_games, 1):
        # Normaliza nomes
        league_norm = normalizer.normalize_league_name(pinnacle_game['league_name'])
        team1_norm = normalizer.normalize_team_name(pinnacle_game['home_team'], league_norm)
        team2_norm = normalizer.normalize_team_name(pinnacle_game['away_team'], league_norm)
        
        if not all([league_norm, team1_norm, team2_norm]):
            continue
        
        # Verifica se existe no histórico
        exists = analyzer.game_exists_in_history(team1_norm, team2_norm, league_norm, pinnacle_game['start_time'])
        
        if exists:
            # Busca jogo no histórico
            history_game = find_matching_history_game(pinnacle_game)
            
            if history_game:
                matches_found.append({
                    'pinnacle': pinnacle_game,
                    'history': history_game,
                    'normalized': {
                        'league': league_norm,
                        'team1': team1_norm,
                        'team2': team2_norm
                    }
                })
                
                # Verifica se tem draft
                has_draft = check_draft_available(history_game)
                if has_draft:
                    matches_with_draft.append(matches_found[-1])
    
    # Mostra resultados
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}RESULTADOS:{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    print(f"   {Colors.CYAN}Total de jogos no Pinnacle:{Colors.RESET} {len(pinnacle_games)}")
    print(f"   {Colors.CYAN}Jogos encontrados no histórico:{Colors.RESET} {Colors.BRIGHT_GREEN if matches_found else Colors.YELLOW}{len(matches_found)}{Colors.RESET}")
    print(f"   {Colors.CYAN}Jogos com draft disponível:{Colors.RESET} {Colors.BRIGHT_GREEN if matches_with_draft else Colors.YELLOW}{len(matches_with_draft)}{Colors.RESET}")
    
    if matches_found:
        print(f"\n{Colors.BRIGHT_BLUE}Jogos encontrados no histórico:{Colors.RESET}")
        for i, match in enumerate(matches_found[:10], 1):
            has_draft = check_draft_available(match['history'])
            draft_status = f"{Colors.BRIGHT_GREEN}[COM DRAFT]{Colors.RESET}" if has_draft else f"{Colors.YELLOW}[SEM DRAFT]{Colors.RESET}"
            
            print(f"   {Colors.CYAN}{i}.{Colors.RESET} {match['pinnacle']['home_team']} vs {match['pinnacle']['away_team']}")
            print(f"      Liga: {match['pinnacle']['league_name']} -> {match['normalized']['league']}")
            print(f"      Data Pinnacle: {match['pinnacle']['start_time']}")
            print(f"      Data Histórico: {match['history']['date']}")
            print(f"      Total Kills: {match['history']['total_kills']}")
            print(f"      {draft_status}")
            print()
    
    if matches_with_draft:
        print(f"\n{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.BRIGHT_GREEN}JOGOS COM DRAFT DISPONÍVEL PARA MÉTODO ML:{Colors.RESET}")
        print(f"{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}\n")
        
        for i, match in enumerate(matches_with_draft[:5], 1):
            print(f"{Colors.BRIGHT_CYAN}Jogo {i}:{Colors.RESET}")
            print(f"   {Colors.CYAN}Pinnacle:{Colors.RESET} {match['pinnacle']['home_team']} vs {match['pinnacle']['away_team']}")
            print(f"   {Colors.CYAN}Matchup ID:{Colors.RESET} {match['pinnacle']['matchup_id']}")
            print(f"   {Colors.CYAN}Liga:{Colors.RESET} {match['pinnacle']['league_name']}")
            print(f"   {Colors.CYAN}Data:{Colors.RESET} {match['pinnacle']['start_time']}")
            print(f"   {Colors.CYAN}Total Kills Real:{Colors.RESET} {match['history']['total_kills']}")
            
            # Testa busca de draft
            draft_data = analyzer.get_draft_data(
                match['normalized']['team1'],
                match['normalized']['team2'],
                match['normalized']['league'],
                match['pinnacle']['start_time']
            )
            
            if draft_data:
                print(f"   {Colors.BRIGHT_GREEN}[OK] Draft encontrado!{Colors.RESET}")
                print(f"      Time 1: {draft_data.get('top_t1')}, {draft_data.get('jung_t1')}, {draft_data.get('mid_t1')}, {draft_data.get('adc_t1')}, {draft_data.get('sup_t1')}")
                print(f"      Time 2: {draft_data.get('top_t2')}, {draft_data.get('jung_t2')}, {draft_data.get('mid_t2')}, {draft_data.get('adc_t2')}, {draft_data.get('sup_t2')}")
                
                # Testa análise completa
                print(f"\n   {Colors.BRIGHT_BLUE}Testando análise completa...{Colors.RESET}")
                analysis = analyzer.analyze_game(match['pinnacle']['matchup_id'])
                
                if analysis:
                    ml_available = analysis.get('ml_available_for_game', False)
                    if ml_available:
                        print(f"   {Colors.BRIGHT_GREEN}[OK] Método ML foi usado na análise!{Colors.RESET}")
                        
                        # Verifica se há apostas com método ML
                        markets = analysis.get('markets', [])
                        ml_bets = [m for m in markets if m.get('analysis', {}).get('metodo') == 'ml']
                        if ml_bets:
                            print(f"   {Colors.BRIGHT_GREEN}[OK] {len(ml_bets)} apostas identificadas com método ML!{Colors.RESET}")
                        else:
                            print(f"   {Colors.YELLOW}[INFO] ML disponível mas nenhuma aposta convergiu (empírico + ML){Colors.RESET}")
                    else:
                        print(f"   {Colors.YELLOW}[INFO] ML não foi usado (draft não encontrado ou erro){Colors.RESET}")
                else:
                    print(f"   {Colors.YELLOW}[ERRO] Falha na análise{Colors.RESET}")
            else:
                print(f"   {Colors.YELLOW}[ERRO] Draft não encontrado mesmo tendo composição no banco{Colors.RESET}")
            
            print()
    else:
        print(f"\n{Colors.YELLOW}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.YELLOW}NENHUM JOGO COM DRAFT DISPONÍVEL ENCONTRADO{Colors.RESET}")
        print(f"{Colors.YELLOW}{'=' * 80}{Colors.RESET}\n")
        
        print(f"{Colors.BRIGHT_BLUE}Possíveis razões:{Colors.RESET}")
        print(f"   1. Jogos no Pinnacle são todos futuros (status: scheduled)")
        print(f"   2. Jogos finalizados não têm correspondência no histórico (normalização)")
        print(f"   3. Diferença de datas muito grande (> 2 horas)")
        print(f"   4. Jogos no histórico não têm composições (draft) salvas")
        
        if matches_found:
            print(f"\n{Colors.BRIGHT_BLUE}Jogos encontrados mas sem draft:{Colors.RESET}")
            for match in matches_found[:5]:
                print(f"   - {match['pinnacle']['home_team']} vs {match['pinnacle']['away_team']} ({match['pinnacle']['league_name']})")

if __name__ == "__main__":
    main()
