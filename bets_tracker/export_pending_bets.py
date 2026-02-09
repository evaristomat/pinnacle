"""
Exporta apostas pendentes (pending) do SQLite para um CSV/JSONL para análise manual.

Inclui colunas de diagnóstico (match ok? por quê falhou?) usando o mesmo ResultMatcher.

Uso (PowerShell):
  python .\\export_pending_bets.py
  python .\\export_pending_bets.py --min-hours 24
  python .\\export_pending_bets.py --out pending_bets.csv
  python .\\export_pending_bets.py --format jsonl
  python .\\export_pending_bets.py --db user
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from config import BETS_DB, USER_BETS_DB, DATE_TOLERANCE_HOURS
from result_matcher import ResultMatcher


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _safe_to_timestamp(value: Any) -> Optional[pd.Timestamp]:
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=False)
    except Exception:
        return None
    return ts if pd.notna(ts) else None


def _load_pending_bets(db_path: Path) -> List[Dict[str, Any]]:
    con = _connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT *
        FROM bets
        WHERE status = 'pending'
        ORDER BY game_date ASC, id ASC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


@dataclass
class DebugInfo:
    match_ok: bool
    match_confidence: Optional[float]
    match_total_kills: Optional[int]
    match_hist_league: Optional[str]
    match_hist_t1: Optional[str]
    match_hist_t2: Optional[str]
    match_hist_date: Optional[str]
    match_hist_game: Optional[Any]
    league_norm: Optional[str]
    team1_norm: Optional[str]
    team2_norm: Optional[str]
    bet_date_parsed: Optional[str]
    bet_age_hours: Optional[float]
    candidates_league: int
    candidates_teams: int
    candidates_map: int
    candidates_date: int
    notes: str


def _debug_match(matcher: ResultMatcher, bet: Dict[str, Any]) -> DebugInfo:
    # Primeiro tenta o matcher oficial (é isso que o pipeline usa).
    res = matcher.match_game(bet)
    if res:
        mi = (res.get("match_info") or {}) if isinstance(res, dict) else {}
        return DebugInfo(
            match_ok=True,
            match_confidence=float(res.get("confidence")) if res.get("confidence") is not None else None,
            match_total_kills=int(res.get("total_kills")) if res.get("total_kills") is not None else None,
            match_hist_league=mi.get("league"),
            match_hist_t1=mi.get("t1"),
            match_hist_t2=mi.get("t2"),
            match_hist_date=str(mi.get("date")) if mi.get("date") is not None else None,
            match_hist_game=mi.get("game"),
            league_norm=None,
            team1_norm=None,
            team2_norm=None,
            bet_date_parsed=None,
            bet_age_hours=None,
            candidates_league=0,
            candidates_teams=0,
            candidates_map=0,
            candidates_date=0,
            notes="",
        )

    df = matcher.history_df
    notes: List[str] = []

    # Campos que o matcher usa hoje (mantém compatível com o DB atual)
    league_name = bet.get("league_name")
    home_team = bet.get("home_team")
    away_team = bet.get("away_team")
    bet_map = bet.get("mapa")

    league_norm = matcher.normalizer.normalize_league_name(league_name)
    team1_norm = matcher.normalizer.normalize_team_name(home_team, league_norm)
    team2_norm = matcher.normalizer.normalize_team_name(away_team, league_norm)
    bet_dt = _safe_to_timestamp(bet.get("game_date"))

    now = pd.Timestamp(datetime.now())
    age_hours = float((now - bet_dt) / pd.Timedelta(hours=1)) if bet_dt is not None else None

    if df is None or len(df) == 0:
        notes.append("history_df vazio (histórico não carregou)")
        return DebugInfo(
            match_ok=False,
            match_confidence=None,
            match_total_kills=None,
            match_hist_league=None,
            match_hist_t1=None,
            match_hist_t2=None,
            match_hist_date=None,
            match_hist_game=None,
            league_norm=league_norm,
            team1_norm=team1_norm,
            team2_norm=team2_norm,
            bet_date_parsed=str(bet_dt) if bet_dt is not None else None,
            bet_age_hours=age_hours,
            candidates_league=0,
            candidates_teams=0,
            candidates_map=0,
            candidates_date=0,
            notes="; ".join(notes),
        )

    if not league_norm:
        notes.append("normalize_league_name retornou None")
    if not team1_norm or not team2_norm:
        notes.append("normalize_team_name retornou None (home/away)")
    if bet_dt is None:
        notes.append("game_date inválida (não parseável)")

    # Liga
    league_candidates_df = df
    if league_norm and "league" in df.columns:
        league_col = df["league"].astype(str).str.strip().str.upper()
        league_candidates_df = df[league_col == league_norm.strip().upper()].copy()
    candidates_league = int(len(league_candidates_df))

    # Times
    team_candidates_df = league_candidates_df
    if league_norm and team1_norm and team2_norm and all(c in team_candidates_df.columns for c in ("t1", "t2")):
        a = team1_norm.strip().upper()
        b = team2_norm.strip().upper()
        t1 = team_candidates_df["t1"].astype(str).str.strip().str.upper()
        t2 = team_candidates_df["t2"].astype(str).str.strip().str.upper()
        team_candidates_df = team_candidates_df[((t1 == a) & (t2 == b)) | ((t1 == b) & (t2 == a))].copy()
    candidates_teams = int(len(team_candidates_df))

    # Mapa
    map_candidates_df = team_candidates_df
    history_games_unique: List[Any] = []
    if "game" in map_candidates_df.columns:
        history_games_unique = sorted(pd.unique(map_candidates_df["game"]).tolist(), key=lambda x: (str(type(x)), str(x)))

    if bet_map is not None and "game" in map_candidates_df.columns and len(map_candidates_df) > 0:
        game_num = pd.to_numeric(map_candidates_df["game"], errors="coerce")
        try:
            bet_map_num = int(bet_map)
        except Exception:
            bet_map_num = None

        map_df_num = map_candidates_df[game_num == bet_map_num].copy() if bet_map_num is not None else map_candidates_df.iloc[0:0].copy()
        map_df_str = map_candidates_df[map_candidates_df["game"].astype(str).str.strip() == str(bet_map).strip()].copy()
        map_candidates_df = map_df_num if len(map_df_num) >= len(map_df_str) else map_df_str

        if len(map_candidates_df) == 0:
            notes.append(f"filtro de mapa zerou (bet.mapa={bet_map!r}); valores no histórico: {history_games_unique[:10]}")
    candidates_map = int(len(map_candidates_df))

    # Data
    date_candidates_df = map_candidates_df
    if bet_dt is not None and "date" in date_candidates_df.columns and len(date_candidates_df) > 0:
        hist_date = pd.to_datetime(date_candidates_df["date"], errors="coerce")
        tolerance = timedelta(hours=DATE_TOLERANCE_HOURS)
        date_candidates_df = date_candidates_df[(hist_date >= bet_dt - tolerance) & (hist_date <= bet_dt + tolerance)].copy()
        if len(date_candidates_df) == 0 and candidates_map > 0:
            notes.append("filtro de data zerou dentro da tolerância (mas havia candidatos por liga/time/mapa)")
    candidates_date = int(len(date_candidates_df))

    return DebugInfo(
        match_ok=False,
        match_confidence=None,
        match_total_kills=None,
        match_hist_league=None,
        match_hist_t1=None,
        match_hist_t2=None,
        match_hist_date=None,
        match_hist_game=None,
        league_norm=league_norm,
        team1_norm=team1_norm,
        team2_norm=team2_norm,
        bet_date_parsed=str(bet_dt) if bet_dt is not None else None,
        bet_age_hours=age_hours,
        candidates_league=candidates_league,
        candidates_teams=candidates_teams,
        candidates_map=candidates_map,
        candidates_date=candidates_date,
        notes="; ".join(notes),
    )


def _iter_rows(bets: Iterable[Dict[str, Any]], matcher: ResultMatcher) -> Iterable[Dict[str, Any]]:
    for b in bets:
        dbg = _debug_match(matcher, b)
        row = dict(b)
        row.update({f"dbg_{k}": v for k, v in asdict(dbg).items()})
        yield row


def _default_out_path(fmt: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    ext = "csv" if fmt == "csv" else "jsonl"
    return Path(__file__).resolve().parent / f"pending_bets_{stamp}.{ext}"


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", choices=["bets", "user"], default="bets", help="Qual banco exportar")
    parser.add_argument("--min-hours", type=float, default=0.0, help="Só exporta bets com game_date >= X horas no passado")
    parser.add_argument("--format", choices=["csv", "jsonl"], default="csv", help="Formato de saída")
    parser.add_argument("--out", type=str, default="", help="Caminho do arquivo de saída (opcional)")
    args = parser.parse_args()

    db_path = USER_BETS_DB if args.db == "user" else BETS_DB
    if not db_path.exists():
        print(f"[ERRO] DB não encontrado: {db_path}")
        return 2

    bets = _load_pending_bets(db_path)
    if not bets:
        print("[OK] Nenhuma bet pending encontrada.")
        return 0

    # filtro por idade
    now = pd.Timestamp(datetime.now())
    filtered: List[Dict[str, Any]] = []
    for b in bets:
        dt = _safe_to_timestamp(b.get("game_date"))
        if dt is None:
            continue
        age = now - dt
        if age >= pd.Timedelta(hours=float(args.min_hours)):
            filtered.append(b)

    matcher = ResultMatcher()  # carrega histórico uma vez
    rows = list(_iter_rows(filtered, matcher))

    out_path = Path(args.out) if args.out else _default_out_path(args.format)
    if args.format == "csv":
        _write_csv(out_path, rows)
    else:
        _write_jsonl(out_path, rows)

    print(f"[OK] Exportado: {out_path}")
    print(f"[INFO] bets pending total: {len(bets)} | exportadas (min_hours={args.min_hours}): {len(filtered)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

