import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DB_PATH = Path(__file__).parent / "pinnacle_data.db"

def init_database():
    """Inicializa o banco de dados criando as tabelas necessárias"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabela de times
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            league_name TEXT NOT NULL,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_games INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            UNIQUE(team_name, league_name)
        )
    """)
    
    # Tabela de jogos
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            matchup_id INTEGER PRIMARY KEY,
            league_name TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            start_time TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Tabela de markets com estrutura melhorada
    # Cada linha representa uma opção específica (home/away, over/under) com sua odd
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matchup_id INTEGER NOT NULL,
            market_type TEXT NOT NULL,
            mapa INTEGER NOT NULL,
            line_value REAL,
            side TEXT,
            odd_decimal REAL NOT NULL,
            is_alternate INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (matchup_id) REFERENCES games(matchup_id) ON DELETE CASCADE,
            UNIQUE(matchup_id, market_type, mapa, line_value, side, is_alternate)
        )
    """)
    
    # Migração: Remove coluna odd_american e converte para odd_decimal se existir
    cursor.execute("PRAGMA table_info(markets)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'odd_american' in columns and 'odd_decimal' not in columns:
        print("Convertendo odd_american para odd_decimal...")
        # SQLite não suporta DROP COLUMN, então criamos nova tabela
        cursor.execute("""
            CREATE TABLE markets_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                matchup_id INTEGER NOT NULL,
                market_type TEXT NOT NULL,
                mapa INTEGER NOT NULL,
                line_value REAL,
                side TEXT,
                odd_decimal REAL NOT NULL,
                is_alternate INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (matchup_id) REFERENCES games(matchup_id) ON DELETE CASCADE,
                UNIQUE(matchup_id, market_type, mapa, line_value, side, is_alternate)
            )
        """)
        # Converte odd_american para odd_decimal durante a migração
        cursor.execute("""
            INSERT INTO markets_new 
            (id, matchup_id, market_type, mapa, line_value, side, odd_decimal, is_alternate, created_at)
            SELECT 
                id, 
                matchup_id, 
                market_type, 
                mapa, 
                line_value, 
                side,
                CASE 
                    WHEN odd_american > 0 THEN ROUND((odd_american / 100.0) + 1, 2)
                    WHEN odd_american < 0 THEN ROUND((100.0 / ABS(odd_american)) + 1, 2)
                    ELSE NULL
                END as odd_decimal,
                is_alternate, 
                created_at
            FROM markets
            WHERE odd_american IS NOT NULL
        """)
        cursor.execute("DROP TABLE markets")
        cursor.execute("ALTER TABLE markets_new RENAME TO markets")
        print("  Coluna odd_american convertida para odd_decimal com sucesso")
    
    # Verifica se existe markets_v2 (nova estrutura) ou markets antiga
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND (name='markets_v2' OR name='markets')
    """)
    existing_tables = [row[0] for row in cursor.fetchall()]
    
    # Se existe markets_v2, renomeia para markets
    if 'markets_v2' in existing_tables:
        if 'markets' in existing_tables:
            # Se ambas existem, remove a antiga markets primeiro
            cursor.execute("DROP TABLE IF EXISTS markets")
        print("Renomeando markets_v2 para markets...")
        cursor.execute("ALTER TABLE markets_v2 RENAME TO markets")
        cursor.execute("DROP INDEX IF EXISTS idx_markets_v2_matchup")
        cursor.execute("DROP INDEX IF EXISTS idx_markets_v2_type")
        cursor.execute("DROP INDEX IF EXISTS idx_markets_v2_mapa")
    elif 'markets' in existing_tables:
        # Verifica se é a estrutura antiga (com market_data JSON) ou nova
        cursor.execute("PRAGMA table_info(markets)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'market_data' in columns:
            # É a estrutura antiga, precisa migrar
            print("Tabela markets antiga encontrada. Migração necessária.")
            # A migração será feita depois, por enquanto mantém
    
    # Índices para melhor performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_matchup ON markets(matchup_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_type ON markets(market_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_mapa ON markets(mapa)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_markets_line_value ON markets(line_value)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_start_time ON games(start_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_league ON games(league_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_teams ON games(home_team, away_team)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_teams_name ON teams(team_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_teams_league ON teams(league_name)")
    
    # Migração: Remove prefixo "League of Legends - " dos nomes de ligas
    migrate_league_names(cursor)
    
    # Migração: Popula tabela teams com dados existentes de games
    migrate_teams_from_games(cursor)
    
    conn.commit()
    conn.close()
    
    print(f"Banco de dados inicializado: {DB_PATH}")

def clean_league_name(league_name: str) -> str:
    """Remove o prefixo 'League of Legends - ' do nome da liga"""
    if not league_name:
        return league_name
    
    prefix = "League of Legends - "
    if league_name.startswith(prefix):
        return league_name[len(prefix):].strip()
    
    return league_name.strip()

def migrate_league_names(cursor):
    """Remove o prefixo 'League of Legends - ' dos nomes de ligas nas tabelas"""
    try:
        # Atualiza tabela games
        cursor.execute("""
            UPDATE games
            SET league_name = CASE 
                WHEN league_name LIKE 'League of Legends - %' 
                THEN SUBSTR(league_name, LENGTH('League of Legends - ') + 1)
                ELSE league_name
            END
            WHERE league_name LIKE 'League of Legends - %'
        """)
        games_updated = cursor.rowcount
        
        # Atualiza tabela teams
        cursor.execute("""
            UPDATE teams
            SET league_name = CASE 
                WHEN league_name LIKE 'League of Legends - %' 
                THEN SUBSTR(league_name, LENGTH('League of Legends - ') + 1)
                ELSE league_name
            END
            WHERE league_name LIKE 'League of Legends - %'
        """)
        teams_updated = cursor.rowcount
        
        if games_updated > 0 or teams_updated > 0:
            print(f"Migração de nomes de ligas: {games_updated} jogos e {teams_updated} times atualizados")
    except Exception as e:
        print(f"Erro na migração de nomes de ligas: {e}")

def migrate_teams_from_games(cursor):
    """Migra times da tabela games para a tabela teams"""
    try:
        # Verifica se já há times na tabela
        cursor.execute("SELECT COUNT(*) FROM teams")
        teams_count = cursor.fetchone()[0]
        
        if teams_count > 0:
            return  # Já tem times, não precisa migrar
        
        # Busca todos os jogos únicos (home_team + league_name e away_team + league_name)
        cursor.execute("""
            SELECT DISTINCT home_team, league_name FROM games
            UNION
            SELECT DISTINCT away_team, league_name FROM games
        """)
        unique_teams = cursor.fetchall()
        
        if not unique_teams:
            return  # Não há jogos ainda
        
        # Conta jogos por time
        cursor.execute("""
            SELECT home_team, league_name, COUNT(*) as count
            FROM games
            GROUP BY home_team, league_name
        """)
        home_counts = {row[0:2]: row[2] for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT away_team, league_name, COUNT(*) as count
            FROM games
            GROUP BY away_team, league_name
        """)
        away_counts = {row[0:2]: row[2] for row in cursor.fetchall()}
        
        # Insere times
        migrated = 0
        for team_name, league_name in unique_teams:
            if not team_name or not league_name:
                continue
            
            # Calcula total de jogos (home + away)
            home_count = home_counts.get((team_name, league_name), 0)
            away_count = away_counts.get((team_name, league_name), 0)
            total_games = home_count + away_count
            
            # Busca primeira e última aparição
            cursor.execute("""
                SELECT MIN(created_at) as first_seen, MAX(updated_at) as last_seen
                FROM games
                WHERE (home_team = ? OR away_team = ?) AND league_name = ?
            """, (team_name, team_name, league_name))
            dates = cursor.fetchone()
            
            first_seen = dates[0] if dates[0] else None
            last_seen = dates[1] if dates[1] else None
            
            # Insere time
            cursor.execute("""
                INSERT OR IGNORE INTO teams (team_name, league_name, total_games, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, (team_name, league_name, total_games, first_seen, last_seen))
            
            if cursor.rowcount > 0:
                migrated += 1
        
        if migrated > 0:
            print(f"Migração de times: {migrated} times migrados da tabela games")
    except Exception as e:
        print(f"Erro na migração de times: {e}")


def get_db_connection():
    """Retorna uma conexão com o banco de dados"""
    return sqlite3.connect(DB_PATH)

def upsert_team(team_name: str, league_name: str) -> bool:
    """
    Insere ou atualiza um time no banco de dados.
    Retorna True se foi inserido (novo), False se foi atualizado (existente)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verifica se o time já existe
    cursor.execute("""
        SELECT id, total_games FROM teams 
        WHERE team_name = ? AND league_name = ?
    """, (team_name, league_name))
    existing = cursor.fetchone()
    
    if existing:
        # Atualiza time existente
        cursor.execute("""
            UPDATE teams 
            SET last_seen = CURRENT_TIMESTAMP,
                total_games = total_games + 1
            WHERE team_name = ? AND league_name = ?
        """, (team_name, league_name))
        conn.commit()
        conn.close()
        return False  # Time existente, apenas atualizado
    else:
        # Insere novo time
        cursor.execute("""
            INSERT INTO teams (team_name, league_name, total_games)
            VALUES (?, ?, 1)
        """, (team_name, league_name))
        conn.commit()
        conn.close()
        return True  # Novo time inserido

def upsert_game(matchup_id: int, league_name: str, home_team: str, 
                away_team: str, start_time: str, status: str) -> bool:
    """
    Insere ou atualiza um jogo no banco de dados.
    Retorna True se foi inserido (novo), False se foi atualizado (existente)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verifica se o jogo já existe
    cursor.execute("SELECT matchup_id FROM games WHERE matchup_id = ?", (matchup_id,))
    exists = cursor.fetchone()
    
    if exists:
        # Atualiza jogo existente
        cursor.execute("""
            UPDATE games 
            SET league_name = ?, home_team = ?, away_team = ?, 
                start_time = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE matchup_id = ?
        """, (league_name, home_team, away_team, start_time, status, matchup_id))
        conn.commit()
        conn.close()
        return False  # Jogo existente, apenas atualizado
    else:
        # Insere novo jogo
        cursor.execute("""
            INSERT INTO games (matchup_id, league_name, home_team, away_team, start_time, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (matchup_id, league_name, home_team, away_team, start_time, status))
        conn.commit()
        conn.close()
        return True  # Novo jogo inserido

def market_exists(matchup_id: int, market_type: str, mapa: int, 
                 line_value: Optional[float], side: str, is_alternate: bool) -> bool:
    """Verifica se um market já existe no banco de dados"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id FROM markets 
        WHERE matchup_id = ? AND market_type = ? AND mapa = ? 
        AND (line_value = ? OR (line_value IS NULL AND ? IS NULL))
        AND side = ? AND is_alternate = ?
    """, (matchup_id, market_type, mapa, line_value, line_value, side, 1 if is_alternate else 0))
    
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def convert_american_to_decimal(american_odds: int) -> float:
    """Converte odds americanas para decimais"""
    if american_odds > 0:
        return round((american_odds / 100) + 1, 2)
    else:
        return round((100 / abs(american_odds)) + 1, 2)

def insert_market(matchup_id: int, market_type: str, mapa: int, 
                 line_value: Optional[float], side: str,
                 odd_decimal: float, is_alternate: bool) -> bool:
    """
    Insere ou atualiza um market no banco de dados.
    Retorna True se foi inserido/atualizado, False se já existia com os mesmos valores
    """
    # Valida handicap_map (não pode ter valor absoluto maior que 5)
    if market_type == 'handicap_map' and line_value is not None and abs(line_value) > 5:
        return False  # Valor inválido, não insere
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Para handicap_kills e handicap_map, verifica se existe com mesmo matchup_id, mapa, side, is_alternate
        # mas com line_value diferente (para atualizar o sinal)
        if market_type in ['handicap_kills', 'handicap_map'] and line_value is not None:
            cursor.execute("""
                SELECT id, line_value FROM markets 
                WHERE matchup_id = ? AND market_type = ? AND mapa = ? 
                AND side = ? AND is_alternate = ?
            """, (matchup_id, market_type, mapa, side, 1 if is_alternate else 0))
            existing = cursor.fetchone()
            
            if existing:
                existing_id, existing_line_value = existing
                # Se o line_value mudou (mesmo valor absoluto mas sinal diferente), atualiza
                if existing_line_value != line_value and abs(existing_line_value) == abs(line_value):
                    cursor.execute("""
                        UPDATE markets 
                        SET line_value = ?, odd_decimal = ?
                        WHERE id = ?
                    """, (line_value, odd_decimal, existing_id))
                    conn.commit()
                    conn.close()
                    return True  # Atualizado
                elif existing_line_value == line_value:
                    # Mesmo line_value, verifica se odd mudou
                    cursor.execute("""
                        SELECT odd_decimal FROM markets WHERE id = ?
                    """, (existing_id,))
                    existing_odd = cursor.fetchone()[0]
                    if existing_odd != odd_decimal:
                        cursor.execute("""
                            UPDATE markets 
                            SET odd_decimal = ?
                            WHERE id = ?
                        """, (odd_decimal, existing_id))
                        conn.commit()
                    conn.close()
                    return False  # Já existe com os mesmos valores
        
        # Verifica se já existe exatamente igual
        if market_exists(matchup_id, market_type, mapa, line_value, side, is_alternate):
            conn.close()
            return False  # Market já existe, não insere
        
        # Insere novo market
        cursor.execute("""
            INSERT INTO markets 
            (matchup_id, market_type, mapa, line_value, side, odd_decimal, is_alternate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (matchup_id, market_type, mapa, line_value, side, 
              odd_decimal, 1 if is_alternate else 0))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # Market já existe (race condition)
        return False
    finally:
        conn.close()

def save_games_and_markets(games: List[Dict]) -> Dict[str, int]:
    """
    Salva jogos e markets no banco de dados.
    Retorna estatísticas: {'new_games': int, 'updated_games': int, 'new_markets': int, 'existing_markets': int, 'new_teams': int, 'updated_teams': int}
    """
    stats = {
        'new_games': 0,
        'updated_games': 0,
        'new_markets': 0,
        'existing_markets': 0,
        'new_teams': 0,
        'updated_teams': 0
    }
    
    for game in games:
        matchup_id = game['matchup_id']
        league_name = game['league']
        home_team = game['home_team']
        away_team = game['away_team']
        
        # Salva/atualiza os times
        if home_team:
            is_new_team = upsert_team(home_team, league_name)
            if is_new_team:
                stats['new_teams'] += 1
            else:
                stats['updated_teams'] += 1
        
        if away_team:
            is_new_team = upsert_team(away_team, league_name)
            if is_new_team:
                stats['new_teams'] += 1
            else:
                stats['updated_teams'] += 1
        
        # Salva/atualiza o jogo
        is_new_game = upsert_game(
            matchup_id=matchup_id,
            league_name=league_name,
            home_team=home_team,
            away_team=away_team,
            start_time=game['start_time'],
            status=game['status']
        )
        
        if is_new_game:
            stats['new_games'] += 1
        else:
            stats['updated_games'] += 1
        
        # Processa markets do jogo
        markets = game.get('markets', {})
        
        # Moneyline
        for period, period_data in markets.get('moneyline', {}).items():
            mapa = int(period)
            if 'home' in period_data:
                if insert_market(matchup_id, 'moneyline', mapa, None, 'home', 
                               period_data['home']['decimal'], False):
                    stats['new_markets'] += 1
                else:
                    stats['existing_markets'] += 1
            if 'away' in period_data:
                if insert_market(matchup_id, 'moneyline', mapa, None, 'away', 
                               period_data['away']['decimal'], False):
                    stats['new_markets'] += 1
                else:
                    stats['existing_markets'] += 1
        
        # Handicap Map
        for period, period_data in markets.get('handicap_map', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    line_value = float(line_value_str)
                except:
                    continue
                
                # Valida: handicap_map não pode ter valor absoluto maior que 5
                if abs(line_value) > 5:
                    continue  # Pula valores inválidos
                
                is_alt = line_data.get('is_alternate', False)
                if 'home' in line_data:
                    if insert_market(matchup_id, 'handicap_map', mapa, line_value, 'home', 
                                   line_data['home']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                if 'away' in line_data:
                    if insert_market(matchup_id, 'handicap_map', mapa, line_value, 'away', 
                                   line_data['away']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
        
        # Total Map
        for period, period_data in markets.get('total_map', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    line_value = float(line_value_str)
                except:
                    continue
                
                is_alt = line_data.get('is_alternate', False)
                if 'over' in line_data:
                    if insert_market(matchup_id, 'total_map', mapa, line_value, 'over', 
                                   line_data['over']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                if 'under' in line_data:
                    if insert_market(matchup_id, 'total_map', mapa, line_value, 'under', 
                                   line_data['under']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
        
        # Total Kill Home
        for period, period_data in markets.get('total_kill_home', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    line_value = float(line_value_str)
                except:
                    continue
                
                is_alt = line_data.get('is_alternate', False)
                if 'over' in line_data:
                    if insert_market(matchup_id, 'total_kill_home', mapa, line_value, 'over', 
                                   line_data['over']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                if 'under' in line_data:
                    if insert_market(matchup_id, 'total_kill_home', mapa, line_value, 'under', 
                                   line_data['under']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
        
        # Total Kill Away
        for period, period_data in markets.get('total_kill_away', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    line_value = float(line_value_str)
                except:
                    continue
                
                is_alt = line_data.get('is_alternate', False)
                if 'over' in line_data:
                    if insert_market(matchup_id, 'total_kill_away', mapa, line_value, 'over', 
                                   line_data['over']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                if 'under' in line_data:
                    if insert_market(matchup_id, 'total_kill_away', mapa, line_value, 'under', 
                                   line_data['under']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
        
        # Handicap Kills
        for period, period_data in markets.get('handicap_kills', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    # Usa o spread do home para home e awaySpread para away, mantendo sinais originais
                    home_spread = line_data.get('home', {}).get('spread')
                    away_spread = line_data.get('away', {}).get('spread')
                    
                    if home_spread is None:
                        # Fallback: tenta usar a chave do dicionário
                        home_spread = float(line_value_str)
                    
                    if away_spread is None:
                        # Fallback: calcula como negativo do home
                        away_spread = -float(home_spread) if isinstance(home_spread, (int, float)) else -float(line_value_str)
                except:
                    continue
                
                is_alt = line_data.get('is_alternate', False)
                
                if 'home' in line_data:
                    # Para home, usa home_spread como line_value
                    home_line_value = float(home_spread)
                    if insert_market(matchup_id, 'handicap_kills', mapa, home_line_value, 'home', 
                                   line_data['home']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                
                if 'away' in line_data:
                    # Para away, usa away_spread diretamente como line_value, mantendo sinal original
                    away_line_value = float(away_spread)
                    if insert_market(matchup_id, 'handicap_kills', mapa, away_line_value, 'away', 
                                   line_data['away']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
        
        # Total Kills
        for period, period_data in markets.get('total_kills', {}).items():
            mapa = int(period)
            for line_value_str, line_data in period_data.items():
                try:
                    line_value = float(line_value_str)
                except:
                    continue
                
                is_alt = line_data.get('is_alternate', False)
                if 'over' in line_data:
                    if insert_market(matchup_id, 'total_kills', mapa, line_value, 'over', 
                                   line_data['over']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
                if 'under' in line_data:
                    if insert_market(matchup_id, 'total_kills', mapa, line_value, 'under', 
                                   line_data['under']['decimal'], is_alt):
                        stats['new_markets'] += 1
                    else:
                        stats['existing_markets'] += 1
    
    return stats

def get_all_games() -> List[Dict]:
    """Retorna todos os jogos do banco de dados com seus markets"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca todos os jogos
    cursor.execute("SELECT * FROM games ORDER BY start_time DESC")
    games_rows = cursor.fetchall()
    
    games = []
    for game_row in games_rows:
        matchup_id = game_row['matchup_id']
        
        # Busca markets deste jogo
        cursor.execute("""
            SELECT market_type, mapa, line_value, side, odd_decimal, is_alternate
            FROM markets WHERE matchup_id = ?
            ORDER BY market_type, mapa, line_value
        """, (matchup_id,))
        markets_rows = cursor.fetchall()
        
        # Reconstrói a estrutura de markets
        markets = {
            'moneyline': {},
            'handicap_map': {},
            'total_map': {},
            'total_kill_home': {},
            'total_kill_away': {},
            'handicap_kills': {},
            'total_kills': {}
        }
        
        for market_row in markets_rows:
            market_type = market_row['market_type']
            mapa = market_row['mapa']
            line_value = market_row['line_value']
            side = market_row['side']
            odd_decimal = market_row['odd_decimal']
            is_alternate = bool(market_row['is_alternate'])
            
            mapa_str = str(mapa)
            
            if market_type == 'moneyline':
                if mapa_str not in markets['moneyline']:
                    markets['moneyline'][mapa_str] = {}
                markets['moneyline'][mapa_str][side] = {
                    'decimal': odd_decimal
                }
            
            elif market_type == 'handicap_map':
                if mapa_str not in markets['handicap_map']:
                    markets['handicap_map'][mapa_str] = {}
                line_str = str(line_value)
                if line_str not in markets['handicap_map'][mapa_str]:
                    markets['handicap_map'][mapa_str][line_str] = {
                        'is_alternate': is_alternate
                    }
                markets['handicap_map'][mapa_str][line_str][side] = {
                    'spread': line_value if side == 'home' else -line_value,
                    'decimal': odd_decimal
                }
            
            elif market_type in ['total_map', 'total_kill_home', 'total_kill_away', 'total_kills']:
                if mapa_str not in markets[market_type]:
                    markets[market_type][mapa_str] = {}
                line_str = str(line_value)
                if line_str not in markets[market_type][mapa_str]:
                    markets[market_type][mapa_str][line_str] = {
                        'line': line_value,
                        'is_alternate': is_alternate
                    }
                markets[market_type][mapa_str][line_str][side] = {
                    'decimal': odd_decimal
                }
            
            elif market_type == 'handicap_kills':
                if mapa_str not in markets['handicap_kills']:
                    markets['handicap_kills'][mapa_str] = {}
                # line_value mantém o sinal original do spread (home_spread para home, awaySpread para away)
                # Usa o line_value diretamente, sem modificar o sinal
                line_str = str(line_value)
                if line_str not in markets['handicap_kills'][mapa_str]:
                    markets['handicap_kills'][mapa_str][line_str] = {
                        'is_alternate': is_alternate
                    }
                # Usa line_value diretamente, mantendo o sinal original
                markets['handicap_kills'][mapa_str][line_str][side] = {
                    'spread': line_value,
                    'decimal': odd_decimal
                }
        
        games.append({
            'matchup_id': matchup_id,
            'league': game_row['league_name'],
            'home_team': game_row['home_team'],
            'away_team': game_row['away_team'],
            'start_time': game_row['start_time'],
            'status': game_row['status'],
            'markets': markets
        })
    
    conn.close()
    return games

def get_all_teams() -> List[Dict]:
    """Retorna todos os times do banco de dados"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT team_name, league_name, first_seen, last_seen, total_games, total_wins, total_losses
        FROM teams
        ORDER BY league_name, team_name
    """)
    
    teams = []
    for row in cursor.fetchall():
        teams.append({
            'team_name': row['team_name'],
            'league_name': row['league_name'],
            'first_seen': row['first_seen'],
            'last_seen': row['last_seen'],
            'total_games': row['total_games'],
            'total_wins': row['total_wins'],
            'total_losses': row['total_losses']
        })
    
    conn.close()
    return teams

def get_teams_by_league(league_name: str) -> List[Dict]:
    """Retorna todos os times de uma liga específica"""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT team_name, league_name, first_seen, last_seen, total_games, total_wins, total_losses
        FROM teams
        WHERE league_name = ?
        ORDER BY team_name
    """, (league_name,))
    
    teams = []
    for row in cursor.fetchall():
        teams.append({
            'team_name': row['team_name'],
            'league_name': row['league_name'],
            'first_seen': row['first_seen'],
            'last_seen': row['last_seen'],
            'total_games': row['total_games'],
            'total_wins': row['total_wins'],
            'total_losses': row['total_losses']
        })
    
    conn.close()
    return teams

def get_database_stats() -> Dict:
    """Retorna estatísticas do banco de dados"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM games")
    total_games = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM markets")
    total_markets = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT matchup_id) FROM markets")
    games_with_markets = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM teams")
    total_teams = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT league_name) FROM teams")
    total_leagues = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'total_games': total_games,
        'total_markets': total_markets,
        'games_with_markets': games_with_markets,
        'total_teams': total_teams,
        'total_leagues': total_leagues
    }
