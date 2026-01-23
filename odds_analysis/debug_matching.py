"""
Debug detalhado do matching entre Pinnacle e histórico
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from odds_analyzer import Colors
from config import PINNACLE_DB, HISTORY_DB
from normalizer import get_normalizer

def main():
    """Debug do matching."""
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}DEBUG: Matching Pinnacle vs Histórico{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    # 1. Verifica jogos no Pinnacle
    print(f"{Colors.BRIGHT_BLUE}1. JOGOS NO PINNACLE:{Colors.RESET}")
    if not PINNACLE_DB.exists():
        print(f"   {Colors.YELLOW}Banco não encontrado{Colors.RESET}")
        return
    
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM games
        GROUP BY status
    """)
    
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
    print(f"   Status dos jogos:")
    for status, count in status_counts.items():
        print(f"      {status}: {count} jogos")
    
    # Últimos 10 jogos
    cursor.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        ORDER BY start_time DESC
        LIMIT 10
    """)
    
    pinnacle_games = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    print(f"\n   Últimos 10 jogos:")
    for i, game in enumerate(pinnacle_games, 1):
        print(f"      {i}. {game['home_team']} vs {game['away_team']} ({game['league_name']})")
        print(f"         Data: {game['start_time']} | Status: {game['status']}")
    
    # 2. Verifica jogos no histórico
    print(f"\n{Colors.BRIGHT_BLUE}2. JOGOS NO HISTÓRICO:{Colors.RESET}")
    if not HISTORY_DB.exists():
        print(f"   {Colors.YELLOW}Banco não encontrado{Colors.RESET}")
        return
    
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT league, COUNT(*) as count
        FROM matchups
        GROUP BY league
        ORDER BY count DESC
    """)
    
    league_counts = {row['league']: row['count'] for row in cursor.fetchall()}
    print(f"   Ligas no histórico:")
    for league, count in list(league_counts.items())[:10]:
        print(f"      {league}: {count} jogos")
    
    # Últimos 10 jogos
    cursor.execute("""
        SELECT gameid, league, t1, t2, date, total_kills
        FROM matchups
        ORDER BY date DESC
        LIMIT 10
    """)
    
    history_games = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    print(f"\n   Últimos 10 jogos:")
    for i, game in enumerate(history_games, 1):
        print(f"      {i}. {game['t1']} vs {game['t2']} ({game['league']})")
        print(f"         Data: {game['date']} | Total Kills: {game['total_kills']}")
    
    # 3. Testa normalização
    print(f"\n{Colors.BRIGHT_BLUE}3. TESTE DE NORMALIZAÇÃO:{Colors.RESET}")
    normalizer = get_normalizer()
    
    # Testa com alguns jogos do Pinnacle
    print(f"   Testando normalização de jogos do Pinnacle:")
    for game in pinnacle_games[:5]:
        league_norm = normalizer.normalize_league_name(game['league_name'])
        team1_norm = normalizer.normalize_team_name(game['home_team'], league_norm)
        team2_norm = normalizer.normalize_team_name(game['away_team'], league_norm)
        
        print(f"      {game['home_team']} vs {game['away_team']} ({game['league_name']})")
        print(f"         Liga: {game['league_name']} -> {league_norm or 'NÃO ENCONTRADO'}")
        print(f"         Time 1: {game['home_team']} -> {team1_norm or 'NÃO ENCONTRADO'}")
        print(f"         Time 2: {game['away_team']} -> {team2_norm or 'NÃO ENCONTRADO'}")
        print()
    
    # 4. Testa matching direto
    print(f"{Colors.BRIGHT_BLUE}4. TESTE DE MATCHING DIRETO:{Colors.RESET}")
    
    # Pega um jogo do histórico e tenta encontrar no Pinnacle
    if history_games:
        test_history = history_games[0]
        print(f"   Testando jogo do histórico: {test_history['t1']} vs {test_history['t2']} ({test_history['league']})")
        print(f"   Data histórico: {test_history['date']}")
        
        # Normaliza
        league_norm = normalizer.normalize_league_name(test_history['league'])
        team1_norm = normalizer.normalize_team_name(test_history['t1'], league_norm)
        team2_norm = normalizer.normalize_team_name(test_history['t2'], league_norm)
        
        print(f"   Normalizado: {team1_norm} vs {team2_norm} ({league_norm})")
        
        # Busca no Pinnacle
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Tenta encontrar por nomes
        cursor.execute("""
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE (home_team LIKE ? OR away_team LIKE ? OR home_team LIKE ? OR away_team LIKE ?)
            OR (home_team LIKE ? OR away_team LIKE ? OR home_team LIKE ? OR away_team LIKE ?)
        """, (f"%{test_history['t1']}%", f"%{test_history['t1']}%", 
              f"%{test_history['t2']}%", f"%{test_history['t2']}%",
              f"%{team1_norm}%", f"%{team1_norm}%",
              f"%{team2_norm}%", f"%{team2_norm}%"))
        
        matches = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        if matches:
            print(f"   {Colors.BRIGHT_GREEN}Encontrados {len(matches)} possíveis matches no Pinnacle:{Colors.RESET}")
            for match in matches[:3]:
                print(f"      - {match['home_team']} vs {match['away_team']} ({match['league_name']})")
                print(f"        Data: {match['start_time']} | Status: {match['status']}")
        else:
            print(f"   {Colors.YELLOW}Nenhum match encontrado no Pinnacle{Colors.RESET}")
    
    # 5. Verifica formato de datas
    print(f"\n{Colors.BRIGHT_BLUE}5. FORMATO DE DATAS:{Colors.RESET}")
    if pinnacle_games and history_games:
        pinnacle_date = pinnacle_games[0]['start_time']
        history_date = history_games[0]['date']
        
        print(f"   Formato Pinnacle: {pinnacle_date} (tipo: {type(pinnacle_date)})")
        print(f"   Formato Histórico: {history_date} (tipo: {type(history_date)})")
        
        # Tenta converter
        try:
            if 'T' in pinnacle_date:
                pinnacle_dt = datetime.strptime(pinnacle_date, '%Y-%m-%dT%H:%M:%S')
            else:
                pinnacle_dt = datetime.strptime(pinnacle_date, '%Y-%m-%d %H:%M:%S')
            
            history_dt = datetime.strptime(history_date, '%Y-%m-%d %H:%M:%S')
            
            diff = abs((pinnacle_dt - history_dt).total_seconds() / 3600)
            print(f"   Diferença: {diff:.2f} horas")
            
            if diff > 2:
                print(f"   {Colors.YELLOW}[AVISO] Diferença maior que 2 horas - pode não fazer match{Colors.RESET}")
        except Exception as e:
            print(f"   {Colors.YELLOW}Erro ao converter datas: {e}{Colors.RESET}")

if __name__ == "__main__":
    main()
