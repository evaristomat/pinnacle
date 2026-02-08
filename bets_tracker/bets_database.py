"""
Schema e funções para o banco de dados de apostas
"""
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import json
import shutil

from config import BETS_DB


def _db_path(db_path: Optional[Path] = None) -> Path:
    """
    Resolve qual banco usar.
    - None => usa o padrão BETS_DB (banco do tracker/modelo)
    - Path => usa o informado (ex: USER_BETS_DB no Streamlit)
    """
    return db_path if isinstance(db_path, Path) else BETS_DB


def get_bet_by_id(bet_id: int, db_path: Optional[Path] = None) -> Optional[Dict]:
    """Busca uma aposta por ID."""
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bets WHERE id = ?", (int(bet_id),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

logger = logging.getLogger(__name__)


def init_database(db_path: Optional[Path] = None):
    """Inicializa o banco de dados de apostas."""
    db = _db_path(db_path)
    conn = sqlite3.connect(db)
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
            mapa INTEGER,  -- Mapa do jogo (0, 1, 2, etc.) - NULL para markets sem mapa
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
    
    # Migração: adiciona coluna mapa se não existir
    if 'mapa' not in columns:
        try:
            cursor.execute("ALTER TABLE bets ADD COLUMN mapa INTEGER")
            print(f"[MIGRACAO] Coluna mapa adicionada à tabela bets")
        except sqlite3.OperationalError as e:
            print(f"[AVISO] Erro ao adicionar coluna mapa: {e}")
    
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
    print(f"[OK] Banco de apostas inicializado: {db}")


def save_bet(bet_data: Dict, db_path: Optional[Path] = None) -> Optional[int]:
    """
    Salva uma aposta no banco de dados.
    Verifica duplicatas antes de salvar.
    
    Args:
        bet_data: Dicionário com dados da aposta
        
    Returns:
        ID da aposta salva, ou None se já existir
    """
    db = _db_path(db_path)
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    
    # Verifica se já existe aposta idêntica (qualquer status: pending, won, lost, void)
    # Evita duplicar ao rodar run_all/collect novamente após atualizar resultados
    cursor.execute("""
        SELECT id FROM bets
        WHERE matchup_id = ?
          AND market_type = ?
          AND COALESCE(mapa, -1) = COALESCE(?, -1)
          AND line_value = ?
          AND side = ?
          AND metodo = ?
    """, (
        bet_data['matchup_id'],
        bet_data['market_type'],
        bet_data.get('mapa'),
        bet_data.get('line_value'),
        bet_data['side'],
        bet_data.get('metodo', 'probabilidade_empirica')
    ))
    
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return None  # Ja existe, nao salva duplicata
    
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
            market_type, mapa, line_value, side, odd_decimal,
            metodo, expected_value, edge, empirical_prob, implied_prob,
            historical_mean, historical_std, historical_games,
            status, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        bet_data['matchup_id'],
        bet_data['game_date'],
        bet_data['league_name'],
        bet_data['home_team'],
        bet_data['away_team'],
        bet_data['market_type'],
        bet_data.get('mapa'),  # Mapa do jogo (pode ser None)
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


def get_pending_bets(db_path: Optional[Path] = None) -> List[Dict]:
    """Retorna todas as apostas pendentes (sem resultado, status pending)."""
    conn = sqlite3.connect(_db_path(db_path))
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


def get_placed_bets(db_path: Optional[Path] = None) -> List[Dict]:
    """Retorna apostas marcadas como 'feita' (usuário já apostou, aguardando resultado)."""
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM bets
        WHERE status = 'feita'
        ORDER BY game_date ASC
    """)
    
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return bets


def get_resolved_bets(statuses: tuple[str, ...] = ("won", "lost", "void"), db_path: Optional[Path] = None) -> List[Dict]:
    """
    Retorna apostas resolvidas (status won/lost/void).

    Observação: no fluxo do app, apostas só viram won/lost/void depois de serem
    marcadas como 'feita' e terem sido atualizadas pelo `ResultsUpdater`.
    """
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * len(statuses))
    cursor.execute(
        f"""
        SELECT * FROM bets
        WHERE status IN ({placeholders})
        ORDER BY game_date ASC
        """,
        tuple(statuses),
    )

    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return bets


def get_bets_by_date(date_start: str, date_end: str, db_path: Optional[Path] = None) -> List[Dict]:
    """
    Retorna apostas com game_date entre date_start e date_end (inclusive).
    date_start/date_end: 'YYYY-MM-DD'. game_date pode ser ISO com T.
    """
    conn = sqlite3.connect(_db_path(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM bets
        WHERE SUBSTR(REPLACE(game_date, 'T', ' '), 1, 10) >= ?
          AND SUBSTR(REPLACE(game_date, 'T', ' '), 1, 10) <= ?
        ORDER BY game_date ASC, id ASC
    """, (date_start, date_end))
    
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return bets


