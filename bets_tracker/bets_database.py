"""
Schema e funções para o banco de dados de apostas
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json

from config import BETS_DB

logger = logging.getLogger(__name__)


def init_database():
    """Inicializa o banco de dados de apostas."""
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    # Tabela de apostas
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matchup_id INTEGER NOT NULL,
            game_date TEXT NOT NULL,
            league_name TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            
            -- Dados da aposta
            market_type TEXT NOT NULL,
            line_value REAL,
            side TEXT NOT NULL,
            odd_decimal REAL NOT NULL,
            
            -- Análise
            metodo TEXT NOT NULL DEFAULT 'probabilidade_empirica',  -- Método de análise usado
            expected_value REAL NOT NULL,
            edge REAL NOT NULL,
            empirical_prob REAL,
            implied_prob REAL,
            historical_mean REAL,
            historical_std REAL,
            historical_games INTEGER,
            
            -- Status
            status TEXT DEFAULT 'pending',  -- pending, won, lost, void
            result_value REAL,  -- Valor real (ex: total_kills)
            result_date TEXT,  -- Data em que o resultado foi atualizado
            
            -- Metadados
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            
            -- JSON com dados adicionais
            metadata TEXT
        )
    """)
    
    # Índices para performance
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_matchup_id ON bets(matchup_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status ON bets(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_game_date ON bets(game_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_league_teams ON bets(league_name, home_team, away_team)
    """)
    
    # Migração: adiciona coluna metodo se não existir
    cursor.execute("PRAGMA table_info(bets)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'metodo' not in columns:
        try:
            cursor.execute("ALTER TABLE bets ADD COLUMN metodo TEXT NOT NULL DEFAULT 'probabilidade_empirica'")
            print(f"[MIGRACAO] Coluna metodo adicionada à tabela bets")
        except sqlite3.OperationalError as e:
            print(f"[AVISO] Erro ao adicionar coluna metodo: {e}")
    
    # Cria índice após garantir que a coluna existe
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_metodo ON bets(metodo)
    """)
    
    # Tabela de correções de nomes (para matching)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS name_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,  -- 'pinnacle' ou 'history'
            type TEXT NOT NULL,  -- 'team' ou 'league'
            original_name TEXT NOT NULL,
            corrected_name TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            UNIQUE(source, type, original_name)
        )
    """)
    
    # Índices para correções
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_corrections_lookup 
        ON name_corrections(source, type, original_name)
    """)
    
    conn.commit()
    conn.close()
    print(f"[OK] Banco de apostas inicializado: {BETS_DB}")


def save_bet(bet_data: Dict) -> Optional[int]:
    """
    Salva uma aposta no banco de dados.
    Verifica duplicatas antes de salvar.
    
    Args:
        bet_data: Dicionário com dados da aposta
        
    Returns:
        ID da aposta salva, ou None se já existir
    """
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    # Verifica se já existe aposta idêntica
    cursor.execute("""
        SELECT id FROM bets
        WHERE matchup_id = ? 
          AND market_type = ?
          AND line_value = ?
          AND side = ?
          AND metodo = ?
          AND status = 'pending'
    """, (
        bet_data['matchup_id'],
        bet_data['market_type'],
        bet_data.get('line_value'),
        bet_data['side'],
        bet_data.get('metodo', 'probabilidade_empirica')
    ))
    
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return None  # Já existe, não salva duplicata
    
    now = datetime.now().isoformat()
    
    # Prepara metadata JSON
    metadata = bet_data.get('metadata', {})
    if isinstance(metadata, dict):
        metadata_json = json.dumps(metadata)
    else:
        metadata_json = metadata
    
    cursor.execute("""
        INSERT INTO bets (
            matchup_id, game_date, league_name, home_team, away_team,
            market_type, line_value, side, odd_decimal,
            metodo, expected_value, edge, empirical_prob, implied_prob,
            historical_mean, historical_std, historical_games,
            status, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        bet_data['matchup_id'],
        bet_data['game_date'],
        bet_data['league_name'],
        bet_data['home_team'],
        bet_data['away_team'],
        bet_data['market_type'],
        bet_data.get('line_value'),
        bet_data['side'],
        bet_data['odd_decimal'],
        bet_data.get('metodo', 'probabilidade_empirica'),  # Método padrão
        bet_data['expected_value'],
        bet_data['edge'],
        bet_data.get('empirical_prob'),
        bet_data.get('implied_prob'),
        bet_data.get('historical_mean'),
        bet_data.get('historical_std'),
        bet_data.get('historical_games'),
        bet_data.get('status', 'pending'),
        now,
        now,
        metadata_json
    ))
    
    bet_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return bet_id


def get_pending_bets() -> List[Dict]:
    """Retorna todas as apostas pendentes (sem resultado)."""
    conn = sqlite3.connect(BETS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM bets
        WHERE status = 'pending'
        ORDER BY game_date ASC
    """)
    
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return bets


