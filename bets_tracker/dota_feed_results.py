"""
Script 1 - Alimenta jogos realizados (OpenDota) em dota_results.db.
Independente: só usa OpenDota API e dota_results.db.
Na segunda execução só adiciona jogos novos (INSERT OR IGNORE por match_id).
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import DOTA_RESULTS_DB
from opendota_client import fetch_pro_matches, REQUEST_DELAY_SEC

def init_db(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS opendota_matches (
            match_id INTEGER PRIMARY KEY,
            start_time INTEGER NOT NULL,
            radiant_name TEXT NOT NULL,
            dire_name TEXT NOT NULL,
            league_name TEXT NOT NULL,
            radiant_win INTEGER NOT NULL,
            radiant_score INTEGER NOT NULL,
            dire_score INTEGER NOT NULL,
            total_kills INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    now = datetime.now(timezone.utc)
    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    year_start_ts = int(year_start.timestamp())
    now_ts = int(now.timestamp())

    conn = sqlite3.connect(DOTA_RESULTS_DB)
    init_db(conn)
    cursor = conn.cursor()

    # Otimização: buscar só partidas mais novas que a última no banco
    cursor.execute("SELECT MAX(start_time) FROM opendota_matches")
    row = cursor.fetchone()
    last_ts = int(row[0]) if row and row[0] is not None else None
    if last_ts is not None:
        print(f"[dota_feed_results] Último jogo no banco: {datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()} — buscando apenas partidas mais recentes.")

    inserted = 0
    less_than = None
    page = 0
    past_year = False
    reached_known = False  # True quando encontrarmos partida já no banco (start_time <= last_ts)

    print(f"[dota_feed_results] Ano: {year_start.year} | Agora UTC: {now.isoformat()}")
    print("[dota_feed_results] Buscando partidas OpenDota (já realizadas)...\n")

    import time as _time
    while not past_year and not reached_known:
        page += 1
        batch = fetch_pro_matches(less_than_match_id=less_than)
        if not batch:
            break
        for m in batch:
            match_id = m.get("match_id")
            start_time = m.get("start_time")
            if match_id is None or start_time is None:
                continue
            if start_time < year_start_ts:
                past_year = True
                break
            if start_time > now_ts:
                continue
            # Otimização: se já temos partidas até last_ts, não precisamos de mais páginas após esta
            if last_ts is not None and start_time <= last_ts:
                reached_known = True
            radiant_score = int(m.get("radiant_score") or 0)
            dire_score = int(m.get("dire_score") or 0)
            total_kills = radiant_score + dire_score
            try:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO opendota_matches
                    (match_id, start_time, radiant_name, dire_name, league_name, radiant_win, radiant_score, dire_score, total_kills, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        start_time,
                        (m.get("radiant_name") or "").strip(),
                        (m.get("dire_name") or "").strip(),
                        (m.get("league_name") or "").strip(),
                        1 if m.get("radiant_win") else 0,
                        radiant_score,
                        dire_score,
                        total_kills,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                if cursor.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"   [AVISO] Erro ao inserir match_id={match_id}: {e}")
        if past_year or reached_known or len(batch) < 100:
            break
        less_than = batch[-1].get("match_id")
        if less_than is None:
            break
        _time.sleep(REQUEST_DELAY_SEC)

    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM opendota_matches WHERE start_time >= ? AND start_time <= ?", (year_start_ts, now_ts))
    total_year = cursor.fetchone()[0]
    conn.close()

    print(f"   Partidas novas inseridas nesta execução: {inserted}")
    print(f"   Total no ano (já realizadas) no DB: {total_year}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
