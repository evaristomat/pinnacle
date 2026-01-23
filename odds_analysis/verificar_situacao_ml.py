"""
Verifica situação real do método ML
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from config import PINNACLE_DB, HISTORY_DB
from odds_analyzer import Colors, OddsAnalyzer
from normalizer import get_normalizer

def main():
    """Verifica situação completa."""
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}VERIFICAÇÃO COMPLETA: Situação do Método ML{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    # 1. Verifica jogos no Pinnacle
    print(f"{Colors.BRIGHT_BLUE}1. JOGOS NO BANCO PINNACLE:{Colors.RESET}")
    if not PINNACLE_DB.exists():
        print(f"   {Colors.YELLOW}Banco não encontrado{Colors.RESET}")
        return
    
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Status dos jogos
    cursor.execute("SELECT status, COUNT(*) as count FROM games GROUP BY status")
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
    print(f"   Status: {status_counts}")
    
    # Jogos antigos (mais de 1 dia)
    cursor.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        WHERE start_time < datetime('now', '-1 day')
        ORDER BY start_time DESC
        LIMIT 10
    """)
    
    old_games = [dict(row) for row in cursor.fetchall()]
    print(f"   Jogos com mais de 1 dia: {len(old_games)}")
    
    if old_games:
        print(f"   {Colors.YELLOW}[AVISO] Há jogos antigos no banco ainda com status 'scheduled'{Colors.RESET}")
        for game in old_games[:3]:
            print(f"      - {game['home_team']} vs {game['away_team']} ({game['start_time']}) - Status: {game['status']}")
    else:
        print(f"   {Colors.BRIGHT_GREEN}[OK] Nenhum jogo antigo no banco{Colors.RESET}")
    
    conn.close()
    
    # 2. Verifica get_upcoming_games
    print(f"\n{Colors.BRIGHT_BLUE}2. FILTRO get_upcoming_games:{Colors.RESET}")
    analyzer = OddsAnalyzer()
    
    # Busca jogos futuros (filtro padrão)
    upcoming = analyzer.get_upcoming_games()
    print(f"   Jogos retornados por get_upcoming_games(): {len(upcoming)}")
    
    # Verifica se há jogos antigos que não são retornados
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM games
        WHERE status != 'final' AND status != 'Final'
        AND start_time < datetime('now', '-1 day')
    """)
    
    old_scheduled = cursor.fetchone()['count']
    print(f"   Jogos antigos com status 'scheduled': {old_scheduled}")
    
    if old_scheduled > 0:
        print(f"   {Colors.YELLOW}[AVISO] Há {old_scheduled} jogos antigos que seriam analisados mas não têm draft{Colors.RESET}")
    
    conn.close()
    
    # 3. Testa matching direto
    print(f"\n{Colors.BRIGHT_BLUE}3. TESTE DE MATCHING DIRETO:{Colors.RESET}")
    
    if old_games:
        test_game = old_games[0]
        print(f"   Testando jogo: {test_game['home_team']} vs {test_game['away_team']}")
        print(f"   Data: {test_game['start_time']}")
        print(f"   Status: {test_game['status']}")
        
        # Normaliza
        normalizer = get_normalizer()
        league_norm = normalizer.normalize_league_name(test_game['league_name'])
        team1_norm = normalizer.normalize_team_name(test_game['home_team'], league_norm)
        team2_norm = normalizer.normalize_team_name(test_game['away_team'], league_norm)
        
        print(f"   Normalizado: {team1_norm} vs {team2_norm} ({league_norm})")
        
        # Verifica se existe no histórico
        exists = analyzer.game_exists_in_history(team1_norm, team2_norm, league_norm, test_game['start_time'])
        print(f"   Existe no histórico: {Colors.BRIGHT_GREEN if exists else Colors.YELLOW}{'SIM' if exists else 'NAO'}{Colors.RESET}")
        
        if exists:
            # Busca draft
            draft_data = analyzer.get_draft_data(team1_norm, team2_norm, league_norm, test_game['start_time'])
            if draft_data:
                print(f"   {Colors.BRIGHT_GREEN}[OK] Draft encontrado! Método ML funcionaria!{Colors.RESET}")
            else:
                print(f"   {Colors.YELLOW}[AVISO] Existe no histórico mas draft não encontrado{Colors.RESET}")
    
    # 4. Conclusão
    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}CONCLUSÃO:{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}\n")
    
    if old_scheduled > 0:
        print(f"{Colors.BRIGHT_GREEN}[OPORTUNIDADE] Há {old_scheduled} jogos antigos no banco que podem ter draft!{Colors.RESET}")
        print(f"   {Colors.BRIGHT_BLUE}Sugestão:{Colors.RESET} Modificar get_upcoming_games() para incluir jogos antigos")
        print(f"   {Colors.BRIGHT_BLUE}ou:{Colors.RESET} Criar função para analisar jogos antigos com draft")
    else:
        print(f"{Colors.YELLOW}[INFO] Não há jogos antigos no banco Pinnacle{Colors.RESET}")
        print(f"   {Colors.BRIGHT_BLUE}Razão:{Colors.RESET} API Pinnacle só retorna jogos futuros")
        print(f"   {Colors.BRIGHT_BLUE}Conclusão:{Colors.RESET} Método ML não pode ser usado na prática atual")

if __name__ == "__main__":
    main()