def update_bet_result(bet_id: int, result_value: float, status: str = 'won'):
    """
    Atualiza resultado de uma aposta.
    
    Args:
        bet_id: ID da aposta
        result_value: Valor real (ex: total_kills)
        status: 'won', 'lost', ou 'void'
    """
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
        UPDATE bets
        SET status = ?,
            result_value = ?,
            result_date = ?,
            updated_at = ?
        WHERE id = ?
    """, (status, result_value, now, now, bet_id))
    
    conn.commit()
    conn.close()


def get_bet_stats() -> Dict:
    """Retorna estatísticas das apostas."""
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    # Total de apostas
    cursor.execute("SELECT COUNT(*) FROM bets")
    total = cursor.fetchone()[0]
    
    # Por status
    cursor.execute("""
        SELECT status, COUNT(*) 
        FROM bets 
        GROUP BY status
    """)
    by_status = {row[0]: row[1] for row in cursor.fetchall()}
    
    # Por método
    try:
        cursor.execute("""
            SELECT metodo, COUNT(*) 
            FROM bets 
            GROUP BY metodo
        """)
        by_metodo = {row[0]: row[1] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        # Se coluna metodo não existir (banco antigo)
        by_metodo = {}
    
    # ROI (se houver resultados)
    cursor.execute("""
        SELECT 
            COUNT(*) as total_resolved,
            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
            AVG(CASE WHEN status = 'won' THEN odd_decimal ELSE 0 END) as avg_win_odd,
            AVG(expected_value) as avg_ev
        FROM bets
        WHERE status IN ('won', 'lost')
    """)
    
    result = cursor.fetchone()
    if result and result[0]:
        roi_data = {
            'total_resolved': result[0],
            'wins': result[1],
            'losses': result[2],
            'win_rate': (result[1] / result[0] * 100) if result[0] > 0 else 0,
            'avg_win_odd': result[3] or 0,
            'avg_ev': result[4] or 0
        }
    else:
        roi_data = {
            'total_resolved': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0,
            'avg_win_odd': 0,
            'avg_ev': 0
        }
    
    conn.close()
    
    return {
        'total': total,
        'by_status': by_status,
        'by_metodo': by_metodo,
        'roi': roi_data
    }


def save_name_correction(source: str, type: str, original: str, corrected: str, confidence: float = 1.0):
    """
    Salva uma correção de nome para matching futuro.
    
    Args:
        source: 'pinnacle' ou 'history'
        type: 'team' ou 'league'
        original: Nome original
        corrected: Nome corrigido
        confidence: Confiança na correção (0.0 a 1.0)
    """
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    now = datetime.now().isoformat()
    
    cursor.execute("""
        INSERT OR REPLACE INTO name_corrections 
        (source, type, original_name, corrected_name, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (source, type, original, corrected, confidence, now))
    
    conn.commit()
    conn.close()


def get_name_corrections(source: Optional[str] = None, type: Optional[str] = None) -> Dict:
    """
    Retorna correções de nomes salvas.
    
    Args:
        source: Filtrar por source ('pinnacle' ou 'history')
        type: Filtrar por type ('team' ou 'league')
        
    Returns:
        Dicionário com correções organizadas
    """
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    query = "SELECT * FROM name_corrections WHERE 1=1"
    params = []
    
    if source:
        query += " AND source = ?"
        params.append(source)
    if type:
        query += " AND type = ?"
        params.append(type)
    
    cursor.execute(query, params)
    
    corrections = {}
    for row in cursor.fetchall():
        key = f"{row[2]}_{row[3]}"  # source_type
        if key not in corrections:
            corrections[key] = []
        corrections[key].append({
            'original': row[4],
            'corrected': row[5],
            'confidence': row[6]
        })
    
    conn.close()
    return corrections