def get_bets_by_metodo(metodo: Optional[str] = None) -> List[Dict]:
    """
    Retorna apostas, opcionalmente filtradas por metodo.
    metodo: 'probabilidade_empirica' | 'ml' | None (todas).
    Ordenadas por game_date.
    """
    conn = sqlite3.connect(BETS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if metodo:
        cursor.execute("""
            SELECT * FROM bets
            WHERE metodo = ?
            ORDER BY game_date ASC, id ASC
        """, (metodo,))
    else:
        cursor.execute("""
            SELECT * FROM bets
            ORDER BY game_date ASC, id ASC
        """)
    
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return bets


def get_processed_matchup_ids(metodo: Optional[str] = None) -> set:
    """
    Retorna conjunto de matchup_ids que já têm apostas no banco.
    
    Args:
        metodo: Se fornecido, retorna apenas matchup_ids com apostas desse método.
                Aceita 'ml' ou 'machinelearning' (ambos são tratados como ML)
    
    Returns:
        Set de matchup_ids já processados
    """
    if not BETS_DB.exists():
        return set()
    
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    if metodo:
        # Aceita tanto 'ml' quanto 'machinelearning'
        if metodo == 'ml':
            cursor.execute("""
                SELECT DISTINCT matchup_id FROM bets 
                WHERE metodo = 'ml' OR metodo = 'machinelearning'
            """)
        else:
            cursor.execute("""
                SELECT DISTINCT matchup_id FROM bets WHERE metodo = ?
            """, (metodo,))
    else:
        cursor.execute("""
            SELECT DISTINCT matchup_id FROM bets
        """)
    
    matchup_ids = {row[0] for row in cursor.fetchall()}
    conn.close()
    return matchup_ids


def mark_bet_placed(bet_id: int, db_path: Optional[Path] = None) -> bool:
    """
    Marca aposta como 'feita' (usuário indicou que já apostou).
    Usado para cruzar com resultados depois.
    
    Args:
        bet_id: ID da aposta
        
    Returns:
        True se atualizado, False se aposta não encontrada ou já resolvida
    """
    conn = sqlite3.connect(_db_path(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM bets WHERE id = ?", (bet_id,))
    row = cursor.fetchone()
    if not row or row[1] not in ('pending',):
        conn.close()
        return False
    now = datetime.now().isoformat()
    cursor.execute("""
        UPDATE bets
        SET status = 'feita',
            updated_at = ?
        WHERE id = ?
    """, (now, bet_id))
    conn.commit()
    conn.close()
    return True


def unmark_bet_placed(bet_id: int, db_path: Optional[Path] = None) -> bool:
    """
    Remove aposta de 'feita' voltando para 'pending'.
    
    Args:
        bet_id: ID da aposta
        
    Returns:
        True se atualizado, False se aposta não encontrada ou não estava como 'feita'
    """
    conn = sqlite3.connect(_db_path(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM bets WHERE id = ?", (bet_id,))
    row = cursor.fetchone()
    if not row or row[1] != 'feita':
        conn.close()
        return False
    now = datetime.now().isoformat()
    cursor.execute("""
        UPDATE bets
        SET status = 'pending',
            updated_at = ?
        WHERE id = ?
    """, (now, bet_id))
    conn.commit()
    conn.close()
    return True


def update_bet_result(bet_id: int, result_value: float, status: str = 'won', db_path: Optional[Path] = None):
    """
    Atualiza resultado de uma aposta.
    
    Args:
        bet_id: ID da aposta
        result_value: Valor real (ex: total_kills)
        status: 'won', 'lost', ou 'void'
    """
    conn = sqlite3.connect(_db_path(db_path))
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


def get_bet_stats(db_path: Optional[Path] = None) -> Dict:
    """Retorna estatísticas das apostas."""
    conn = sqlite3.connect(_db_path(db_path))
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
    
    def _roi_from_row(row) -> dict:
        if not row or not row[0]:
            return {'total_resolved': 0, 'wins': 0, 'losses': 0, 'win_rate': 0, 'avg_win_odd': 0, 'lucro': 0, 'return_pct': 0}
        lucro = row[4] if len(row) > 4 and row[4] is not None else 0
        n = row[0]
        return {
            'total_resolved': n,
            'wins': row[1],
            'losses': row[2],
            'win_rate': (row[1] / n * 100) if n > 0 else 0,
            'avg_win_odd': row[3] or 0,
            'lucro': lucro,
            'return_pct': (lucro / n * 100) if n > 0 else 0,
        }

    roi_sql = """
        SELECT
            COUNT(*) as total_resolved,
            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
            AVG(CASE WHEN status = 'won' THEN odd_decimal ELSE NULL END) as avg_win_odd,
            SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
        FROM bets
        WHERE status IN ('won', 'lost')
    """

    cursor.execute(roi_sql)
    roi_data = _roi_from_row(cursor.fetchone())

    cursor.execute(roi_sql + " AND metodo = ?", ('probabilidade_empirica',))
    roi_empirico = _roi_from_row(cursor.fetchone())

    # Empirico ROI 10+ e 20+ (expected_value em decimal: 0.10 = 10%, 0.20 = 20%)
    ev_filter = " AND expected_value >= ?"
    cursor.execute(roi_sql + " AND metodo = ?" + ev_filter, ('probabilidade_empirica', 0.10))
    roi_empirico_10 = _roi_from_row(cursor.fetchone())

    cursor.execute(roi_sql + " AND metodo = ?" + ev_filter, ('probabilidade_empirica', 0.20))
    roi_empirico_20 = _roi_from_row(cursor.fetchone())

    cursor.execute(roi_sql + " AND metodo = ?", ('ml',))
    roi_ml = _roi_from_row(cursor.fetchone())

    # ML ROI 10+ e 20+ (expected_value >= 10%, >= 20%)
    cursor.execute(roi_sql + " AND metodo = ?" + ev_filter, ('ml', 0.10))
    roi_ml_10 = _roi_from_row(cursor.fetchone())

    cursor.execute(roi_sql + " AND metodo = ?" + ev_filter, ('ml', 0.20))
    roi_ml_20 = _roi_from_row(cursor.fetchone())

    conn.close()

    return {
        'total': total,
        'by_status': by_status,
        'by_metodo': by_metodo,
        'roi': roi_data,
        'roi_empirico': roi_empirico,
        'roi_empirico_10': roi_empirico_10,
        'roi_empirico_20': roi_empirico_20,
        'roi_ml': roi_ml,
        'roi_ml_10': roi_ml_10,
        'roi_ml_20': roi_ml_20,
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


def update_kill_bets_map_to_one():
    """
    Atualiza todas as apostas de kills existentes que têm mapa NULL para mapa = 1.
    
    Returns:
        Número de apostas atualizadas
    """
    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()
    
    # Conta quantas apostas serão atualizadas
    cursor.execute("""
        SELECT COUNT(*) FROM bets
        WHERE market_type IN ('total_kills', 'total_kill_home', 'total_kill_away')
          AND mapa IS NULL
    """)
    count_before = cursor.fetchone()[0]
    
    if count_before == 0:
        conn.close()
        print(f"[INFO] Nenhuma aposta de kills com mapa NULL encontrada")
        return 0
    
    # Atualiza as apostas
    cursor.execute("""
        UPDATE bets
        SET mapa = 1
        WHERE market_type IN ('total_kills', 'total_kill_home', 'total_kill_away')
          AND mapa IS NULL
    """)
    
    updated_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"[OK] {updated_count} apostas de kills atualizadas para mapa = 1")
    return updated_count


def filter_best_per_map_db(
    max_per_map: int = 3,
    *,
    backup: bool = True,
    db_path: Optional[Path] = None,
) -> dict:
    """
    Filtra o banco mantendo apenas as N melhores apostas por (matchup_id, mapa, método).
    
    Estratégia:
    - ML: top N por expected_value (maior EV)
    - Empírico: top N por odd_decimal (maior odd/payoff)
    
    Args:
        max_per_map: Máximo de apostas por (matchup, mapa, método_categoria)
        backup: Se True, cria cópia do banco antes de filtrar
        db_path: Caminho do banco (default: BETS_DB)
        
    Returns:
        dict com {backup_path, total_before, total_after, deleted}
    """
    db = _db_path(db_path)
    if not db.exists():
        return {"backup_path": None, "total_before": 0, "total_after": 0, "deleted": 0}
    
    backup_path = None
    if backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db.with_name(f"{db.stem}.bak-{ts}{db.suffix}")
        shutil.copy2(db, backup_path)
        print(f"[BACKUP] Backup criado: {backup_path}")
    
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Conta total antes
    cursor.execute("SELECT COUNT(*) FROM bets")
    total_before = cursor.fetchone()[0]
    
    # Busca todas as apostas
    cursor.execute("""
        SELECT id, matchup_id, mapa, metodo, expected_value, odd_decimal
        FROM bets
    """)
    all_bets = [dict(row) for row in cursor.fetchall()]
    
    # Agrupa por (matchup_id, mapa, metodo_categoria)
    from collections import defaultdict
    groups = defaultdict(list)
    for bet in all_bets:
        matchup_id = bet['matchup_id']
        mapa = bet['mapa']
        metodo = bet['metodo'] or 'probabilidade_empirica'
        metodo_cat = 'ml' if metodo in ('ml', 'machinelearning') else 'empirico'
        key = (matchup_id, mapa, metodo_cat)
        groups[key].append(bet)
    
    # Identifica IDs para remover
    ids_to_keep = set()
    for (matchup_id, mapa, metodo_cat), group_bets in groups.items():
        if len(group_bets) <= max_per_map:
            ids_to_keep.update(b['id'] for b in group_bets)
            continue
        
        # Seleciona top N conforme estratégia
        if metodo_cat == 'ml':
            sorted_bets = sorted(group_bets, key=lambda b: float(b.get('expected_value') or 0), reverse=True)
        else:
            sorted_bets = sorted(group_bets, key=lambda b: float(b.get('odd_decimal') or 0), reverse=True)
        
        selected = sorted_bets[:max_per_map]
        ids_to_keep.update(b['id'] for b in selected)
    
    # Remove apostas que não estão na seleção
    ids_to_remove = [b['id'] for b in all_bets if b['id'] not in ids_to_keep]
    
    if ids_to_remove:
        # Deleta em lotes
        for i in range(0, len(ids_to_remove), 500):
            batch = ids_to_remove[i:i+500]
            placeholders = ",".join(["?"] * len(batch))
            cursor.execute(f"DELETE FROM bets WHERE id IN ({placeholders})", batch)
        conn.commit()
    
    # Conta total depois
    cursor.execute("SELECT COUNT(*) FROM bets")
    total_after = cursor.fetchone()[0]
    
    conn.close()
    
    deleted = total_before - total_after
    print(f"[FILTRO] Banco filtrado: {total_before} -> {total_after} apostas ({deleted} removidas)")
    print(f"[FILTRO] Estratégia: {max_per_map}/mapa (ML: melhor EV | Empírico: melhor odd)")
    
    return {
        "backup_path": str(backup_path) if backup_path else None,
        "total_before": total_before,
        "total_after": total_after,
        "deleted": deleted,
    }


def prune_bets_by_ev(
    min_ev: float = 0.20,
    *,
    statuses: Optional[tuple[str, ...]] = ("pending", "feita"),
    all_statuses: bool = False,
    backup: bool = True,
) -> dict:
    """
    Remove do bets.db apostas com EV abaixo do mínimo.

    Por padrão é conservador: só remove apostas ainda "ativas" (pending/feita),
    preservando histórico (won/lost/void).

    Args:
        min_ev: EV mínimo (decimal). Ex: 0.20 = 20%
        statuses: status considerados quando all_statuses=False
        all_statuses: se True, remove de todos os status
        backup: se True, cria cópia do bets.db antes de remover

    Returns:
        dict com {backup_path, deleted}
    """
    if not BETS_DB.exists():
        return {"backup_path": None, "deleted": 0}

    backup_path = None
    if backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = BETS_DB.with_name(f"{BETS_DB.stem}.bak-{ts}{BETS_DB.suffix}")
        shutil.copy2(BETS_DB, backup_path)

    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()

    if all_statuses:
        cursor.execute("DELETE FROM bets WHERE expected_value < ?", (float(min_ev),))
    else:
        st = statuses or ("pending", "feita")
        placeholders = ",".join(["?"] * len(st))
        cursor.execute(
            f"DELETE FROM bets WHERE expected_value < ? AND status IN ({placeholders})",
            (float(min_ev), *st),
        )

    deleted = cursor.rowcount or 0
    conn.commit()
    conn.close()

    return {"backup_path": str(backup_path) if backup_path else None, "deleted": int(deleted)}
