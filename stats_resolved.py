"""
Estatísticas das apostas resolvidas (won/lost) com EV >= 15%.

Usado pelo app Streamlit na aba "Estatísticas (EV15+)".
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

EV_MIN = 0.15


def _lucro_u(row: dict) -> float:
    s = (row.get("status") or "").lower()
    o = float(row.get("odd_decimal") or 0)
    if s == "won":
        return o - 1.0
    if s == "lost":
        return -1.0
    return 0.0


def _odds_bucket(odd: float) -> str:
    if odd <= 1.80:
        return "1.50 – 1.80"
    if odd <= 2.00:
        return "1.80 – 2.00"
    if odd <= 2.20:
        return "2.00 – 2.20"
    if odd <= 2.50:
        return "2.20 – 2.50"
    return "2.50+"


def _metodo_label(m: str | None) -> str:
    if not m:
        return "—"
    m = str(m).lower().strip()
    if "ml" in m or "machine" in m:
        return "ML"
    return "Empírico"


def _mapa_label(mapa: int | None) -> str:
    if mapa is None:
        return "Sem mapa"
    if mapa == 1:
        return "Map 1"
    if mapa == 2:
        return "Map 2"
    return f"Map {mapa}"


def fetch_resolved_ev15(db_path: Path) -> list[dict[str, Any]]:
    """Apostas resolvidas (won/lost) com expected_value >= EV_MIN."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, matchup_id, game_date, league_name, home_team, away_team,
               market_type, mapa, line_value, side, odd_decimal, metodo,
               expected_value, status, result_value
        FROM bets
        WHERE status IN ('won', 'lost') AND expected_value >= ?
        ORDER BY game_date ASC, id ASC
        """,
        (EV_MIN,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def build_df(bets: list[dict[str, Any]]) -> pd.DataFrame:
    """DataFrame com colunas auxiliares para agregações."""
    if not bets:
        return pd.DataFrame()

    records = []
    for b in bets:
        odd = float(b.get("odd_decimal") or 0)
        game_date_raw = b.get("game_date")
        game_dt = pd.to_datetime(game_date_raw, errors="coerce")
        records.append({
            "id": b.get("id"),
            "matchup_id": b.get("matchup_id"),
            "game_date": game_date_raw,
            "game_date_day": game_dt.date().isoformat() if pd.notna(game_dt) else None,
            "league_name": (b.get("league_name") or "").strip() or "—",
            "side": (b.get("side") or "").strip().upper() or "—",
            "odd_decimal": odd,
            "odds_bucket": _odds_bucket(odd),
            "metodo": _metodo_label(b.get("metodo")),
            "mapa_label": _mapa_label(b.get("mapa")),
            "mapa_raw": b.get("mapa"),
            "status": (b.get("status") or "").lower(),
            "lucro_u": _lucro_u(b),
            "expected_value": float(b.get("expected_value") or 0),
        })
    return pd.DataFrame(records)


def _avg_odd_wins(grp: pd.DataFrame) -> float | None:
    w = grp[grp["status"] == "won"]
    if len(w) == 0:
        return None
    return float(w["odd_decimal"].mean())


def agg_stats(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Agrega N, W, L, WR%, Lucro(u), ROI%, AvgOdd(W)."""
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()

    g = df.groupby(group_col, dropna=False)
    n = g.size().rename("N")
    wins = g["status"].apply(lambda s: (s == "won").sum()).rename("W")
    losses = g["status"].apply(lambda s: (s == "lost").sum()).rename("L")
    lucro = g["lucro_u"].sum().rename("Lucro(u)")
    odd_w = g.apply(_avg_odd_wins, include_groups=False).rename("AvgOdd(W)")

    out = pd.DataFrame({"N": n, "W": wins, "L": losses, "Lucro(u)": lucro, "AvgOdd(W)": odd_w})
    out["WR%"] = (out["W"] / out["N"] * 100).round(1)
    out["ROI%"] = (out["Lucro(u)"] / out["N"] * 100).round(2)
    out = out.sort_values("N", ascending=False)
    return out.reset_index()


def agg_stats_multi(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Agrega N, W, L, WR%, Lucro(u), ROI%, AvgOdd(W) por múltiplas colunas (ex: league_name + side)."""
    if df.empty or not group_cols or any(c not in df.columns for c in group_cols):
        return pd.DataFrame()

    g = df.groupby(group_cols, dropna=False)
    n = g.size().rename("N")
    wins = g["status"].apply(lambda s: (s == "won").sum()).rename("W")
    losses = g["status"].apply(lambda s: (s == "lost").sum()).rename("L")
    lucro = g["lucro_u"].sum().rename("Lucro(u)")
    odd_w = g.apply(_avg_odd_wins, include_groups=False).rename("AvgOdd(W)")

    out = pd.DataFrame({"N": n, "W": wins, "L": losses, "Lucro(u)": lucro, "AvgOdd(W)": odd_w})
    out["WR%"] = (out["W"] / out["N"] * 100).round(1)
    out["ROI%"] = (out["Lucro(u)"] / out["N"] * 100).round(2)
    out = out.sort_values(group_cols + ["N"], ascending=[True] * len(group_cols) + [False])
    return out.reset_index()


def summary_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Métricas gerais (N, W, L, WR%, Lucro, ROI%, AvgOdd W, AvgOdd L)."""
    if df.empty:
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "lucro": 0.0, "roi": 0.0, "avg_odd_w": None, "avg_odd_l": None}
    n = len(df)
    w = int((df["status"] == "won").sum())
    l = int((df["status"] == "lost").sum())
    lucro = float(df["lucro_u"].sum())
    wr = (w / n * 100) if n else 0.0
    roi = (lucro / n * 100) if n else 0.0
    aw = df.loc[df["status"] == "won", "odd_decimal"]
    al = df.loc[df["status"] == "lost", "odd_decimal"]
    avg_odd_w = float(aw.mean()) if len(aw) else None
    avg_odd_l = float(al.mean()) if len(al) else None
    return {
        "n": n,
        "w": w,
        "l": l,
        "wr": round(wr, 1),
        "lucro": round(lucro, 2),
        "roi": round(roi, 2),
        "avg_odd_w": round(avg_odd_w, 2) if avg_odd_w is not None else None,
        "avg_odd_l": round(avg_odd_l, 2) if avg_odd_l is not None else None,
    }


def odds_bucket_order() -> list[str]:
    """Ordem das faixas de odds para exibição."""
    return ["1.50 – 1.80", "1.80 – 2.00", "2.00 – 2.20", "2.20 – 2.50", "2.50+"]


def build_pl_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative P/L by day for charting.

    Returns DataFrame with columns: date (datetime), daily (float), cumulative (float).
    """
    if df.empty or "game_date_day" not in df.columns:
        return pd.DataFrame(columns=["date", "daily", "cumulative"])
    daily = (
        df.groupby("game_date_day")["lucro_u"]
        .sum()
        .reset_index()
        .rename(columns={"game_date_day": "date", "lucro_u": "daily"})
        .sort_values("date")
    )
    daily["cumulative"] = daily["daily"].cumsum()
    daily["date"] = pd.to_datetime(daily["date"])
    return daily
