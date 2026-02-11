"""
Script 2 - Apostas de valor: compara odds (pinnacle_dota.db) com histórico (opendota_matches)
e salva apostas de valor em bets_dota.db. Preenche pinnacle_to_result para jogos já realizados.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from collections import defaultdict

from config import PINNACLE_DOTA_DB, DOTA_RESULTS_DB, BETS_DOTA_DB, DATE_TOLERANCE_HOURS, MAX_BETS_PER_MAP
from opendota_client import _league_match, _team_match
from bets_database import init_database, save_bet

EV_MIN = float(__import__("os").environ.get("PINNACLE_EV_MIN_STORE", "0.05"))
MIN_GAMES = 5
MAX_PER_MAP = int(__import__("os").environ.get("DOTA_MAX_BETS_PER_MAP", str(MAX_BETS_PER_MAP)))
VERBOSE = __import__("os").environ.get("DOTA_COLLECT_VERBOSE", "").lower() in ("1", "true", "yes")


def normalize_league_name(league_name: str) -> str:
    """Remove prefixo 'Dota 2 - ' se existir (consistência com API/outros sistemas)."""
    if not league_name:
        return league_name
    s = league_name.strip()
    if s.lower().startswith("dota 2 - "):
        return s[9:].strip()
    return s

def _parse_start_time(st: Optional[str]) -> Optional[int]:
    if not st:
        return None
    try:
        st = st.strip().replace("Z", "+00:00")
        if "T" in st:
            dt = datetime.fromisoformat(st)
        else:
            dt = datetime.strptime(st[:10], "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None

def ensure_pinnacle_to_result(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pinnacle_to_result (
            matchup_id INTEGER PRIMARY KEY,
            opendota_match_id INTEGER NOT NULL,
            total_kills INTEGER NOT NULL,
            radiant_win INTEGER NOT NULL,
            confidence REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()

def get_historical_total_kills(
    conn_dota: sqlite3.Connection,
    league_name: str,
    home_team: Optional[str] = None,
    away_team: Optional[str] = None,
) -> List[int]:
    """
    Retorna lista de total_kills do histórico (opendota_matches).
    Filtra por liga; se home_team/away_team forem passados, considera apenas partidas
    em que pelo menos um dos dois times participou (igual ao LoL: estatística dos times na liga).
    """
    cursor = conn_dota.cursor()
    cursor.execute("SELECT league_name, radiant_name, dire_name, total_kills FROM opendota_matches")
    rows = cursor.fetchall()
    out = []
    for row in rows:
        api_league, rad, dire, total_kills = row[0], row[1] or "", row[2] or "", row[3]
        if not _league_match(league_name, api_league or ""):
            continue
        if home_team or away_team:
            home_ok = _team_match(home_team or "", rad) or _team_match(home_team or "", dire)
            away_ok = _team_match(away_team or "", rad) or _team_match(away_team or "", dire)
            if not (home_ok or away_ok):
                continue
        out.append(total_kills)
    return out

def find_best_match(
    conn_dota: sqlite3.Connection,
    league_name: str,
    home_team: str,
    away_team: str,
    game_start_ts: int,
) -> Optional[Tuple[int, int, int, float]]:
    """Retorna (opendota_match_id, total_kills, radiant_win, confidence) ou None."""
    tolerance_sec = DATE_TOLERANCE_HOURS * 3600
    cursor = conn_dota.cursor()
    cursor.execute(
        "SELECT match_id, start_time, radiant_name, dire_name, league_name, total_kills, radiant_win FROM opendota_matches"
    )
    best = None
    best_score = 0.0
    for row in cursor.fetchall():
        match_id, start_time, rad, dire, api_league, total_kills, radiant_win = row
        if abs(start_time - game_start_ts) > tolerance_sec:
            continue
        if not _league_match(league_name, api_league or ""):
            continue
        hr = _team_match(home_team, rad) and _team_match(away_team, dire)
        hd = _team_match(home_team, dire) and _team_match(away_team, rad)
        if not (hr or hd):
            continue
        score = 0.7
        delta = abs(start_time - game_start_ts) / 3600
        if delta < 1:
            score += 0.2
        elif delta < 6:
            score += 0.1
        if score > best_score:
            best_score = score
            best = (match_id, total_kills, radiant_win, min(score, 1.0))
    return best

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not PINNACLE_DOTA_DB.exists():
        print("[dota_collect_value_bets] pinnacle_dota.db nao encontrado.")
        return 1
    if not DOTA_RESULTS_DB.exists():
        print("[dota_collect_value_bets] Rode dota_feed_results.py antes.")
        return 1

    init_database(db_path=BETS_DOTA_DB)
    conn_pinnacle = sqlite3.connect(PINNACLE_DOTA_DB)
    conn_pinnacle.row_factory = sqlite3.Row
    conn_dota = sqlite3.connect(DOTA_RESULTS_DB)
    ensure_pinnacle_to_result(conn_dota)

    now_ts = int(datetime.now(timezone.utc).timestamp())
    saved = 0
    results_written = 0

    cur_p = conn_pinnacle.cursor()
    cur_p.execute("SELECT matchup_id, league_name, home_team, away_team, start_time FROM games ORDER BY start_time ASC")
    games = cur_p.fetchall()

    print(f"[dota_collect_value_bets] {len(games)} jogos no pinnacle_dota.db\n")

    for g in games:
        matchup_id = g["matchup_id"]
        league_name = normalize_league_name(g["league_name"] or "")
        home_team = (g["home_team"] or "").strip()
        away_team = (g["away_team"] or "").strip()
        start_time_str = g["start_time"]
        game_start_ts = _parse_start_time(start_time_str)

        cur_p.execute(
            "SELECT market_type, mapa, line_value, side, odd_decimal FROM markets WHERE matchup_id = ? AND market_type = 'total_kills' ORDER BY mapa, line_value, side",
            (matchup_id,),
        )
        markets = cur_p.fetchall()
        if not markets:
            if VERBOSE:
                print(f"   [SKIP] matchup_id={matchup_id} {league_name} | sem markets total_kills")
            continue

        # Estatística: primeiro tenta com jogos dos dois times na liga (como LoL); fallback para só liga
        hist = get_historical_total_kills(conn_dota, league_name, home_team, away_team)
        if len(hist) < MIN_GAMES:
            hist = get_historical_total_kills(conn_dota, league_name)
        if len(hist) < MIN_GAMES:
            if VERBOSE:
                print(f"   [SKIP] matchup_id={matchup_id} {league_name} | {home_team} vs {away_team} | historico insuficiente (n={len(hist)})")
            continue

        mean = sum(hist) / len(hist)
        variance = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = (variance ** 0.5) if variance > 0 else 0.0
        n = len(hist)

        game_date = (start_time_str or "")[:19] if start_time_str and "T" in (start_time_str or "") else (start_time_str or "")[:10]
        if not game_date:
            continue

        # Coletar todas as apostas de valor (EV >= EV_MIN) para este jogo
        candidates = []
        for m in markets:
            line_value = m["line_value"]
            side = (m["side"] or "").upper()
            odd_decimal = float(m["odd_decimal"] or 0)
            if odd_decimal <= 0:
                continue
            implied_prob = 1.0 / odd_decimal
            if side == "OVER":
                empirical_prob = sum(1 for x in hist if x > line_value) / n
            else:
                empirical_prob = sum(1 for x in hist if x < line_value) / n
            ev = empirical_prob * odd_decimal - 1.0
            edge = empirical_prob - implied_prob
            if ev < EV_MIN:
                continue
            bet_data = {
                "matchup_id": matchup_id,
                "game_date": game_date,
                "league_name": league_name,
                "home_team": home_team,
                "away_team": away_team,
                "market_type": "total_kills",
                "mapa": m["mapa"],
                "line_value": line_value,
                "side": side,
                "odd_decimal": odd_decimal,
                "metodo": "probabilidade_empirica",
                "expected_value": ev,
                "edge": edge,
                "empirical_prob": empirical_prob,
                "implied_prob": implied_prob,
                "historical_mean": mean,
                "historical_std": std,
                "historical_games": n,
                "status": "pending",
            }
            candidates.append(bet_data)

        # Restringir a MAX_PER_MAP apostas por mapa: as de maiores odds
        if MAX_PER_MAP > 0 and candidates:
            by_map = defaultdict(list)
            for b in candidates:
                by_map[b["mapa"]].append(b)
            selected = []
            for mapa, group in by_map.items():
                sorted_bets = sorted(group, key=lambda b: float(b.get("odd_decimal", 0)), reverse=True)
                selected.extend(sorted_bets[:MAX_PER_MAP])
            candidates = selected
            if VERBOSE and len(by_map) > 0:
                total_before = sum(len(g) for g in by_map.values())
                if total_before > len(candidates):
                    print(f"   [FILTRO] {MAX_PER_MAP} apostas/mapa (maior odd): {total_before} -> {len(candidates)}")

        saved_game = 0
        for bet_data in candidates:
            bid = save_bet(bet_data, db_path=BETS_DOTA_DB)
            if bid is not None:
                saved += 1
                saved_game += 1

        if VERBOSE and (saved_game > 0 or len(markets) > 0):
            print(f"   [JOGO] {league_name} | {home_team} vs {away_team} | historico n={n} mean={mean:.1f} std={std:.1f} | apostas salvas={saved_game} / {len(markets)} markets")

        # Só preenche pinnacle_to_result para jogos já realizados (evita resultado para jogo futuro)
        if game_start_ts is not None and game_start_ts <= now_ts:
            best = find_best_match(conn_dota, league_name, home_team, away_team, game_start_ts)
            if best is not None:
                opendota_match_id, total_kills, radiant_win, confidence = best
                conn_dota.execute(
                    """
                    INSERT OR REPLACE INTO pinnacle_to_result (matchup_id, opendota_match_id, total_kills, radiant_win, confidence, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (matchup_id, opendota_match_id, total_kills, radiant_win, confidence, datetime.now(timezone.utc).isoformat()),
                )
                conn_dota.commit()
                results_written += 1

    conn_pinnacle.close()
    conn_dota.close()

    print(f"   Apostas de valor salvas: {saved}")
    print(f"   Jogos com resultado gravado (pinnacle_to_result): {results_written}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
