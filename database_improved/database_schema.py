"""
Schema e funções para banco de dados SQLite
Opcional: Migração de CSV para SQLite para melhor performance
"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, Optional
import logging

from config import SQLITE_DB, TRANSFORMED_CSV, LOG_FILE, LOG_LEVEL

# Configurar logging
logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='a'
)

logger = logging.getLogger(__name__)


def init_database() -> bool:
    """
    Cria o schema do banco de dados SQLite.
    
    Returns:
        True se sucesso, False caso contrário
    """
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            
            # Tabela de matchups (jogos)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS matchups (
                gameid TEXT PRIMARY KEY,
                league TEXT NOT NULL,
                year INTEGER NOT NULL,
                date TIMESTAMP NOT NULL,
                game INTEGER,
                patch TEXT,
                side TEXT,
                t1 TEXT NOT NULL,
                t2 TEXT NOT NULL,
                result_t1 INTEGER,  -- 0 = perdeu, 1 = ganhou
                gamelength REAL,    -- em minutos
                kills_t1 INTEGER,   -- kills do time 1
                kills_t2 INTEGER,   -- kills do time 2
                total_kills INTEGER,
                total_barons INTEGER,
                total_towers INTEGER,
                total_dragons INTEGER,
                total_inhibitors INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # Tabela de composições (champions por time)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS compositions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameid TEXT NOT NULL,
                team TEXT NOT NULL,  -- 't1' ou 't2'
                top TEXT,
                jung TEXT,
                mid TEXT,
                adc TEXT,
                sup TEXT,
                kills INTEGER,
                firstdragon INTEGER,
                dragons INTEGER,
                barons INTEGER,
                firstherald INTEGER,
                firstbaron INTEGER,
                firsttower INTEGER,
                towers INTEGER,
                inhibitors INTEGER,
                FOREIGN KEY (gameid) REFERENCES matchups(gameid) ON DELETE CASCADE,
                UNIQUE(gameid, team)
            )
            """)
            
            # Tabela de ligas e times (cache)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS leagues_teams (
                league TEXT NOT NULL,
                team_name TEXT NOT NULL,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                total_games INTEGER DEFAULT 0,
                total_wins INTEGER DEFAULT 0,
                total_losses INTEGER DEFAULT 0,
                PRIMARY KEY (league, team_name)
            )
            """)
            
            # Índices para performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_league ON matchups(league)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_date ON matchups(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_t1 ON matchups(t1)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_t2 ON matchups(t2)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_year ON matchups(year)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_compositions_gameid ON compositions(gameid)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_leagues_teams_league ON leagues_teams(league)")
            
            # Migração: adiciona colunas kills_t1 e kills_t2 se não existirem
            cursor.execute("PRAGMA table_info(matchups)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'kills_t1' not in columns:
                try:
                    cursor.execute("ALTER TABLE matchups ADD COLUMN kills_t1 INTEGER")
                    logger.info("Coluna kills_t1 adicionada à tabela matchups")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Erro ao adicionar kills_t1: {e}")
            
            if 'kills_t2' not in columns:
                try:
                    cursor.execute("ALTER TABLE matchups ADD COLUMN kills_t2 INTEGER")
                    logger.info("Coluna kills_t2 adicionada à tabela matchups")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Erro ao adicionar kills_t2: {e}")
            
            # Migração: adiciona colunas created_at e updated_at se não existirem
            if 'created_at' not in columns:
                try:
                    cursor.execute("ALTER TABLE matchups ADD COLUMN created_at TIMESTAMP")
                    # Atualiza registros existentes com data atual
                    cursor.execute("UPDATE matchups SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
                    logger.info("Coluna created_at adicionada à tabela matchups")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Erro ao adicionar created_at: {e}")
            
            if 'updated_at' not in columns:
                try:
                    cursor.execute("ALTER TABLE matchups ADD COLUMN updated_at TIMESTAMP")
                    # Atualiza registros existentes com data atual
                    cursor.execute("UPDATE matchups SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
                    logger.info("Coluna updated_at adicionada à tabela matchups")
                except sqlite3.OperationalError as e:
                    logger.warning(f"Erro ao adicionar updated_at: {e}")
            
            conn.commit()
        
        print(f"[OK] Banco de dados inicializado: {SQLITE_DB}")
        logger.info(f"Banco de dados inicializado: {SQLITE_DB}")
        return True
        
    except Exception as e:
        print(f"[ERRO] Erro ao inicializar banco: {e}")
        logger.error(f"Erro ao inicializar banco: {e}", exc_info=True)
        return False


def import_csv_to_database() -> bool:
    """
    Importa dados do CSV transformado para o banco SQLite.
    
    Returns:
        True se sucesso, False caso contrário
    """
    if not TRANSFORMED_CSV.exists():
        print(f"[ERRO] Arquivo não encontrado: {TRANSFORMED_CSV}")
        return False
    
    try:
        print(f"[LENDO] Lendo CSV: {TRANSFORMED_CSV.name}")
        df = pd.read_csv(TRANSFORMED_CSV, low_memory=False)
        print(f"   Linhas: {len(df):,}")
        
        # Inicializa banco se necessário
        if not SQLITE_DB.exists():
            init_database()
        else:
            # Verifica se precisa de migração (PRIMARY KEY ou colunas faltando)
            with sqlite3.connect(SQLITE_DB) as conn:
                cursor = conn.cursor()
                
                # Verifica se gameid é PRIMARY KEY
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='matchups'")
                table_sql = cursor.fetchone()
                needs_recreate = False
                
                if table_sql and 'PRIMARY KEY' not in table_sql[0].upper():
                    print("   [INFO] Tabela matchups sem PRIMARY KEY, recriando...")
                    needs_recreate = True
                
                cursor.execute("PRAGMA table_info(matchups)")
                columns = [col[1] for col in cursor.fetchall()]
                
                if 'created_at' not in columns or 'updated_at' not in columns:
                    if not needs_recreate:
                        print("   [INFO] Adicionando colunas created_at/updated_at...")
                    needs_recreate = True
                
                if needs_recreate:
                    # Recria tabela com estrutura correta
                    print("   [INFO] Migrando tabela matchups...")
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS matchups_new (
                            gameid TEXT PRIMARY KEY,
                            league TEXT NOT NULL,
                            year INTEGER NOT NULL,
                            date TIMESTAMP NOT NULL,
                            game INTEGER,
                            patch TEXT,
                            side TEXT,
                            t1 TEXT NOT NULL,
                            t2 TEXT NOT NULL,
                            result_t1 INTEGER,
                            gamelength REAL,
                            kills_t1 INTEGER,
                            kills_t2 INTEGER,
                            total_kills INTEGER,
                            total_barons INTEGER,
                            total_towers INTEGER,
                            total_dragons INTEGER,
                            total_inhibitors INTEGER,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    
                    # Copia dados existentes (remove duplicatas mantendo o mais recente)
                    cursor.execute("""
                        INSERT INTO matchups_new 
                        SELECT DISTINCT gameid, league, year, date, game, patch, side, t1, t2, 
                               result_t1, gamelength, kills_t1, kills_t2, total_kills, 
                               total_barons, total_towers, total_dragons, total_inhibitors,
                               COALESCE(created_at, CURRENT_TIMESTAMP) as created_at,
                               CURRENT_TIMESTAMP as updated_at
                        FROM matchups
                        WHERE gameid IN (
                            SELECT gameid FROM matchups 
                            GROUP BY gameid 
                            HAVING MAX(COALESCE(updated_at, date))
                        )
                    """)
                    
                    # Remove tabela antiga e renomeia nova
                    cursor.execute("DROP TABLE matchups")
                    cursor.execute("ALTER TABLE matchups_new RENAME TO matchups")
                    
                    # Recria índices
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_league ON matchups(league)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_date ON matchups(date)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_t1 ON matchups(t1)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_t2 ON matchups(t2)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matchups_year ON matchups(year)")
                    
                    print("   [OK] Migração concluída")
                    logger.info("Tabela matchups migrada com sucesso")
                
                # Verifica e migra tabela compositions se necessário
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='compositions'")
                comp_sql = cursor.fetchone()
                needs_comp_migration = False
                
                if comp_sql and 'UNIQUE' not in comp_sql[0].upper():
                    print("   [INFO] Tabela compositions sem UNIQUE constraint, recriando...")
                    needs_comp_migration = True
                
                if needs_comp_migration:
                    print("   [INFO] Migrando tabela compositions...")
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS compositions_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            gameid TEXT NOT NULL,
                            team TEXT NOT NULL,
                            top TEXT,
                            jung TEXT,
                            mid TEXT,
                            adc TEXT,
                            sup TEXT,
                            kills INTEGER,
                            firstdragon INTEGER,
                            dragons INTEGER,
                            barons INTEGER,
                            firstherald INTEGER,
                            firstbaron INTEGER,
                            firsttower INTEGER,
                            towers INTEGER,
                            inhibitors INTEGER,
                            FOREIGN KEY (gameid) REFERENCES matchups(gameid) ON DELETE CASCADE,
                            UNIQUE(gameid, team)
                        )
                    """)
                    
                    # Copia dados existentes removendo duplicatas
                    cursor.execute("""
                        INSERT INTO compositions_new (gameid, team, top, jung, mid, adc, sup, kills,
                            firstdragon, dragons, barons, firstherald, firstbaron, firsttower, towers, inhibitors)
                        SELECT DISTINCT gameid, team, top, jung, mid, adc, sup, kills,
                            firstdragon, dragons, barons, firstherald, firstbaron, firsttower, towers, inhibitors
                        FROM compositions
                    """)
                    
                    cursor.execute("DROP TABLE compositions")
                    cursor.execute("ALTER TABLE compositions_new RENAME TO compositions")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compositions_gameid ON compositions(gameid)")
                    
                    print("   [OK] Migração de compositions concluída")
                    logger.info("Tabela compositions migrada com sucesso")
                
                conn.commit()
        
        # Valida se gameid existe ou gera
        if 'gameid' not in df.columns:
            import hashlib
            print("   [INFO] Gerando gameid unico para cada matchup...")
            df['gameid'] = df.apply(
                lambda row: hashlib.md5(
                    f"{row.get('league', '')}_{row.get('date', '')}_{row.get('t1', '')}_{row.get('t2', '')}_{row.get('game', '')}".encode()
                ).hexdigest(),
                axis=1
            )
        
        # Valida gameids antes de processar
        df = df[df['gameid'].notna() & (df['gameid'] != '')].copy()
        if len(df) == 0:
            print(f"[ERRO] Nenhum registro valido com gameid encontrado")
            return False
        
        with sqlite3.connect(SQLITE_DB) as conn:
            # Insere matchups
            print("[IMPORTANDO] Importando matchups...")
            
            # Seleciona colunas para matchups (inclui kills individuais se disponíveis)
            matchup_cols = ['gameid', 'league', 'year', 'date', 'game', 'patch', 'side',
                          't1', 't2', 'result_t1', 'gamelength']
            
            # Adiciona kills individuais se existirem no CSV
            if 'kills_t1' in df.columns:
                matchup_cols.append('kills_t1')
            if 'kills_t2' in df.columns:
                matchup_cols.append('kills_t2')
            
            # Adiciona totais
            matchup_cols.extend(['total_kills', 'total_barons', 'total_towers', 
                                 'total_dragons', 'total_inhibitors'])
            
            # Filtra apenas colunas que existem no DataFrame
            available_cols = [col for col in matchup_cols if col in df.columns]
            df_matchups = df[available_cols].copy()
            
            # Faz upsert (INSERT OR REPLACE) para evitar duplicatas
            cursor = conn.cursor()
            
            # Verifica quantos gameids já existem no banco (com created_at para preservar)
            existing_data = {}
            try:
                cursor.execute("SELECT gameid, created_at FROM matchups")
                existing_data = {row[0]: row[1] for row in cursor.fetchall()}
            except sqlite3.OperationalError:
                # Tabela não existe ainda, todos serão novos
                pass
            
            # Prepara SQL uma vez
            placeholders = ', '.join(['?' for _ in available_cols])
            columns = ', '.join(available_cols)
            
            # Prepara dados para batch insert
            new_count = 0
            updated_count = 0
            batch_data = []
            preserved_created_at = {}  # Guarda created_at para preservar depois
            
            for _, row in df_matchups.iterrows():
                gameid = row['gameid']
                is_new = gameid not in existing_data
                
                # Prepara valores
                values = tuple(row[col] for col in available_cols)
                batch_data.append(values)
                
                if is_new:
                    new_count += 1
                else:
                    updated_count += 1
                    # Guarda created_at original para preservar depois
                    preserved_created_at[gameid] = existing_data[gameid]
            
            # Executa batch insert (INSERT OR REPLACE substitui tudo, então precisamos preservar created_at depois)
            if batch_data:
                cursor.executemany(f"""
                    INSERT OR REPLACE INTO matchups ({columns}, updated_at)
                    VALUES ({placeholders}, CURRENT_TIMESTAMP)
                """, batch_data)
            
            # Preserva created_at dos registros que já existiam
            if preserved_created_at:
                for gameid, created_at in preserved_created_at.items():
                    cursor.execute("""
                        UPDATE matchups 
                        SET created_at = ? 
                        WHERE gameid = ?
                    """, (created_at, gameid))
            
            conn.commit()
            print(f"   [OK] {len(df_matchups):,} matchups processados ({new_count:,} novos, {updated_count:,} atualizados)")
        
            # Prepara composições
            print("[IMPORTANDO] Importando composicoes...")
            compositions_data = []
            
            for _, row in df.iterrows():
                # Time 1
                compositions_data.append({
                'gameid': row.get('gameid'),
                'team': 't1',
                'top': row.get('top_t1'),
                'jung': row.get('jung_t1'),
                'mid': row.get('mid_t1'),
                'adc': row.get('adc_t1'),
                'sup': row.get('sup_t1'),
                'kills': row.get('kills_t1'),
                'firstdragon': row.get('firstdragon_t1'),
                'dragons': row.get('dragons_t1'),
                'barons': row.get('barons_t1'),
                'firstherald': row.get('firstherald_t1'),
                'firstbaron': row.get('firstbaron_t1'),
                'firsttower': row.get('firsttower_t1'),
                'towers': row.get('towers_t1'),
                'inhibitors': row.get('inhibitors_t1'),
                })
                
                # Time 2
                compositions_data.append({
                'gameid': row.get('gameid'),
                'team': 't2',
                'top': row.get('top_t2'),
                'jung': row.get('jung_t2'),
                'mid': row.get('mid_t2'),
                'adc': row.get('adc_t2'),
                'sup': row.get('sup_t2'),
                'kills': row.get('kills_t2'),
                'firstdragon': row.get('firstdragon_t2'),
                'dragons': row.get('dragons_t2'),
                'barons': row.get('barons_t2'),
                'firstherald': row.get('firstherald_t2'),
                'firstbaron': row.get('firstbaron_t2'),
                'firsttower': row.get('firsttower_t2'),
                'towers': row.get('towers_t2'),
                'inhibitors': row.get('inhibitors_t2'),
                })
            
            df_compositions = pd.DataFrame(compositions_data)
            
            # Faz upsert para composições também (usando UNIQUE constraint gameid, team)
            # Verifica quais composições já existem (batch check para performance)
            existing_compositions = set()
            try:
                cursor.execute("SELECT gameid, team FROM compositions")
                existing_compositions = {(row[0], row[1]) for row in cursor.fetchall()}
            except sqlite3.OperationalError:
                # Tabela não existe ainda, todas serão novas
                pass
            
            # Prepara batch data para composições
            new_comp_count = 0
            updated_comp_count = 0
            comp_batch_data = []
            
            for _, row in df_compositions.iterrows():
                comp_key = (row['gameid'], row['team'])
                is_new = comp_key not in existing_compositions
                
                comp_batch_data.append((
                    row['gameid'], row['team'], row['top'], row['jung'], row['mid'], 
                    row['adc'], row['sup'], row['kills'], row['firstdragon'], row['dragons'],
                    row['barons'], row['firstherald'], row['firstbaron'], row['firsttower'],
                    row['towers'], row['inhibitors']
                ))
                
                if is_new:
                    new_comp_count += 1
                    existing_compositions.add(comp_key)
                else:
                    updated_comp_count += 1
            
            # Executa batch insert para composições
            if comp_batch_data:
                cursor.executemany("""
                    INSERT OR REPLACE INTO compositions 
                    (gameid, team, top, jung, mid, adc, sup, kills, firstdragon, dragons, 
                     barons, firstherald, firstbaron, firsttower, towers, inhibitors)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, comp_batch_data)
            
            conn.commit()
            print(f"   [OK] {len(df_compositions):,} composicoes processadas ({new_comp_count:,} novas, {updated_comp_count:,} atualizadas)")
            
            # Atualiza cache de ligas e times
            print("[ATUALIZANDO] Atualizando cache de ligas e times...")
            update_leagues_teams_cache(conn)
        
            db_size = SQLITE_DB.stat().st_size / 1024 / 1024
            print(f"[OK] Importacao concluida!")
            print(f"   Tamanho do banco: {db_size:.2f} MB")
            logger.info(f"Importação concluída: {len(df):,} matchups")
        
        return True
        
    except Exception as e:
        print(f"[ERRO] Erro na importacao: {e}")
        logger.error(f"Erro na importação: {e}", exc_info=True)
        return False


def update_leagues_teams_cache(conn: sqlite3.Connection):
    """Atualiza cache de ligas e times baseado nos matchups."""
    cursor = conn.cursor()
    
    # Limpa cache antigo
    cursor.execute("DELETE FROM leagues_teams")
    
    # Insere times do time 1
    cursor.execute("""
        INSERT INTO leagues_teams (league, team_name, first_seen, last_seen, total_games, total_wins, total_losses)
        SELECT 
            league,
            t1 as team_name,
            MIN(date) as first_seen,
            MAX(date) as last_seen,
            COUNT(*) as total_games,
            SUM(result_t1) as total_wins,
            SUM(1 - result_t1) as total_losses
        FROM matchups
        GROUP BY league, t1
    """)
    
    # Insere/atualiza times do time 2
    # Usa CASE para MIN/MAX corretamente no ON CONFLICT
    cursor.execute("""
        INSERT INTO leagues_teams (league, team_name, first_seen, last_seen, total_games, total_wins, total_losses)
        SELECT 
            league,
            t2 as team_name,
            MIN(date) as first_seen,
            MAX(date) as last_seen,
            COUNT(*) as total_games,
            SUM(1 - result_t1) as total_wins,
            SUM(result_t1) as total_losses
        FROM matchups
        GROUP BY league, t2
        ON CONFLICT(league, team_name) DO UPDATE SET
            first_seen = CASE 
                WHEN excluded.first_seen < leagues_teams.first_seen THEN excluded.first_seen 
                ELSE leagues_teams.first_seen 
            END,
            last_seen = CASE 
                WHEN excluded.last_seen > leagues_teams.last_seen THEN excluded.last_seen 
                ELSE leagues_teams.last_seen 
            END,
            total_games = leagues_teams.total_games + excluded.total_games,
            total_wins = leagues_teams.total_wins + excluded.total_wins,
            total_losses = leagues_teams.total_losses + excluded.total_losses
    """)
    
    conn.commit()
    
    count = cursor.execute("SELECT COUNT(*) FROM leagues_teams").fetchone()[0]
    print(f"   [OK] {count:,} times no cache")


def get_database_stats() -> Dict:
    """Retorna estatísticas do banco de dados."""
    if not SQLITE_DB.exists():
        return {}
    
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            
            stats = {
                'total_matchups': cursor.execute("SELECT COUNT(*) FROM matchups").fetchone()[0],
                'total_compositions': cursor.execute("SELECT COUNT(*) FROM compositions").fetchone()[0],
                'total_leagues': cursor.execute("SELECT COUNT(DISTINCT league) FROM matchups").fetchone()[0],
                'total_teams': cursor.execute("SELECT COUNT(*) FROM leagues_teams").fetchone()[0],
                'date_range': cursor.execute("SELECT MIN(date), MAX(date) FROM matchups").fetchone(),
            }
            
            return stats
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {e}")
        return {}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "init":
            init_database()
        elif command == "import":
            init_database()
            import_csv_to_database()
        elif command == "stats":
            stats = get_database_stats()
            if stats:
                print("\n[ESTATISTICAS] Estatisticas do Banco de Dados:")
                print(f"   Matchups: {stats['total_matchups']:,}")
                print(f"   Composicoes: {stats['total_compositions']:,}")
                print(f"   Ligas: {stats['total_leagues']}")
                print(f"   Times: {stats['total_teams']:,}")
                if stats['date_range'][0]:
                    print(f"   Periodo: {stats['date_range'][0]} ate {stats['date_range'][1]}")
            else:
                print("[ERRO] Banco de dados nao encontrado ou vazio")
        else:
            print("Comandos disponíveis:")
            print("  python database_schema.py init    - Inicializa o banco")
            print("  python database_schema.py import  - Importa CSV para o banco")
            print("  python database_schema.py stats   - Mostra estatísticas")
    else:
        print("Uso: python database_schema.py [comando]")
        print("Comandos: init, import, stats")
