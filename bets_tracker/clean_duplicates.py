"""
Remove apostas duplicadas do bets.db.
Duplicata = mesmo matchup_id, market_type, line_value, side, metodo.
Mantém uma por grupo (prioriza won/lost, depois menor id).
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import BETS_DB


def main():
    if not BETS_DB.exists():
        print(f"[ERRO] Banco nao encontrado: {BETS_DB}")
        return 1

    conn = sqlite3.connect(BETS_DB)
    cursor = conn.cursor()

    # Conta duplicatas (grupos com mais de 1)
    cursor.execute("""
        SELECT matchup_id, market_type, line_value, side, metodo, COUNT(*) as n
        FROM bets
        GROUP BY matchup_id, market_type, line_value, side, metodo
        HAVING COUNT(*) > 1
    """)
    dup_groups = cursor.fetchall()
    total_dups = sum(g[5] - 1 for g in dup_groups)  # excesso por grupo

    if not dup_groups:
        print("[OK] Nenhuma duplicata encontrada.")
        conn.close()
        return 0

    print(f"[INFO] {len(dup_groups)} grupos duplicados, {total_dups} apostas a remover.")

    # IDs a manter: por grupo, manter 1. Priorizar won/lost (resultado conhecido), senao min(id).
    keep_ids = set()
    for (matchup_id, market_type, line_value, side, metodo, _) in dup_groups:
        cursor.execute("""
            SELECT id, status FROM bets
            WHERE matchup_id = ? AND market_type = ? AND line_value IS ? AND side = ? AND metodo = ?
            ORDER BY CASE status WHEN 'won' THEN 0 WHEN 'lost' THEN 1 ELSE 2 END, id ASC
            LIMIT 1
        """, (matchup_id, market_type, line_value, side, metodo))
        row = cursor.fetchone()
        if row:
            keep_ids.add(row[0])

    # Também manter todos os ids que NÃO estão em grupos duplicados (qualquer um serve)
    cursor.execute("SELECT id FROM bets")
    all_ids = {r[0] for r in cursor.fetchall()}
    cursor.execute("""
        SELECT id FROM bets
        WHERE (matchup_id, market_type, line_value, side, metodo) IN (
            SELECT matchup_id, market_type, line_value, side, metodo
            FROM bets
            GROUP BY matchup_id, market_type, line_value, side, metodo
            HAVING COUNT(*) = 1
        )
    """)
    keep_ids |= {r[0] for r in cursor.fetchall()}

    delete_ids = sorted(all_ids - keep_ids)
    if not delete_ids:
        print("[INFO] Nenhuma aposta a deletar apos calcular keeps.")
        conn.close()
        return 0

    placeholders = ",".join("?" * len(delete_ids))
    cursor.execute(f"DELETE FROM bets WHERE id IN ({placeholders})", delete_ids)
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    print(f"[OK] {deleted} duplicatas removidas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
