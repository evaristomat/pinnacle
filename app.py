"""
App Streamlit – Pinnacle: Dashboard, Apostas, Draft+ML, Minhas Apostas, Performance.

Redesign completo: st.tabs(), sidebar com KPIs, gráfico P/L, bets agrupadas por jogo, DRY.
"""
from __future__ import annotations

import os
import sys
import re
import json
import subprocess
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

ROOT = Path(__file__).parent
EV_MIN_APP = float(os.getenv("PINNACLE_EV_MIN_APP", "0.15"))
for _path in [str(ROOT / "odds_analysis"), str(ROOT / "bets_tracker"), str(ROOT)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import streamlit as st
import sqlite3
import pandas as pd

# Draft ao vivo (LoL Esports)
import lolesports_live_draft as ls_draft

# Bets DB (bets_tracker)
from bets_database import (
    get_bets_by_date,
    mark_bet_placed,
    unmark_bet_placed,
    get_bet_stats,
    get_placed_bets,
    get_resolved_bets,
    get_bet_by_id,
    save_bet,
    init_database,
)

# Update results (bets_tracker)
from update_results import ResultsUpdater

# Config (bets_tracker)
from config import PINNACLE_DB, BETS_DB, USER_BETS_DB, HISTORY_DB, IS_CLOUD

# Estatísticas resolvidas EV15+
from stats_resolved import (
    fetch_resolved_ev15,
    build_df,
    agg_stats,
    agg_stats_multi,
    summary_stats,
    odds_bucket_order,
    build_pl_curve,
)

st.set_page_config(
    page_title="Pinnacle Apostas & Draft",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════
# Data helpers
# ═══════════════════════════════════════════════════════════════


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow() -> str:
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


@st.cache_data(ttl=180)
def _ls_get_schedule_events():
    return ls_draft.fetch_schedule(hl="en-US")


@st.cache_data(ttl=60)
def _ls_get_live_events():
    return ls_draft.fetch_live(hl="en-US")


@st.cache_data(ttl=120)
def _ls_get_event_details(match_id: str):
    return ls_draft.fetch_event_details(match_id, hl="en-US")


@st.cache_data(ttl=15)
def _ls_get_window(game_id: str):
    return ls_draft.fetch_window(game_id)


def _games_today_tomorrow():
    """Jogos do Pinnacle com start_time hoje ou amanhã."""
    if not PINNACLE_DB.exists():
        return [], []
    conn = sqlite3.connect(PINNACLE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT matchup_id, league_name, home_team, away_team, start_time, status
        FROM games
        WHERE SUBSTR(REPLACE(start_time, 'T', ' '), 1, 10) >= ?
          AND SUBSTR(REPLACE(start_time, 'T', ' '), 1, 10) <= ?
        ORDER BY start_time ASC
    """, (_today(), _tomorrow()))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    today = [g for g in rows if g["start_time"][:10] == _today()]
    tomorrow = [g for g in rows if g["start_time"][:10] == _tomorrow()]
    return today, tomorrow


def _champions_from_history():
    """Lista de campeões únicos em lol_history (compositions)."""
    if not HISTORY_DB.exists():
        return []
    conn = sqlite3.connect(HISTORY_DB)
    cur = conn.cursor()
    cur.execute("SELECT top, jung, mid, adc, sup FROM compositions")
    champs = set()
    for row in cur.fetchall():
        for c in row:
            if c and str(c).strip():
                champs.add(str(c).strip())
    conn.close()
    return sorted(champs)


def _leagues_from_history():
    """Ligas únicas em lol_history."""
    if not HISTORY_DB.exists():
        return []
    conn = sqlite3.connect(HISTORY_DB)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT league FROM matchups ORDER BY league")
    out = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return out


def _teams_by_league(league: str):
    """Times por liga (matchups t1/t2)."""
    if not HISTORY_DB.exists() or not league:
        return []
    conn = sqlite3.connect(HISTORY_DB)
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT t1 AS t FROM matchups WHERE league = ? "
        "UNION SELECT t2 FROM matchups WHERE league = ? ORDER BY t",
        (league, league),
    )
    out = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return out


def _apply_method_filter(bets: list, method: str) -> list:
    """Filtra lista de bets por método (sidebar)."""
    if method == "Todos":
        return bets
    if method == "ML":
        return [b for b in bets if (b.get("metodo") or "").lower() == "ml"]
    return [b for b in bets if (b.get("metodo") or "").lower() != "ml"]


def _apply_method_filter_df(df: pd.DataFrame, method: str) -> pd.DataFrame:
    """Filtra DataFrame por método (sidebar)."""
    if method == "Todos" or df.empty or "metodo" not in df.columns:
        return df
    if method == "ML":
        return df[df["metodo"] == "ML"].copy()
    return df[df["metodo"] == "Empírico"].copy()


# ═══════════════════════════════════════════════════════════════
# OddsAnalyzer (lazy load)
# ═══════════════════════════════════════════════════════════════


@st.cache_resource
def _get_analyzer():
    import io
    import contextlib
    import importlib.util

    f = io.StringIO()
    _oa = ROOT / "odds_analysis"

    _cfg_spec = importlib.util.spec_from_file_location("odds_config", _oa / "config.py")
    _cfg_mod = importlib.util.module_from_spec(_cfg_spec)
    _cfg_spec.loader.exec_module(_cfg_mod)
    _prev_config = sys.modules.get("config")
    sys.modules["config"] = _cfg_mod

    _nz_spec = importlib.util.spec_from_file_location("oa_normalizer", _oa / "normalizer.py")
    _nz_mod = importlib.util.module_from_spec(_nz_spec)
    _nz_spec.loader.exec_module(_nz_mod)
    _prev_normalizer = sys.modules.get("normalizer")
    sys.modules["normalizer"] = _nz_mod

    try:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            import odds_analyzer as _oa_mod
            a = _oa_mod.OddsAnalyzer()
        return a
    finally:
        if _prev_config is not None:
            sys.modules["config"] = _prev_config
        else:
            sys.modules.pop("config", None)
        if _prev_normalizer is not None:
            sys.modules["normalizer"] = _prev_normalizer
        else:
            sys.modules.pop("normalizer", None)


def _run_empirical(matchup_id: int):
    """Análise empírica para um matchup."""
    try:
        analyzer = _get_analyzer()
        return analyzer.analyze_game(matchup_id, force_method="probabilidade_empirica")
    except Exception as e:
        st.error(f"Erro na análise empírica: {e}")
        return None


def _run_ml_with_draft(draft_data: dict, line_value: float):
    """Predição ML para draft + linha."""
    try:
        analyzer = _get_analyzer()
        return analyzer._predict_ml(draft_data, line_value)
    except Exception as e:
        import traceback
        print(f"[ERRO ML] {e}\n{traceback.format_exc()}")
        return None


# ═══════════════════════════════════════════════════════════════
# Draft helpers
# ═══════════════════════════════════════════════════════════════


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


LOL_CHAMPION_ID_MAP = {
    "JarvanIV": "Jarvan IV",
    "XinZhao": "Xin Zhao",
    "LeeSin": "Lee Sin",
    "TwistedFate": "Twisted Fate",
    "MissFortune": "Miss Fortune",
    "DrMundo": "Dr. Mundo",
    "TahmKench": "Tahm Kench",
    "AurelionSol": "Aurelion Sol",
    "MonkeyKing": "Wukong",
    "KSante": "K'Sante",
    "RenataGlasc": "Renata Glasc",
    "Renata": "Renata Glasc",
    "NunuWillump": "Nunu & Willump",
    "BelVeth": "Bel'Veth",
    "RekSai": "Rek'Sai",
    "KhaZix": "Kha'Zix",
    "VelKoz": "Vel'Koz",
    "ChoGath": "Cho'Gath",
    "KaiSa": "Kai'Sa",
    "KogMaw": "Kog'Maw",
    "MasterYi": "Master Yi",
}


def _match_champ_to_options(champ_id: str, options: list[str]) -> str:
    """Converte championId da API para string que existe no selectbox."""
    if not champ_id:
        return ""
    raw = str(champ_id).strip()
    candidates = [raw]
    mapped = LOL_CHAMPION_ID_MAP.get(raw)
    if mapped:
        candidates.append(mapped)
    if raw and raw.isascii():
        camel = re.sub(r"(?<!^)([A-Z])", r" \1", raw).strip()
        if camel and camel != raw:
            candidates.append(camel)

    for c in candidates:
        if c in options:
            return c

    opt_map = {_norm_key(o): o for o in options if o}
    for c in candidates:
        nk = _norm_key(c)
        if nk in opt_map:
            return opt_map[nk]

    raw_lower = raw.lower()
    for opt in options:
        if not opt:
            continue
        if opt.lower().startswith(raw_lower) or raw_lower.startswith(_norm_key(opt)):
            return opt
    for opt in options:
        if not opt:
            continue
        if raw_lower in _norm_key(opt) or _norm_key(opt).startswith(raw_lower):
            return opt

    return ""


def _draft_ml_build_bet_rows(
    results: list,
    value_bets: list,
    matchup_id_sel,
    start_time_sel,
    league_sel: str,
    team1_sel: str,
    team2_sel: str,
    draft_data: dict,
    mapa_sel=None,
) -> list[dict]:
    """Converte results + value_bets em lista de bet_data (só EV >= EV_MIN_APP e com vb_match)."""
    def _norm(s):
        return (s or "").strip().lower()

    if not results or not value_bets or matchup_id_sel is None:
        return []
    if mapa_sel is not None:
        value_bets = [
            vb for vb in value_bets
            if vb.get("market", {}).get("mapa") == mapa_sel
        ]
        if not value_bets:
            return []
    game_date = start_time_sel[:10] if isinstance(start_time_sel, str) and start_time_sel else start_time_sel
    draft_data_serializable = (
        {k: v for k, v in (draft_data or {}).items()
         if isinstance(v, (str, int, float, bool, type(None)))}
        if isinstance(draft_data, dict) else {}
    )
    mapa_val = mapa_sel if mapa_sel is not None else None
    rows = []
    for r in results:
        ev_val = r.get("ev")
        if ev_val is None or float(ev_val) < EV_MIN_APP:
            continue
        r_line = float(r["line"]) if r.get("line") is not None else None
        r_side_norm = _norm(r.get("side"))
        vb_match = next(
            (vb for vb in value_bets
             if r_line is not None
             and abs(float(vb.get("line_value") or 0) - r_line) < 0.01
             and _norm(vb.get("side")) == r_side_norm),
            None,
        )
        if not vb_match:
            continue
        rows.append({
            "matchup_id": matchup_id_sel,
            "game_date": game_date,
            "league_name": league_sel,
            "home_team": team1_sel,
            "away_team": team2_sel,
            "market_type": "total_kills",
            "mapa": mapa_val,
            "line_value": float(r["line"]) if r.get("line") is not None else None,
            "side": (r.get("side") or "").strip().lower() or "over",
            "odd_decimal": float(r["odd"]) if r.get("odd") and r["odd"] > 0 else 1.0,
            "metodo": "ml",
            "expected_value": float(r["ev"]) if r.get("ev") is not None else 0.0,
            "edge": float(r["ev"]) if r.get("ev") is not None else 0.0,
            "empirical_prob": vb_match.get("empirical_prob"),
            "implied_prob": (1.0 / float(r["odd"])) if r.get("odd") and r["odd"] > 0 else None,
            "historical_mean": vb_match.get("historical_mean"),
            "historical_std": vb_match.get("historical_std"),
            "historical_games": vb_match.get("historical_games"),
            "status": "pending",
            "metadata": {
                "ml_prediction": r.get("ml_pred"),
                "ml_prob_over": r.get("ml_prob_over"),
                "ml_prob_under": r.get("ml_prob_under"),
                "converges": r.get("converges"),
                "draft_data": draft_data_serializable,
            },
        })
    return rows


# ═══════════════════════════════════════════════════════════════
# Core data functions
# ═══════════════════════════════════════════════════════════════


def _calculated_prob(b: dict) -> float | None:
    """Probabilidade calculada do evento para a aposta."""
    p = b.get("empirical_prob")
    if isinstance(p, (int, float)) and p > 0:
        return float(p)
    md = b.get("metadata")
    if md:
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except Exception:
                md = None
    if isinstance(md, dict):
        side = (b.get("side") or "").lower().strip()
        if side == "over":
            p = md.get("ml_prob_over")
        elif side == "under":
            p = md.get("ml_prob_under")
        else:
            p = md.get("calculated_prob") or md.get("probability") or md.get("prob")
        if isinstance(p, (int, float)) and p > 0:
            return float(p)
    return None


def _build_bets_df(bets: list) -> pd.DataFrame:
    """Retorna DataFrame com dados das apostas, ordenados por game_date e mapa."""
    rows = []
    for b in bets:
        ev = (b.get("expected_value") or 0) * 100
        metodo = "ML" if (b.get("metodo") or "").lower() == "ml" else "Empírico"
        jogo = f"{b['home_team']} vs {b['away_team']}"
        game_date = b.get("game_date") or ""
        dt_str = game_date[:16].replace("T", " ") if game_date else ""
        mapa_val = b.get("mapa")
        mapa_display = f"Map {mapa_val}" if mapa_val is not None else ""
        prob = _calculated_prob(b)
        fair_odds = (1.0 / prob) if (prob is not None and prob > 0) else None
        rows.append({
            "id": b["id"],
            "matchup_id": b.get("matchup_id"),
            "game_date": game_date,
            "Data/Hora": dt_str,
            "Liga": b.get("league_name", ""),
            "Jogo": jogo,
            "Mapa": mapa_display,
            "Mercado": f"{b.get('side', '')} {b.get('line_value')}",
            "Linha": b.get("line_value"),
            "Odd": round(float(b.get("odd_decimal") or 0), 2),
            "fair_odds": round(float(fair_odds), 2) if fair_odds is not None else None,
            "EV%": round(ev, 1),
            "Método": metodo,
            "Status": (b.get("status") or "pending"),
            "mapa_sort": mapa_val if mapa_val is not None else 999,
            "market_type": b.get("market_type") or "total_kills",
            "side": (b.get("side") or "").strip().lower(),
            "metodo": (b.get("metodo") or "probabilidade_empirica").strip().lower(),
            "mapa_raw": mapa_val if mapa_val is not None else -1,
        })
    rows.sort(key=lambda x: (x.get("game_date", "") or "", x.get("mapa_sort", 999)))
    df = pd.DataFrame(rows)
    if "mapa_sort" in df.columns:
        df = df.drop(columns=["mapa_sort"])
    return df


def _get_placed_bets_keys(db_path=None) -> set:
    """Set de (matchup_id, market_type, mapa, line_value, side, metodo) já feitas em user_bets.db."""
    db_path = db_path or USER_BETS_DB
    if not db_path.exists():
        return set()
    try:
        placed = get_placed_bets(db_path=db_path)
        keys = set()
        for b in placed:
            mapa = b.get("mapa") if b.get("mapa") is not None else -1
            lv = b.get("line_value")
            line_val = float(lv) if lv is not None else None
            keys.add((
                b.get("matchup_id"),
                (b.get("market_type") or "total_kills").strip().lower(),
                mapa,
                line_val,
                (b.get("side") or "").strip().lower(),
                (b.get("metodo") or "probabilidade_empirica").strip().lower(),
            ))
        return keys
    except Exception:
        return set()


def _add_model_bet_to_user_db(model_bet_id: int) -> bool:
    """Copia aposta do banco do MODELO (bets.db) para o banco do USUÁRIO (user_bets.db)."""
    src = get_bet_by_id(int(model_bet_id), db_path=BETS_DB)
    if not src:
        return False
    md = src.get("metadata")
    if isinstance(md, str) and md.strip():
        try:
            md = json.loads(md)
        except Exception:
            md = {"raw_metadata": md}
    if not isinstance(md, dict):
        md = {}
    md.setdefault("source_model_bet_id", int(model_bet_id))
    bet_data = {
        "matchup_id": src["matchup_id"],
        "game_date": src["game_date"],
        "league_name": src["league_name"],
        "home_team": src["home_team"],
        "away_team": src["away_team"],
        "market_type": src["market_type"],
        "mapa": src.get("mapa"),
        "line_value": src.get("line_value"),
        "side": src["side"],
        "odd_decimal": src["odd_decimal"],
        "metodo": src.get("metodo", "probabilidade_empirica"),
        "expected_value": src.get("expected_value", 0.0),
        "edge": src.get("edge", 0.0),
        "empirical_prob": src.get("empirical_prob"),
        "implied_prob": src.get("implied_prob"),
        "historical_mean": src.get("historical_mean"),
        "historical_std": src.get("historical_std"),
        "historical_games": src.get("historical_games"),
        "status": "feita",
        "metadata": md,
    }
    new_id = save_bet(bet_data, db_path=USER_BETS_DB)
    if new_id:
        return True
    conn = sqlite3.connect(USER_BETS_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """SELECT id, status FROM bets
        WHERE matchup_id = ? AND market_type = ?
          AND COALESCE(mapa, -1) = COALESCE(?, -1)
          AND line_value = ? AND side = ? AND metodo = ?
        ORDER BY id DESC LIMIT 1""",
        (bet_data["matchup_id"], bet_data["market_type"], bet_data.get("mapa"),
         bet_data.get("line_value"), bet_data["side"], bet_data.get("metodo", "probabilidade_empirica")),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    if str(row["status"]).lower().strip() == "pending":
        return mark_bet_placed(int(row["id"]), db_path=USER_BETS_DB)
    return True


# ═══════════════════════════════════════════════════════════════
# Shared UI components (DRY)
# ═══════════════════════════════════════════════════════════════


def render_kpi_row(metrics: list[dict]):
    """Render row of KPI st.metric() cards.

    metrics: list of {"label": str, "value": str|int, "delta": str|None}
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            st.metric(m["label"], m["value"], delta=m.get("delta"))


def render_pl_curve(df_curve: pd.DataFrame):
    """Render P/L cumulative line chart with Altair."""
    if df_curve.empty:
        st.caption("Sem dados para gráfico P/L.")
        return
    import altair as alt

    line = alt.Chart(df_curve).mark_line(
        strokeWidth=2.5, color="#28a745",
    ).encode(
        x=alt.X("date:T", title="Data"),
        y=alt.Y("cumulative:Q", title="Lucro acumulado (u)"),
        tooltip=[
            alt.Tooltip("date:T", title="Data", format="%d/%m/%Y"),
            alt.Tooltip("cumulative:Q", title="Acumulado", format="+.2f"),
            alt.Tooltip("daily:Q", title="Dia", format="+.2f"),
        ],
    )
    points = alt.Chart(df_curve).mark_circle(size=30, color="#28a745").encode(
        x="date:T", y="cumulative:Q",
    )
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color="gray", strokeDash=[4, 4], opacity=0.5,
    ).encode(y="y:Q")
    st.altair_chart(
        (line + points + zero).properties(height=350).interactive(),
        width="stretch",
    )


def render_map_filter(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Render map filter selectbox, returns filtered DataFrame."""
    if "Mapa" not in df.columns:
        return df
    mapas = sorted(
        [m for m in df["Mapa"].unique() if pd.notna(m) and str(m).strip()], key=str,
    )
    if not mapas:
        return df
    sel = st.selectbox("Filtrar por mapa", ["Todos"] + mapas, key=f"filtro_mapa_{key_prefix}")
    if sel != "Todos":
        return df[df["Mapa"] == sel].copy()
    return df


def _row_placed_key(row) -> tuple | None:
    """Build placed-check key from a DataFrame row."""
    matchup_id = row.get("matchup_id")
    market_type = (row.get("market_type") or "total_kills").strip().lower() if pd.notna(row.get("market_type")) else "total_kills"
    mapa_raw = row.get("mapa_raw")
    if pd.isna(mapa_raw) or mapa_raw is None:
        mapa_raw = -1
    line_val = row.get("Linha")
    line_val = float(line_val) if line_val is not None and pd.notna(line_val) else None
    side = (row.get("side") or "").strip().lower() if pd.notna(row.get("side")) else ""
    metodo = (row.get("metodo") or "probabilidade_empirica").strip().lower() if pd.notna(row.get("metodo")) else "probabilidade_empirica"
    return (matchup_id, market_type, mapa_raw, line_val, side, metodo)


def _render_action_btn(row, idx, *, source, key_prefix, already_placed_keys, show_mark, show_remove):
    """Render mark/remove button for a single bet row."""
    status_val = str(row.get("Status", "")).lower().strip()
    is_placed = False
    if source == "model" and already_placed_keys:
        rk = _row_placed_key(row)
        is_placed = rk is not None and rk in already_placed_keys

    if is_placed:
        st.caption("✅")
    elif status_val == "pending" and show_mark:
        if st.button("✓", key=f"{key_prefix}mk_{idx}", help="Marcar como feita",
                      width="stretch", type="secondary"):
            ok = (_add_model_bet_to_user_db(int(row["id"])) if source == "model"
                  else mark_bet_placed(int(row["id"]), db_path=USER_BETS_DB))
            if ok:
                st.rerun()
    elif status_val == "feita" and show_remove:
        if st.button("✗", key=f"{key_prefix}rm_{idx}", help="Remover",
                      width="stretch", type="secondary"):
            if unmark_bet_placed(int(row["id"]), db_path=USER_BETS_DB):
                st.rerun()
    else:
        st.text("")


def render_bets_grouped(df: pd.DataFrame, *, key_prefix: str, source: str,
                        already_placed_keys: set | None = None,
                        show_mark: bool = True, show_remove: bool = False):
    """Render bets grouped by match using bordered containers."""
    if df.empty:
        st.info("Nenhuma aposta encontrada.")
        return
    already_placed_keys = already_placed_keys or set()

    if "matchup_id" in df.columns:
        groups = df.groupby("matchup_id", sort=False)
    else:
        groups = df.groupby("Jogo", sort=False)

    for _gkey, gdf in groups:
        first = gdf.iloc[0]
        liga = first.get("Liga", "")
        jogo = first.get("Jogo", "")
        dt_str = str(first.get("Data/Hora", ""))[:16]

        with st.container(border=True):
            st.markdown(f"**{liga}** — {jogo} &nbsp; `{dt_str}`")
            # Column headers
            hdr = st.columns([0.7, 1.6, 0.6, 0.6, 0.8, 0.6, 0.5])
            hdr[0].caption("Mapa")
            hdr[1].caption("Mercado")
            hdr[2].caption("Odd")
            hdr[3].caption("Fair")
            hdr[4].caption("EV%")
            hdr[5].caption("Método")
            hdr[6].caption("")

            for idx, row in gdf.iterrows():
                cols = st.columns([0.7, 1.6, 0.6, 0.6, 0.8, 0.6, 0.5])
                mapa = str(row.get("Mapa", "")) if pd.notna(row.get("Mapa")) else ""
                with cols[0]:
                    if mapa == "Map 1":
                        st.markdown("<span style='color:#007bff;font-weight:bold'>Map 1</span>",
                                    unsafe_allow_html=True)
                    elif mapa == "Map 2":
                        st.markdown("<span style='color:#ff6b35;font-weight:bold'>Map 2</span>",
                                    unsafe_allow_html=True)
                    else:
                        st.text(mapa)
                with cols[1]:
                    st.text(str(row.get("Mercado", "")))
                with cols[2]:
                    odd = row.get("Odd")
                    st.text(f"{float(odd):.2f}" if pd.notna(odd) else "")
                with cols[3]:
                    fair = row.get("fair_odds")
                    st.text(f"{float(fair):.2f}" if pd.notna(fair) else "")
                with cols[4]:
                    ev = row.get("EV%", 0)
                    if pd.notna(ev) and ev > 0:
                        st.markdown(
                            f"<span style='color:#28a745;font-weight:bold'>+{ev:.1f}%</span>",
                            unsafe_allow_html=True,
                        )
                    elif pd.notna(ev):
                        st.text(f"{ev:.1f}%")
                    else:
                        st.text("")
                with cols[5]:
                    st.text(str(row.get("Método", "")))
                with cols[6]:
                    _render_action_btn(
                        row, idx, source=source, key_prefix=key_prefix,
                        already_placed_keys=already_placed_keys,
                        show_mark=show_mark, show_remove=show_remove,
                    )


def render_bets_flat(df: pd.DataFrame, *, key_prefix: str, source: str,
                     already_placed_keys: set | None = None,
                     show_mark: bool = True, show_remove: bool = False):
    """Render bets as a flat table with action buttons (used for Draft+ML and compact views)."""
    if df.empty:
        return
    already_placed_keys = already_placed_keys or set()

    widths = [0.7, 1.6, 0.6, 0.6, 0.8, 0.6, 0.5]
    hdr = st.columns(widths)
    for h, col in zip(["Mapa", "Mercado", "Odd", "Fair", "EV%", "Método", ""], hdr):
        col.markdown(f"**{h}**") if h else None

    for idx, row in df.iterrows():
        cols = st.columns(widths)
        mapa = str(row.get("Mapa", "")) if pd.notna(row.get("Mapa")) else ""
        with cols[0]:
            if mapa == "Map 1":
                st.markdown("<span style='color:#007bff;font-weight:bold'>Map 1</span>",
                            unsafe_allow_html=True)
            elif mapa == "Map 2":
                st.markdown("<span style='color:#ff6b35;font-weight:bold'>Map 2</span>",
                            unsafe_allow_html=True)
            else:
                st.text(mapa)
        with cols[1]:
            st.text(str(row.get("Mercado", "")))
        with cols[2]:
            odd = row.get("Odd")
            st.text(f"{float(odd):.2f}" if pd.notna(odd) else "")
        with cols[3]:
            fair = row.get("fair_odds")
            st.text(f"{float(fair):.2f}" if pd.notna(fair) else "")
        with cols[4]:
            ev = row.get("EV%", 0)
            if pd.notna(ev) and ev > 0:
                st.markdown(
                    f"<span style='color:#28a745;font-weight:bold'>+{ev:.1f}%</span>",
                    unsafe_allow_html=True,
                )
            elif pd.notna(ev):
                st.text(f"{ev:.1f}%")
            else:
                st.text("")
        with cols[5]:
            st.text(str(row.get("Método", "")))
        with cols[6]:
            _render_action_btn(
                row, idx, source=source, key_prefix=key_prefix,
                already_placed_keys=already_placed_keys,
                show_mark=show_mark, show_remove=show_remove,
            )


def _render_draft_ml_bets_table(bet_rows: list[dict], key_prefix: str = "draft_ml_"):
    """Tabela de apostas Draft+ML com botão 'Marcar como feita'."""
    if not bet_rows:
        return
    try:
        init_database(db_path=USER_BETS_DB)
    except Exception:
        pass
    already_placed = _get_placed_bets_keys(db_path=USER_BETS_DB)

    def row_key(b):
        mapa_raw = b.get("mapa") if b.get("mapa") is not None else -1
        return (
            b.get("matchup_id"),
            (b.get("market_type") or "total_kills").strip().lower(),
            mapa_raw,
            b.get("line_value"),
            (b.get("side") or "").strip().lower(),
            "ml",
        )

    st.session_state["draft_ml_bet_rows"] = list(bet_rows)

    widths = [0.7, 1.6, 0.6, 0.6, 0.8, 0.6, 0.5]
    hdr = st.columns(widths)
    for h, col in zip(["Mapa", "Mercado", "Odd", "Fair", "EV%", "Método", ""], hdr):
        col.markdown(f"**{h}**") if h else None

    for i, b in enumerate(bet_rows):
        ev = (b.get("expected_value") or 0) * 100
        prob = b.get("empirical_prob")
        fair_odds = (1.0 / prob) if (prob is not None and prob > 0) else None
        rk = row_key(b)
        is_placed = rk in already_placed

        cols = st.columns(widths)
        with cols[0]:
            mapa_disp = b.get("mapa")
            if mapa_disp == 1:
                st.markdown("<span style='color:#007bff;font-weight:bold'>Map 1</span>",
                            unsafe_allow_html=True)
            elif mapa_disp == 2:
                st.markdown("<span style='color:#ff6b35;font-weight:bold'>Map 2</span>",
                            unsafe_allow_html=True)
            else:
                st.text(f"Map {mapa_disp}" if mapa_disp is not None else "")
        with cols[1]:
            st.text(f"{b.get('side', '')} {b.get('line_value')}")
        with cols[2]:
            st.text(f"{float(b.get('odd_decimal') or 0):.2f}")
        with cols[3]:
            st.text(f"{fair_odds:.2f}" if fair_odds else "")
        with cols[4]:
            if ev > 0:
                st.markdown(
                    f"<span style='color:#28a745;font-weight:bold'>+{ev:.1f}%</span>",
                    unsafe_allow_html=True,
                )
            else:
                st.text(f"{ev:.1f}%")
        with cols[5]:
            st.text("ML")
        with cols[6]:
            if is_placed:
                st.caption("✅")
            else:
                if st.button("✓", key=f"{key_prefix}mark_{i}", help="Marcar como feita",
                              width="stretch", type="secondary"):
                    bet_data = st.session_state.get("draft_ml_bet_rows")
                    if bet_data and i < len(bet_data):
                        bd = bet_data[i]
                        bid = save_bet(bd, db_path=USER_BETS_DB)
                        if bid:
                            if mark_bet_placed(bid, db_path=USER_BETS_DB):
                                st.rerun()
                        else:
                            conn = sqlite3.connect(USER_BETS_DB)
                            conn.row_factory = sqlite3.Row
                            cur = conn.cursor()
                            cur.execute(
                                "SELECT id FROM bets WHERE matchup_id=? AND market_type=? "
                                "AND COALESCE(mapa,-1)=COALESCE(?,-1) AND line_value=? "
                                "AND side=? AND metodo=? ORDER BY id DESC LIMIT 1",
                                (bd["matchup_id"], bd["market_type"], bd.get("mapa"),
                                 bd["line_value"], bd["side"], bd["metodo"]),
                            )
                            ex = cur.fetchone()
                            conn.close()
                            if ex and mark_bet_placed(ex["id"], db_path=USER_BETS_DB):
                                st.rerun()
                    else:
                        st.warning("Dados da aposta não encontrados.")
    return None


# ═══════════════════════════════════════════════════════════════
# Init
# ═══════════════════════════════════════════════════════════════

try:
    init_database(db_path=USER_BETS_DB)
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🎮 Pinnacle")
    st.caption(f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    st.divider()

    # Quick KPIs
    if BETS_DB.exists():
        _sb_stats = get_bet_stats(db_path=BETS_DB)
        _sb_roi = _sb_stats.get("roi") or {}
        _sb_resolved = int(_sb_roi.get("total_resolved", 0))
        _sb_lucro = float(_sb_roi.get("lucro", 0))
        _sb_roi_pct = float(_sb_roi.get("return_pct", 0))
        _sb_pending = int(_sb_stats.get("by_status", {}).get("pending", 0)) + int(
            _sb_stats.get("by_status", {}).get("feita", 0)
        )
        c1, c2 = st.columns(2)
        with c1:
            st.metric("ROI", f"{_sb_roi_pct:+.1f}%")
        with c2:
            st.metric("Lucro", f"{_sb_lucro:+.1f}u")
        c3, c4 = st.columns(2)
        with c3:
            st.metric("Resolvidas", _sb_resolved)
        with c4:
            st.metric("Pendentes", _sb_pending)
    else:
        st.info("Banco bets.db não encontrado.")

    st.divider()

    # Global filters
    method_filter = st.selectbox("Método", ["Todos", "Empírico", "ML"], key="sidebar_method")
    source_filter = st.radio(
        "Fonte (performance)",
        ["bets.db (modelo)", "user_bets.db (usuário)"],
        key="sidebar_source",
    )

    st.divider()

    if IS_CLOUD:
        st.caption("☁️ Modo Cloud (read-only)")
    else:
        # Pipeline button (apenas local)
        if st.button("🔄 Atualizar Pipeline", width="stretch", type="primary"):
            with st.spinner("Rodando run_all.py..."):
                try:
                    _pipe_result = subprocess.run(
                        [sys.executable, str(ROOT / "run_all.py")],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                        timeout=300,
                    )
                    if _pipe_result.returncode == 0:
                        st.success("Pipeline concluído!")
                    else:
                        st.error(f"Pipeline falhou (exit {_pipe_result.returncode})")
                        with st.expander("Output"):
                            if _pipe_result.stdout:
                                st.code(_pipe_result.stdout[-2000:])
                            if _pipe_result.stderr:
                                st.code(_pipe_result.stderr[-2000:])
                except subprocess.TimeoutExpired:
                    st.error("Pipeline excedeu timeout de 5 min.")
                except Exception as _pipe_err:
                    st.error(f"Erro ao rodar pipeline: {_pipe_err}")
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# Main tabs
# ═══════════════════════════════════════════════════════════════

tab_dash, tab_apostas, tab_draft, tab_minhas, tab_perf = st.tabs([
    "📊 Dashboard",
    "📋 Apostas",
    "🃏 Draft + ML",
    "✅ Minhas Apostas",
    "📈 Performance",
])

# ───────────────────────────────────────────────────────────────
# TAB: Dashboard
# ───────────────────────────────────────────────────────────────

with tab_dash:
    _dash_db = BETS_DB if "modelo" in source_filter else USER_BETS_DB
    if not _dash_db.exists():
        st.warning(f"Banco `{_dash_db.name}` não encontrado.")
    else:
        _d_bets = fetch_resolved_ev15(_dash_db)
        _d_df = build_df(_d_bets)
        _d_df = _apply_method_filter_df(_d_df, method_filter)
        _d_stats = summary_stats(_d_df)

        # ── KPIs principais ──
        col_roi, col_lucro, col_wr, col_wl = st.columns(4)
        with col_roi:
            st.metric("ROI", f"{_d_stats['roi']:+.1f}%")
        with col_lucro:
            st.metric("Lucro", f"{_d_stats['lucro']:+.2f} u")
        with col_wr:
            st.metric("Winrate", f"{_d_stats['wr']:.1f}%")
        with col_wl:
            st.metric("Apostas", f"{_d_stats['n']}", delta=f"{_d_stats['w']}W / {_d_stats['l']}L", delta_color="off")

        # ── Breakdown por método (tabela limpa) ──
        if not _d_df.empty and method_filter == "Todos":
            _df_ml = _d_df[_d_df["metodo"] == "ML"]
            _df_emp = _d_df[_d_df["metodo"] == "Empírico"]
            _s_ml = summary_stats(_df_ml)
            _s_emp = summary_stats(_df_emp)
            _method_comp = pd.DataFrame([
                {
                    "Método": "Empírico",
                    "N": _s_emp["n"],
                    "W/L": f"{_s_emp['w']}/{_s_emp['l']}",
                    "WR%": _s_emp["wr"],
                    "Lucro (u)": _s_emp["lucro"],
                    "ROI%": _s_emp["roi"],
                },
                {
                    "Método": "ML",
                    "N": _s_ml["n"],
                    "W/L": f"{_s_ml['w']}/{_s_ml['l']}",
                    "WR%": _s_ml["wr"],
                    "Lucro (u)": _s_ml["lucro"],
                    "ROI%": _s_ml["roi"],
                },
            ])
            st.dataframe(
                _method_comp,
                width="stretch",
                hide_index=True,
                column_config={
                    "N": st.column_config.NumberColumn(format="%d"),
                    "WR%": st.column_config.NumberColumn(format="%.1f"),
                    "Lucro (u)": st.column_config.NumberColumn(format="%+.2f"),
                    "ROI%": st.column_config.NumberColumn(format="%+.1f"),
                },
            )

        st.divider()

        # P/L curve
        st.subheader("Curva P/L acumulada")
        _d_pl = build_pl_curve(_d_df)
        render_pl_curve(_d_pl)

        st.divider()

        # Period profits
        if not _d_df.empty and "game_date_day" in _d_df.columns:
            _d_today = datetime.now().date()
            _d_yesterday = _d_today - timedelta(days=1)
            _d_days = pd.to_datetime(_d_df["game_date_day"], errors="coerce")

            def _d_lucro_mask(mask):
                sub = _d_df[mask]
                return float(pd.to_numeric(sub["lucro_u"], errors="coerce").fillna(0).sum()) if not sub.empty else 0.0

            render_kpi_row([
                {"label": "Hoje", "value": f"{_d_lucro_mask(_d_days.dt.date == _d_today):+.2f}u"},
                {"label": "Ontem", "value": f"{_d_lucro_mask(_d_days.dt.date == _d_yesterday):+.2f}u"},
                {"label": "7 dias", "value": f"{_d_lucro_mask(_d_days.dt.date >= (_d_today - timedelta(days=6))):+.2f}u"},
                {"label": "30 dias", "value": f"{_d_lucro_mask(_d_days.dt.date >= (_d_today - timedelta(days=29))):+.2f}u"},
            ])
            st.divider()

        # Last 10 resolved
        if not _d_df.empty:
            st.subheader("Ultimas apostas resolvidas")
            _d_last = _d_df.sort_values("game_date", ascending=False).head(10).copy()
            # Build Mercado column (side + line)
            _d_last["Mercado"] = _d_last.apply(
                lambda r: f"{r['side']} {r['line_value']}" if pd.notna(r.get("line_value")) else r["side"],
                axis=1,
            )
            # Build Jogo column
            _d_last["Jogo"] = _d_last.apply(
                lambda r: f"{r['home_team']} vs {r['away_team']}" if r.get("home_team") else "",
                axis=1,
            )
            _display_cols = ["game_date_day", "league_name", "Jogo", "Mercado", "odd_decimal", "status", "lucro_u", "metodo"]
            _display_cols = [c for c in _display_cols if c in _d_last.columns]
            st.dataframe(
                _d_last[_display_cols].rename(
                    columns={
                        "game_date_day": "Data",
                        "league_name": "Liga",
                        "odd_decimal": "Odd",
                        "status": "Resultado",
                        "lucro_u": "P/L (u)",
                        "metodo": "Metodo",
                    }
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    "Odd": st.column_config.NumberColumn("Odd", format="%.2f"),
                    "P/L (u)": st.column_config.NumberColumn("P/L (u)", format="%+.2f"),
                },
            )


# ───────────────────────────────────────────────────────────────
# TAB: Apostas (merged Hoje + Futuros)
# ───────────────────────────────────────────────────────────────

with tab_apostas:
    if not BETS_DB.exists():
        st.warning("Banco `bets.db` não encontrado. Rode o pipeline primeiro.")
    else:
        # Load all upcoming bets
        _a_all = get_bets_by_date(_today(), "2099-12-31", db_path=BETS_DB)
        _a_all = [b for b in _a_all if float(b.get("expected_value") or 0) >= EV_MIN_APP]
        _a_all = _apply_method_filter(_a_all, method_filter)

        # Filters row
        fc1, fc2 = st.columns([1, 1])
        with fc1:
            _a_period = st.selectbox(
                "Período",
                ["Hoje", "Amanhã", "Todos futuros"],
                key="apostas_period",
            )
        with fc2:
            pass  # map filter applied after building df

        # Filter by period
        if _a_period == "Hoje":
            _a_bets = [b for b in _a_all if (b.get("game_date") or "")[:10] == _today()]
        elif _a_period == "Amanhã":
            _a_bets = [b for b in _a_all if (b.get("game_date") or "")[:10] == _tomorrow()]
        else:
            _a_bets = _a_all

        _a_df = _build_bets_df(_a_bets)

        if _a_df.empty:
            st.info(f"Nenhuma aposta encontrada ({_a_period}).")
        else:
            # Map filter
            with fc2:
                _a_df = render_map_filter(_a_df, "apostas")

            # Quick stats
            n_total = len(_a_df)
            n_map1 = len(_a_df[_a_df["Mapa"] == "Map 1"]) if "Mapa" in _a_df.columns else 0
            n_map2 = len(_a_df[_a_df["Mapa"] == "Map 2"]) if "Mapa" in _a_df.columns else 0
            render_kpi_row([
                {"label": f"Apostas ({_a_period})", "value": n_total},
                {"label": "Map 1", "value": n_map1},
                {"label": "Map 2", "value": n_map2},
            ])

            st.divider()

            # Grouped bets
            render_bets_grouped(
                _a_df,
                key_prefix="apostas_",
                source="model",
                already_placed_keys=_get_placed_bets_keys(USER_BETS_DB),
                show_mark=True,
            )

            # Summary
            _a_stats = get_bet_stats(db_path=BETS_DB)
            st.divider()
            st.caption(
                f"Total no banco: {_a_stats['total']} apostas | "
                f"Empírico: {_a_stats.get('by_metodo', {}).get('probabilidade_empirica', 0)} | "
                f"ML: {_a_stats.get('by_metodo', {}).get('ml', 0)}"
            )


# ───────────────────────────────────────────────────────────────
# TAB: Draft + ML
# ───────────────────────────────────────────────────────────────

with tab_draft:
    st.caption(
        "Selecione um jogo, preencha os campeões e rode o modelo. "
        "Convergência empírica + ML = aposta boa."
    )

    # Model info
    try:
        _az = _get_analyzer()
        _ml_ok = getattr(_az, "ml_available", False)
        _z_cal = getattr(_az, "ml_z_calibration", None) or {}
        if _ml_ok:
            _sk = _z_cal.get("sigmoid_k", "N/A")
            _as = _z_cal.get("adjust_strength", "N/A")
            try:
                _cfg_s = importlib.util.spec_from_file_location(
                    "oa_cfg_ml", ROOT / "odds_analysis" / "config.py"
                )
                _cfg_m = importlib.util.module_from_spec(_cfg_s)
                _cfg_s.loader.exec_module(_cfg_m)
                _mlt = getattr(_cfg_m, "ML_CONFIDENCE_THRESHOLD", 0.65)
            except Exception:
                _mlt = 0.65
            st.info(
                f"**Modelo ML 2026** — Split temporal · "
                f"Threshold: **{_mlt:.0%}** · "
                f"Z-score calibrado (k={_sk}, s={_as})"
            )
        else:
            st.warning("Modelo ML não disponível.")
    except Exception:
        pass

    games_today, games_tomorrow = _games_today_tomorrow()
    games_for_picker = (games_today or []) + (games_tomorrow or [])
    champs = _champions_from_history()
    empty = [""] + (champs or ["Nenhum campeão"])

    # ── Container 1: Game selection ──
    with st.container(border=True):
        st.markdown("**📅 Seleção do Jogo**")

        mode = st.radio("Modo", ["Jogo do dia", "Manual"], horizontal=True, key="draft_mode")

        league_sel = None
        team1_sel = None
        team2_sel = None
        matchup_id_sel = None
        start_time_sel = None

        if mode == "Jogo do dia":
            if not games_for_picker:
                st.info("Nenhum jogo hoje/amanhã no Pinnacle. Use modo Manual.")
            else:
                opts = [
                    f"{g['league_name']} — {g['home_team']} vs {g['away_team']} ({g['start_time'][:16]})"
                    for g in games_for_picker
                ]
                idx = st.selectbox(
                    "Jogo", range(len(opts)),
                    format_func=lambda i: opts[i],
                    key="draft_ml_jogo_dia",
                )
                if idx is not None and 0 <= idx < len(games_for_picker):
                    g = games_for_picker[idx]
                    league_sel = g["league_name"]
                    team1_sel = g["home_team"]
                    team2_sel = g["away_team"]
                    matchup_id_sel = g["matchup_id"]
                    start_time_sel = g["start_time"]
                    st.success(f"**{league_sel}** — {team1_sel} vs {team2_sel}")
        else:
            leagues = _leagues_from_history()
            league_sel = st.selectbox("Liga", [""] + (leagues or ["—"]), key="draft_manual_league")
            teams = _teams_by_league(league_sel) if league_sel else []
            team1_sel = st.selectbox("Time 1", [""] + (teams or ["—"]), key="draft_manual_t1")
            team2_sel = st.selectbox("Time 2", [""] + (teams or ["—"]), key="draft_manual_t2")

        # LoL Esports schedule (collapsible)
        with st.expander("📡 Próximos jogos (LoL Esports)", expanded=False):
            try:
                schedule_events = _ls_get_schedule_events()
                live_events = _ls_get_live_events()
                live_match_ids = set()
                for ev in (live_events or []):
                    if ev.get("type") == "match":
                        mid = ev.get("match") and ev.get("match", {}).get("id")
                        if mid:
                            live_match_ids.add(str(mid))
                now_utc = datetime.now(timezone.utc)
                ls_rows = []
                for ev in (schedule_events or [])[:80]:
                    if ev.get("type") != "match":
                        continue
                    match = ev.get("match") or {}
                    teams_ls = match.get("teams") or []
                    if len(teams_ls) < 2:
                        continue
                    mid = str(match.get("id", ""))
                    if not mid or mid == "N/A":
                        continue
                    start_iso = ev.get("startTime") or ""
                    try:
                        dt_utc = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                        if dt_utc.tzinfo is None:
                            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
                        if dt_utc < now_utc and mid not in live_match_ids:
                            continue
                        dt_local = dt_utc.astimezone(tz=None)
                        start_display = dt_local.strftime("%d/%m %H:%M")
                    except Exception:
                        start_display = start_iso[:16] if start_iso else "—"
                    league_ls = (ev.get("league") or {}).get("name", "") or "—"
                    t1_ls = (teams_ls[0].get("name") or teams_ls[0].get("code") or "").strip() or "—"
                    t2_ls = (teams_ls[1].get("name") or teams_ls[1].get("code") or "").strip() or "—"
                    state = "🔴 Ao vivo" if mid in live_match_ids else "⏳"
                    ls_rows.append({"Liga": league_ls, "Jogo": f"{t1_ls} vs {t2_ls}",
                                    "Horário": start_display, "Status": state})
                if ls_rows:
                    st.dataframe(pd.DataFrame(ls_rows), width="stretch", hide_index=True)
                else:
                    st.info("Nenhum jogo encontrado.")
            except Exception as e:
                st.warning(f"Erro ao carregar LoL Esports: {e}")

    # ── Container 2: Draft ──
    with st.container(border=True):
        st.markdown("**🃏 Draft**")

        # Live draft toggle
        ls_enabled = st.checkbox(
            "📡 Buscar draft ao vivo (LoL Esports)",
            value=False,
            key="ls_enable_live_draft",
        )

        if ls_enabled and league_sel and team1_sel and team2_sel:
            map_choice = st.selectbox("Mapa ao vivo", [1, 2, 3, 4, 5], index=0, key="ls_map_choice")
            col_a, col_b = st.columns(2)
            with col_a:
                do_fetch = st.button("🔄 Buscar draft", type="secondary", width="stretch")
            with col_b:
                do_fill = st.button("✅ Preencher campeões", type="primary", width="stretch")

            if do_fetch or do_fill:
                try:
                    events = []
                    try:
                        events.extend(_ls_get_live_events())
                    except Exception:
                        pass
                    try:
                        events.extend(_ls_get_schedule_events())
                    except Exception:
                        pass
                    cand = ls_draft.find_best_match_id(
                        events, league_name=league_sel, team1=team1_sel,
                        team2=team2_sel, start_time_iso=start_time_sel,
                    )
                    if not cand:
                        st.warning("Partida não encontrada no LoL Esports.")
                    else:
                        st.success(f"Match: id={cand.match_id} (score {cand.score:.2f})")
                        details = _ls_get_event_details(cand.match_id)
                        game_ids, sides = ls_draft.extract_game_ids_by_map(details)
                        game_id = game_ids.get(int(map_choice))
                        if not game_id:
                            st.info(f"Sem gameId para Map {map_choice}.")
                        else:
                            window = _ls_get_window(game_id)
                            draft = ls_draft.extract_draft_from_window(window)
                            team_names_by_id = ls_draft.extract_match_team_names(details)
                            team1_is_blue: Optional[bool] = None
                            side_map = sides.get(int(map_choice)) or {}
                            blue_tid = side_map.get("blue")
                            red_tid = side_map.get("red")
                            blue_name = team_names_by_id.get(str(blue_tid), "") if blue_tid else ""
                            red_name = team_names_by_id.get(str(red_tid), "") if red_tid else ""
                            if blue_name and _norm_key(blue_name) == _norm_key(team1_sel):
                                team1_is_blue = True
                            elif red_name and _norm_key(red_name) == _norm_key(team1_sel):
                                team1_is_blue = False
                            if team1_is_blue is None:
                                st.warning("Não consegui mapear BLUE/RED automaticamente.")
                                team1_side = st.radio(
                                    "Time 1 é:", ["BLUE side", "RED side"],
                                    horizontal=True, key="ls_team1_side_choice",
                                )
                                team1_is_blue = team1_side == "BLUE side"
                            else:
                                st.caption(f"Time 1: {'BLUE' if team1_is_blue else 'RED'} side")
                            t1_draft = draft.get("blue" if team1_is_blue else "red", {})
                            t2_draft = draft.get("red" if team1_is_blue else "blue", {})

                            df_preview = pd.DataFrame([
                                {"Role": r, "Time 1": t1_draft.get(r.lower(), ""), "Time 2": t2_draft.get(r.lower(), "")}
                                for r in ["TOP", "JUNG", "MID", "ADC", "SUP"]
                            ])
                            st.dataframe(df_preview, width="stretch", hide_index=True)

                            if do_fill:
                                opts = empty
                                for role in ["top", "jung", "mid", "adc", "sup"]:
                                    st.session_state[f"{role}_t1"] = _match_champ_to_options(t1_draft.get(role, ""), opts)
                                    st.session_state[f"{role}_t2"] = _match_champ_to_options(t2_draft.get(role, ""), opts)
                                st.success("Campeões preenchidos!")
                                st.rerun()
                except Exception as e:
                    st.warning(f"Falha ao consultar draft ao vivo: {e}")

        # Champion selectboxes
        st.markdown("**Campeões**")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Time 1")
            top_t1 = st.selectbox("Top T1", empty, key="top_t1")
            jung_t1 = st.selectbox("Jungle T1", empty, key="jung_t1")
            mid_t1 = st.selectbox("Mid T1", empty, key="mid_t1")
            adc_t1 = st.selectbox("ADC T1", empty, key="adc_t1")
            sup_t1 = st.selectbox("Sup T1", empty, key="sup_t1")
        with c2:
            st.caption("Time 2")
            top_t2 = st.selectbox("Top T2", empty, key="top_t2")
            jung_t2 = st.selectbox("Jungle T2", empty, key="jung_t2")
            mid_t2 = st.selectbox("Mid T2", empty, key="mid_t2")
            adc_t2 = st.selectbox("ADC T2", empty, key="adc_t2")
            sup_t2 = st.selectbox("Sup T2", empty, key="sup_t2")

        # Map selector for bet association
        mapa_sel = None
        if matchup_id_sel is not None:
            mapa_sel = st.selectbox(
                "Mapa das apostas",
                [1, 2],
                format_func=lambda x: f"Map {x}",
                key="draft_ml_mapa_sel",
                help="Associe ao mapa do draft preenchido.",
            )

    # ── Container 3: Results ──
    with st.container(border=True):
        st.markdown("**🔬 Resultados**")

        run_ml = st.button("▶ Rodar Modelo (empírico + ML)", type="primary", width="stretch")
        results = []
        value_bets = []
        draft_data = {}

        if run_ml:
            if not league_sel or not team1_sel or not team2_sel:
                st.warning("Selecione liga e times.")
            elif not all([top_t1, jung_t1, mid_t1, adc_t1, sup_t1, top_t2, jung_t2, mid_t2, adc_t2, sup_t2]):
                st.warning("Preencha todos os 10 campeões.")
            else:
                # Normalize league
                try:
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location(
                        "oa_normalizer", ROOT / "odds_analysis" / "normalizer.py"
                    )
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    _nz = _mod.get_normalizer()
                    league_norm = _nz.normalize_league_name(league_sel) or league_sel
                except Exception:
                    league_norm = league_sel

                def normalize_champ_name(champ):
                    if not champ:
                        return ""
                    return " ".join(str(champ).strip().split())

                draft_data = {
                    "league": league_norm,
                    "top_t1": normalize_champ_name(top_t1),
                    "jung_t1": normalize_champ_name(jung_t1),
                    "mid_t1": normalize_champ_name(mid_t1),
                    "adc_t1": normalize_champ_name(adc_t1),
                    "sup_t1": normalize_champ_name(sup_t1),
                    "top_t2": normalize_champ_name(top_t2),
                    "jung_t2": normalize_champ_name(jung_t2),
                    "mid_t2": normalize_champ_name(mid_t2),
                    "adc_t2": normalize_champ_name(adc_t2),
                    "sup_t2": normalize_champ_name(sup_t2),
                }

                if st.checkbox("🔍 Mostrar dados enviados", key="debug_ml_data"):
                    st.json(draft_data)

                # ── Empirical analysis ──
                value_bets = []
                if matchup_id_sel is not None:
                    with st.spinner("Análise empírica..."):
                        emp = _run_empirical(matchup_id_sel)
                    if emp and not emp.get("error"):
                        markets = emp.get("markets") or []
                        for m in markets:
                            if m.get("error"):
                                continue
                            ad = m.get("analysis") or {}
                            if not ad.get("value") or ad.get("empirical_prob") is None:
                                continue
                            ev = ad.get("expected_value", 0)
                            edge = ad.get("edge", 0)
                            value_bets.append({
                                "market": m["market"],
                                "side": m["market"]["side"],
                                "line_value": m["market"].get("line_value"),
                                "odd_decimal": m["market"]["odd_decimal"],
                                "expected_value": ev,
                                "edge": edge,
                                "empirical_prob": ad.get("empirical_prob"),
                                "implied_prob": ad.get("implied_probability"),
                                "historical_mean": ad.get("historical_mean"),
                                "historical_std": ad.get("historical_std"),
                                "historical_games": ad.get("historical_games"),
                            })
                    elif emp and emp.get("error"):
                        st.warning(f"Empírico: {emp['error']}")
                else:
                    st.info("Modo manual: sem matchup. Apenas predição ML.")

                value_bets_ev = [
                    vb for vb in value_bets
                    if vb.get("expected_value") is not None and float(vb.get("expected_value") or 0) >= EV_MIN_APP
                ]

                # ── ML predictions ──
                lines_to_check = [vb["line_value"] for vb in value_bets_ev]

                def _round_to_step(x: float, step: float = 0.5) -> float:
                    return round(float(x) / step) * step

                if not lines_to_check and league_norm:
                    try:
                        analyzer = _get_analyzer()
                        ls = (analyzer.ml_league_stats or {}).get(league_norm, {})
                        mean_val = ls.get("mean")
                        if mean_val is not None:
                            lines_to_check = [_round_to_step(float(mean_val), 0.5)]
                    except Exception:
                        lines_to_check = [25.5]

                ml_by_line = {}
                seen = set()
                for line_val in lines_to_check:
                    if line_val is None:
                        continue
                    key = float(line_val)
                    if key in seen:
                        continue
                    seen.add(key)
                    ml_res = _run_ml_with_draft(draft_data, float(line_val))
                    if ml_res is None:
                        st.caption(f"⚠ ML: confiança < threshold para linha {line_val} (ignorado)")
                    ml_pred = (ml_res.get("prediction") or "").upper() if ml_res else ""
                    ml_by_line[float(line_val)] = {
                        "ml_pred": ml_pred,
                        "ml_prob_over": ml_res.get("probability_over") if ml_res else None,
                        "ml_prob_under": ml_res.get("probability_under") if ml_res else None,
                    }

                # ── Build convergence results ──
                for vb in value_bets_ev:
                    line_val = vb.get("line_value")
                    if line_val is None:
                        continue
                    ml_info = ml_by_line.get(float(line_val), {})
                    empirical_side = (vb.get("side") or "").upper()
                    ml_pred = (ml_info.get("ml_pred") or "").upper()
                    converges = bool(ml_pred) and (ml_pred == empirical_side)
                    results.append({
                        "line": line_val,
                        "side": vb.get("side"),
                        "ml_pred": ml_pred,
                        "ml_prob_over": ml_info.get("ml_prob_over"),
                        "ml_prob_under": ml_info.get("ml_prob_under"),
                        "converges": converges,
                        "odd": vb.get("odd_decimal"),
                        "ev": vb.get("expected_value"),
                        "emp_prob": vb.get("empirical_prob"),
                        "implied_prob": vb.get("implied_prob"),
                    })

                # ── Display results ──
                if value_bets_ev:
                    st.markdown(f"**Empírico (EV ≥ {EV_MIN_APP*100:.0f}%)**")
                    df_emp_ev = pd.DataFrame([{
                        "Side": str(vb.get("side") or "").upper(),
                        "Linha": vb.get("line_value"),
                        "Odd": vb.get("odd_decimal"),
                        "Prob.": vb.get("empirical_prob"),
                        "EV%": float(vb.get("expected_value") or 0) * 100,
                    } for vb in value_bets_ev])
                    st.dataframe(df_emp_ev.sort_values("EV%", ascending=False),
                                 width="stretch", hide_index=True,
                                 column_config={
                                     "Linha": st.column_config.NumberColumn(format="%.1f"),
                                     "Odd": st.column_config.NumberColumn(format="%.2f"),
                                     "Prob.": st.column_config.NumberColumn(format="%.3f"),
                                     "EV%": st.column_config.NumberColumn(format="%.1f"),
                                 })

                if ml_by_line:
                    st.markdown("**ML por linha**")
                    df_ml = pd.DataFrame([{
                        "Linha": line,
                        "ML pred": info.get("ml_pred") or "—",
                        "P(OVER)": info.get("ml_prob_over"),
                        "P(UNDER)": info.get("ml_prob_under"),
                        "Status": "✅ Confiante" if info.get("ml_pred") else "⚠ Abaixo do threshold",
                    } for line, info in ml_by_line.items()])
                    st.dataframe(df_ml.sort_values("Linha"), width="stretch", hide_index=True,
                                 column_config={
                                     "P(OVER)": st.column_config.NumberColumn(format="%.3f"),
                                     "P(UNDER)": st.column_config.NumberColumn(format="%.3f"),
                                 })

                if results:
                    eligible = [r for r in results if r.get("ev") is not None and float(r.get("ev") or 0) >= EV_MIN_APP]
                    converged = [r for r in eligible if r.get("converges")]
                    if eligible:
                        st.markdown(f"**Convergência (EV ≥ {EV_MIN_APP*100:.0f}%)**")
                        render_kpi_row([
                            {"label": "Total EV+", "value": len(eligible)},
                            {"label": "Convergiu", "value": len(converged)},
                            {"label": "Taxa", "value": f"{len(converged)/len(eligible)*100:.0f}%"},
                        ])
                        if converged:
                            df_conv = pd.DataFrame([{
                                "Side": str(r.get("side") or "").upper(),
                                "Linha": r.get("line"),
                                "Odd": r.get("odd"),
                                "EV%": (r.get("ev") * 100) if r.get("ev") else None,
                                "ML": r.get("ml_pred"),
                                "P(O)": r.get("ml_prob_over"),
                                "P(U)": r.get("ml_prob_under"),
                            } for r in converged])
                            st.dataframe(
                                df_conv.sort_values("EV%", ascending=False),
                                width="stretch", hide_index=True,
                                column_config={
                                    "Linha": st.column_config.NumberColumn(format="%.1f"),
                                    "Odd": st.column_config.NumberColumn(format="%.2f"),
                                    "EV%": st.column_config.NumberColumn(format="%.1f"),
                                    "P(O)": st.column_config.NumberColumn(format="%.3f"),
                                    "P(U)": st.column_config.NumberColumn(format="%.3f"),
                                },
                            )
                        with st.expander("Divergiram (debug)", expanded=False):
                            diverged = [r for r in eligible if not r.get("converges")]
                            if not diverged:
                                st.caption("Nenhuma.")
                            else:
                                df_div = pd.DataFrame([{
                                    "Side": str(r.get("side") or "").upper(),
                                    "Linha": r.get("line"),
                                    "Odd": r.get("odd"),
                                    "EV%": (r.get("ev") * 100) if r.get("ev") else None,
                                    "ML": r.get("ml_pred"),
                                } for r in diverged])
                                st.dataframe(df_div, width="stretch", hide_index=True)

        # ── Good bets table (always shown if available) ──
        if results and value_bets and matchup_id_sel is not None:
            good_bet_rows = _draft_ml_build_bet_rows(
                results, value_bets, matchup_id_sel, start_time_sel,
                league_sel, team1_sel, team2_sel, draft_data,
                mapa_sel=mapa_sel,
            )
            if good_bet_rows:
                st.session_state["draft_ml_bet_rows"] = list(good_bet_rows)
                st.subheader(f"Apostas boas (EV ≥ {EV_MIN_APP*100:.0f}%)")
                _ = _render_draft_ml_bets_table(good_bet_rows)
            else:
                st.session_state["draft_ml_bet_rows"] = []
                st.info(f"Nenhuma aposta com EV ≥ {EV_MIN_APP*100:.0f}% e dados empíricos.")
        elif st.session_state.get("draft_ml_bet_rows"):
            good_bet_rows = st.session_state["draft_ml_bet_rows"]
            st.subheader(f"Apostas boas (EV ≥ {EV_MIN_APP*100:.0f}%)")
            _ = _render_draft_ml_bets_table(good_bet_rows)


# ───────────────────────────────────────────────────────────────
# TAB: Minhas Apostas
# ───────────────────────────────────────────────────────────────

with tab_minhas:
    if not USER_BETS_DB.exists():
        st.info("Nenhuma aposta marcada ainda. Use o botão ✓ nas abas Apostas ou Draft+ML.")
    else:
        sub_aguard, sub_resolv = st.tabs(["⏳ Aguardando", "✅ Resolvidas"])

        # ── Sub-tab: Aguardando ──
        with sub_aguard:
            # Update results button (prominent)
            if st.button("🔄 Atualizar Resultados", type="primary", width="content"):
                with st.spinner("Atualizando resultados..."):
                    try:
                        updater = ResultsUpdater(db_path=USER_BETS_DB)
                        upd_stats = updater.update_all_results(dry_run=False)
                        st.success("Atualização concluída!")
                        st.json({
                            "Pendentes": upd_stats["pending_bets"],
                            "Encontrados": upd_stats["matched"],
                            "Atualizados": upd_stats["updated"],
                            "Não encontrados": upd_stats["not_found"],
                            "Erros": upd_stats["errors"],
                        })
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")

            feitas = get_placed_bets(db_path=USER_BETS_DB)
            feitas = [b for b in feitas if float(b.get("expected_value") or 0) >= EV_MIN_APP]
            df_feitas = _build_bets_df(feitas)

            if df_feitas.empty:
                st.info("Nenhuma aposta aguardando resultado.")
            else:
                df_feitas = render_map_filter(df_feitas, "minhas_aguard")
                st.caption(f"{len(df_feitas)} apostas aguardando resultado")
                render_bets_grouped(
                    df_feitas,
                    key_prefix="minhas_aguard_",
                    source="user",
                    show_mark=False,
                    show_remove=True,
                )

        # ── Sub-tab: Resolvidas ──
        with sub_resolv:
            # KPIs
            user_stats = get_bet_stats(db_path=USER_BETS_DB)
            roi_data = user_stats.get("roi") or {}
            if roi_data.get("total_resolved", 0) > 0:
                render_kpi_row([
                    {"label": "Resolvidas", "value": int(roi_data.get("total_resolved", 0))},
                    {"label": "Vitórias", "value": int(roi_data.get("wins", 0))},
                    {"label": "Derrotas", "value": int(roi_data.get("losses", 0))},
                    {"label": "Winrate", "value": f"{float(roi_data.get('win_rate', 0)):.1f}%"},
                    {"label": "Lucro (u)", "value": f"{float(roi_data.get('lucro', 0)):+.2f}"},
                    {"label": "ROI", "value": f"{float(roi_data.get('return_pct', 0)):+.1f}%"},
                ])
                st.divider()
            else:
                st.caption("Sem apostas resolvidas (won/lost).")

            resolved = get_resolved_bets(db_path=USER_BETS_DB)
            resolved = [b for b in resolved if float(b.get("expected_value") or 0) >= EV_MIN_APP]
            df_resolved = _build_bets_df(resolved)

            if not df_resolved.empty:
                df_resolved = render_map_filter(df_resolved, "minhas_resolv")
                render_bets_grouped(
                    df_resolved,
                    key_prefix="minhas_resolv_",
                    source="user",
                    show_mark=False,
                    show_remove=False,
                )


# ───────────────────────────────────────────────────────────────
# TAB: Performance
# ───────────────────────────────────────────────────────────────

with tab_perf:
    _p_db = BETS_DB if "modelo" in source_filter else USER_BETS_DB
    if not _p_db.exists():
        st.warning(f"Banco `{_p_db.name}` não encontrado.")
    else:
        _p_bets = fetch_resolved_ev15(_p_db)
        _p_df = build_df(_p_bets)
        _p_df = _apply_method_filter_df(_p_df, method_filter)

        if _p_df.empty:
            st.info("Nenhuma aposta resolvida (won/lost) com EV ≥ 15%.")
        else:
            # ── Resumo geral ──
            st.subheader("Resumo geral")
            _p_s = summary_stats(_p_df)
            render_kpi_row([
                {"label": "N", "value": _p_s["n"]},
                {"label": "W", "value": _p_s["w"]},
                {"label": "L", "value": _p_s["l"]},
                {"label": "WR%", "value": f"{_p_s['wr']:.1f}"},
                {"label": "Lucro (u)", "value": f"{_p_s['lucro']:+.2f}"},
                {"label": "ROI%", "value": f"{_p_s['roi']:+.2f}"},
                {"label": "Odd média (W)", "value": f"{_p_s['avg_odd_w']:.2f}" if _p_s["avg_odd_w"] else "—"},
                {"label": "Odd média (L)", "value": f"{_p_s['avg_odd_l']:.2f}" if _p_s["avg_odd_l"] else "—"},
            ])

            st.divider()

            # ── P/L curve ──
            st.subheader("P/L acumulada por dia")
            _p_pl = build_pl_curve(_p_df)
            render_pl_curve(_p_pl)

            st.divider()

            # ── Period profits ──
            if "game_date_day" in _p_df.columns:
                _p_today = datetime.now().date()
                _p_yesterday = _p_today - timedelta(days=1)
                _p_days = pd.to_datetime(_p_df["game_date_day"], errors="coerce")

                def _p_lucro_mask(mask):
                    sub = _p_df[mask]
                    return float(pd.to_numeric(sub["lucro_u"], errors="coerce").fillna(0).sum()) if not sub.empty else 0.0

                render_kpi_row([
                    {"label": "Hoje", "value": f"{_p_lucro_mask(_p_days.dt.date == _p_today):+.2f}u"},
                    {"label": "Ontem", "value": f"{_p_lucro_mask(_p_days.dt.date == _p_yesterday):+.2f}u"},
                    {"label": "7 dias", "value": f"{_p_lucro_mask(_p_days.dt.date >= (_p_today - timedelta(days=6))):+.2f}u"},
                    {"label": "30 dias", "value": f"{_p_lucro_mask(_p_days.dt.date >= (_p_today - timedelta(days=29))):+.2f}u"},
                ])

                st.divider()

            # ── Empírico vs ML comparison ──
            if method_filter == "Todos":
                st.subheader("Empirico vs ML")
                _p_emp = _p_df[_p_df["metodo"] == "Empírico"]
                _p_ml = _p_df[_p_df["metodo"] == "ML"]
                _se = summary_stats(_p_emp)
                _sm = summary_stats(_p_ml)

                _comp_df = pd.DataFrame({
                    "Metrica": ["Apostas", "Vitorias", "Derrotas", "Winrate", "Lucro (u)", "ROI%", "Odd media (W)"],
                    "Empirico": [
                        str(_se["n"]), str(_se["w"]), str(_se["l"]),
                        f"{_se['wr']:.1f}%",
                        f"{_se['lucro']:+.2f}",
                        f"{_se['roi']:+.1f}%",
                        f"{_se['avg_odd_w']:.2f}" if _se["avg_odd_w"] else "—",
                    ],
                    "ML": [
                        str(_sm["n"]), str(_sm["w"]), str(_sm["l"]),
                        f"{_sm['wr']:.1f}%",
                        f"{_sm['lucro']:+.2f}",
                        f"{_sm['roi']:+.1f}%",
                        f"{_sm['avg_odd_w']:.2f}" if _sm["avg_odd_w"] else "—",
                    ],
                })
                st.dataframe(_comp_df, width="stretch", hide_index=True)

                # P/L comparison side by side
                _col_pl_e, _col_pl_m = st.columns(2)
                with _col_pl_e:
                    st.caption("P/L Empirico")
                    render_pl_curve(build_pl_curve(_p_emp))
                with _col_pl_m:
                    st.caption("P/L ML")
                    render_pl_curve(build_pl_curve(_p_ml))

                st.divider()

            # ── Over vs Under ──
            st.subheader("Over vs Under")
            _ou_tab_all, _ou_tab_emp, _ou_tab_ml = st.tabs(["Geral", "Empirico", "ML"])
            for _ou_tab, _ou_label, _ou_subset in [
                (_ou_tab_all, "Geral", _p_df),
                (_ou_tab_emp, "Empirico", _p_df[_p_df["metodo"] == "Empírico"]),
                (_ou_tab_ml, "ML", _p_df[_p_df["metodo"] == "ML"]),
            ]:
                with _ou_tab:
                    _ou_agg = agg_stats(_ou_subset, "side")
                    _ou_agg = _ou_agg[_ou_agg["side"].isin(["OVER", "UNDER"])].copy() if not _ou_agg.empty else _ou_agg
                    if _ou_agg.empty:
                        st.caption("Sem dados.")
                    else:
                        _ou_c1, _ou_c2 = st.columns([1, 1])
                        with _ou_c1:
                            st.dataframe(
                                _ou_agg[["side", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                                width="stretch", hide_index=True,
                                column_config={
                                    "side": st.column_config.TextColumn("Side"),
                                    "N": st.column_config.NumberColumn(format="%d"),
                                    "WR%": st.column_config.NumberColumn(format="%.1f"),
                                    "Lucro(u)": st.column_config.NumberColumn(format="%+.2f"),
                                    "ROI%": st.column_config.NumberColumn(format="%.2f"),
                                    "AvgOdd(W)": st.column_config.NumberColumn(format="%.2f"),
                                },
                            )
                        with _ou_c2:
                            st.bar_chart(_ou_agg.set_index("side")[["ROI%"]])

            st.divider()

            # ── Por liga ──
            st.subheader("Por liga")
            _lg_tab_all, _lg_tab_emp, _lg_tab_ml = st.tabs(["Geral", "Empirico", "ML"])
            for _lg_tab, _lg_label, _lg_subset in [
                (_lg_tab_all, "Geral", _p_df),
                (_lg_tab_emp, "Empirico", _p_df[_p_df["metodo"] == "Empírico"]),
                (_lg_tab_ml, "ML", _p_df[_p_df["metodo"] == "ML"]),
            ]:
                with _lg_tab:
                    _lg_agg = agg_stats(_lg_subset, "league_name")
                    _lg_agg = _lg_agg[_lg_agg["league_name"] != "—"].copy() if not _lg_agg.empty else _lg_agg
                    if _lg_agg.empty:
                        st.caption("Sem dados.")
                    else:
                        st.dataframe(
                            _lg_agg[["league_name", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                            width="stretch", hide_index=True,
                            column_config={
                                "league_name": st.column_config.TextColumn("Liga"),
                                "N": st.column_config.NumberColumn(format="%d"),
                                "WR%": st.column_config.NumberColumn(format="%.1f"),
                                "Lucro(u)": st.column_config.NumberColumn(format="%+.2f"),
                                "ROI%": st.column_config.NumberColumn(format="%.2f"),
                                "AvgOdd(W)": st.column_config.NumberColumn(format="%.2f"),
                            },
                        )

            st.divider()

            # ── Por faixa de odds ──
            st.subheader("Por faixa de odds")
            _ob_tab_all, _ob_tab_emp, _ob_tab_ml = st.tabs(["Geral", "Empirico", "ML"])
            _ob_order = odds_bucket_order()
            for _ob_tab, _ob_label, _ob_subset in [
                (_ob_tab_all, "Geral", _p_df),
                (_ob_tab_emp, "Empirico", _p_df[_p_df["metodo"] == "Empírico"]),
                (_ob_tab_ml, "ML", _p_df[_p_df["metodo"] == "ML"]),
            ]:
                with _ob_tab:
                    _ob_agg = agg_stats(_ob_subset, "odds_bucket")
                    if not _ob_agg.empty:
                        _ob_agg["_ord"] = _ob_agg["odds_bucket"].apply(
                            lambda x: _ob_order.index(x) if x in _ob_order else 999
                        )
                        _ob_agg = _ob_agg.sort_values("_ord").drop(columns=["_ord"])
                        _ob_c1, _ob_c2 = st.columns([1, 1])
                        with _ob_c1:
                            st.dataframe(
                                _ob_agg[["odds_bucket", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                                width="stretch", hide_index=True,
                                column_config={
                                    "odds_bucket": st.column_config.TextColumn("Faixa"),
                                    "N": st.column_config.NumberColumn(format="%d"),
                                    "WR%": st.column_config.NumberColumn(format="%.1f"),
                                    "Lucro(u)": st.column_config.NumberColumn(format="%+.2f"),
                                    "ROI%": st.column_config.NumberColumn(format="%.2f"),
                                    "AvgOdd(W)": st.column_config.NumberColumn(format="%.2f"),
                                },
                            )
                        with _ob_c2:
                            st.bar_chart(_ob_agg.set_index("odds_bucket")[["ROI%"]])
                    else:
                        st.caption("Sem dados.")

            st.divider()

            # ── Por mapa ──
            st.subheader("Por mapa")
            _mp_tab_all, _mp_tab_emp, _mp_tab_ml = st.tabs(["Geral", "Empirico", "ML"])
            for _mp_tab, _mp_label, _mp_subset in [
                (_mp_tab_all, "Geral", _p_df),
                (_mp_tab_emp, "Empirico", _p_df[_p_df["metodo"] == "Empírico"]),
                (_mp_tab_ml, "ML", _p_df[_p_df["metodo"] == "ML"]),
            ]:
                with _mp_tab:
                    _mp_agg = agg_stats(_mp_subset, "mapa_label")
                    if not _mp_agg.empty:
                        st.dataframe(
                            _mp_agg[["mapa_label", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                            width="stretch", hide_index=True,
                            column_config={
                                "mapa_label": st.column_config.TextColumn("Mapa"),
                                "N": st.column_config.NumberColumn(format="%d"),
                                "WR%": st.column_config.NumberColumn(format="%.1f"),
                                "Lucro(u)": st.column_config.NumberColumn(format="%+.2f"),
                                "ROI%": st.column_config.NumberColumn(format="%.2f"),
                                "AvgOdd(W)": st.column_config.NumberColumn(format="%.2f"),
                            },
                        )
                    else:
                        st.caption("Sem dados.")

            # ── Cenários (Top N por jogo+mapa) ──
            with st.expander("📊 Cenários (Top N por jogo+mapa)", expanded=False):
                st.caption("Simula performance com 1/2/3 apostas por mapa (maior odd ou maior EV).")

                def _pick_top_n_per_game_map(_df: pd.DataFrame, *, n: int, by: str) -> pd.DataFrame:
                    if _df.empty or "matchup_id" not in _df.columns or "mapa_label" not in _df.columns:
                        return _df.iloc[0:0].copy()
                    if by not in _df.columns:
                        return _df.iloc[0:0].copy()
                    work = _df.copy()
                    work["odd_decimal"] = pd.to_numeric(work["odd_decimal"], errors="coerce")
                    work["expected_value"] = pd.to_numeric(work["expected_value"], errors="coerce")
                    sort_cols = ["odd_decimal", "expected_value"] if by == "odd_decimal" else ["expected_value", "odd_decimal"]
                    work = work.sort_values(by=sort_cols, ascending=[False, False], na_position="last")
                    parts = []
                    for _, g in work.groupby(["matchup_id", "mapa_label"], dropna=False, sort=False):
                        parts.append(g.head(max(1, int(n))))
                    return pd.concat(parts, ignore_index=True) if parts else work.iloc[0:0].copy()

                scenarios = []
                for n_pick in (1, 2, 3):
                    for by_col, label in [("odd_decimal", "Odd"), ("expected_value", "EV")]:
                        _df_pick = _pick_top_n_per_game_map(_p_df, n=n_pick, by=by_col)
                        _s_pick = summary_stats(_df_pick)
                        scenarios.append({
                            "Cenário": f"Top {n_pick} por {label}",
                            "N": _s_pick["n"],
                            "WR%": _s_pick["wr"],
                            "Lucro(u)": _s_pick["lucro"],
                            "ROI%": _s_pick["roi"],
                        })
                df_scen = pd.DataFrame(scenarios)
                st.dataframe(
                    df_scen, width="stretch", hide_index=True,
                    column_config={
                        "N": st.column_config.NumberColumn(format="%d"),
                        "WR%": st.column_config.NumberColumn(format="%.1f"),
                        "Lucro(u)": st.column_config.NumberColumn(format="%+.2f"),
                        "ROI%": st.column_config.NumberColumn(format="%+.2f"),
                    },
                )

            # ── Best/worst league ──
            _bw_lg = agg_stats(_p_df, "league_name")
            _bw_lg = _bw_lg[_bw_lg["league_name"] != "—"].copy() if not _bw_lg.empty else _bw_lg
            if not _bw_lg.empty and len(_bw_lg) >= 2:
                st.divider()
                best = _bw_lg.loc[_bw_lg["ROI%"].idxmax()]
                worst = _bw_lg.loc[_bw_lg["ROI%"].idxmin()]
                b1, b2 = st.columns(2)
                with b1:
                    st.metric("Melhor liga (ROI%)", f"{best['league_name']}", f"{best['ROI%']:+.2f}%")
                with b2:
                    st.metric("Pior liga (ROI%)", f"{worst['league_name']}", f"{worst['ROI%']:+.2f}%")
