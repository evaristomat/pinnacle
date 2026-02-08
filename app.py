"""
App Streamlit - Pinnacle: Apostas do dia/amanhã e Draft + ML.
"""
from __future__ import annotations

import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

ROOT = Path(__file__).parent
# EV mínimo no app: só mostra apostas com EV >= 15% (qualquer método). Ajustável via env var.
EV_MIN_APP = float(os.getenv("PINNACLE_EV_MIN_APP", "0.15"))
# Ordem: inserir por último = ficar primeiro. Queremos bets_tracker antes de odds_analysis (config).
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
from config import PINNACLE_DB, BETS_DB, USER_BETS_DB, HISTORY_DB

# Estatísticas resolvidas EV15+
from stats_resolved import (
    fetch_resolved_ev15,
    build_df,
    agg_stats,
    agg_stats_multi,
    summary_stats,
    odds_bucket_order,
)

st.set_page_config(
    page_title="Pinnacle Apostas & Draft",
    page_icon="🎮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        "SELECT DISTINCT t1 AS t FROM matchups WHERE league = ? UNION SELECT t2 FROM matchups WHERE league = ? ORDER BY t",
        (league, league),
    )
    out = [r[0] for r in cur.fetchall() if r[0]]
    conn.close()
    return out


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
    """Converte results + value_bets em lista de bet_data (só EV >= EV_MIN_APP e com vb_match).
    mapa_sel: mapa a associar (1, 2, etc.); filtra value_bets por esse mapa para evitar duplicatas Map 1/2."""
    def _norm(s):
        return (s or "").strip().lower()

    if not results or not value_bets or matchup_id_sel is None:
        return []
    # Filtra value_bets pelo mapa selecionado (evita duplicatas: mesma linha em Map 1 e Map 2)
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


def _render_draft_ml_bets_table(bet_rows: list[dict], key_prefix: str = "draft_ml_"):
    """
    Mostra tabela de apostas Draft+ML com botão 'Marcar como feita' por linha (igual Apostas Hoje).
    bet_rows deve estar em st.session_state['draft_ml_bet_rows'] para o clique funcionar.
    """
    if not bet_rows:
        return
    try:
        init_database(db_path=USER_BETS_DB)
    except Exception:
        pass
    already_placed = _get_placed_bets_keys(db_path=USER_BETS_DB)
    # Chave para Draft+ML: (matchup_id, market_type, mapa, line_value, side, metodo="ml")
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

    widths = [1.3, 1.0, 2.5, 0.7, 1.3, 0.8, 0.8, 0.9, 1.0, 0.9, 0.9, 0.5]
    header_cols = st.columns(widths)
    headers = ["Data/Hora", "Liga", "Jogo", "Mapa", "Mercado", "Linha", "Odd", "fair_odds", "EV%", "Método", "Status", ""]
    for h, col in zip(headers, header_cols):
        with col:
            st.markdown(f"**{h}**")

    for i, b in enumerate(bet_rows):
        game_date = b.get("game_date") or ""
        dt_str = game_date[:16].replace("T", " ") if game_date else ""
        jogo = f"{b.get('home_team', '')} vs {b.get('away_team', '')}"
        ev = (b.get("expected_value") or 0) * 100
        prob = b.get("empirical_prob")
        fair_odds = (1.0 / prob) if (prob is not None and prob > 0) else None
        rk = row_key(b)
        is_placed = rk in already_placed

        cols = st.columns(widths)
        with cols[0]:
            st.text(dt_str)
        with cols[1]:
            st.text(b.get("league_name") or "")
        with cols[2]:
            st.text(jogo)
        with cols[3]:
            mapa_disp = b.get("mapa")
            st.text(f"Map {mapa_disp}" if mapa_disp is not None else "")
        with cols[4]:
            st.text(f"{b.get('side', '')} {b.get('line_value')}")
        with cols[5]:
            st.text(f"{float(b.get('line_value') or 0):.1f}")
        with cols[6]:
            st.text(f"{float(b.get('odd_decimal') or 0):.2f}")
        with cols[7]:
            st.text(f"{fair_odds:.2f}" if fair_odds else "")
        with cols[8]:
            if ev > 0:
                st.markdown(f"<span style='color: #28a745; font-weight: bold'>🟢 +{ev:.1f}%</span>", unsafe_allow_html=True)
            else:
                st.text(f"{ev:.1f}%")
        with cols[9]:
            st.text("ML")
        with cols[10]:
            st.text("pending")
        with cols[11]:
            if is_placed:
                st.caption("✅ Já feita")
            else:
                if st.button("✓", key=f"{key_prefix}mark_{i}", help="Marcar como feita", use_container_width=True, type="secondary"):
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
                                "SELECT id FROM bets WHERE matchup_id=? AND market_type=? AND COALESCE(mapa, -1)=COALESCE(?, -1) AND line_value=? AND side=? AND metodo=? ORDER BY id DESC LIMIT 1",
                                (bd["matchup_id"], bd["market_type"], bd.get("mapa"), bd["line_value"], bd["side"], bd["metodo"]),
                            )
                            ex = cur.fetchone()
                            conn.close()
                            if ex and mark_bet_placed(ex["id"], db_path=USER_BETS_DB):
                                st.rerun()
                    else:
                        st.warning("Dados da aposta não encontrados. Rode o modelo novamente.")


# ---------------------------------------------------------------------------
# OddsAnalyzer (lazy load)
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_analyzer():
    import io
    import contextlib
    import importlib.util

    f = io.StringIO()
    # OddsAnalyzer usa config e normalizer do odds_analysis
    _oa = ROOT / "odds_analysis"
    
    # Carrega config do odds_analysis
    _cfg_spec = importlib.util.spec_from_file_location("odds_config", _oa / "config.py")
    _cfg_mod = importlib.util.module_from_spec(_cfg_spec)
    _cfg_spec.loader.exec_module(_cfg_mod)
    _prev_config = sys.modules.get("config")
    sys.modules["config"] = _cfg_mod
    
    # Carrega normalizer do odds_analysis
    _nz_spec = importlib.util.spec_from_file_location("oa_normalizer", _oa / "normalizer.py")
    _nz_mod = importlib.util.module_from_spec(_nz_spec)
    _nz_spec.loader.exec_module(_nz_mod)
    _prev_normalizer = sys.modules.get("normalizer")
    sys.modules["normalizer"] = _nz_mod

    try:
        with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
            # Import deve resolver config = odds_config e normalizer = oa_normalizer
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
    """Análise empírica para um matchup. Retorna analysis ou None."""
    try:
        analyzer = _get_analyzer()
        return analyzer.analyze_game(matchup_id, force_method="probabilidade_empirica")
    except Exception as e:
        st.error(f"Erro na análise empírica: {e}")
        return None


def _run_ml_with_draft(draft_data: dict, line_value: float):
    """Predição ML para draft + linha. Retorna dict com prediction, probability_over, etc."""
    try:
        analyzer = _get_analyzer()
        result = analyzer._predict_ml(draft_data, line_value)
        return result
    except Exception as e:
        # Loga erro detalhado para debug
        import traceback
        error_msg = f"Erro ao rodar modelo ML: {str(e)}\n{traceback.format_exc()}"
        print(f"[ERRO ML] {error_msg}")
        return None


# ---------------------------------------------------------------------------
# Helpers UI
# ---------------------------------------------------------------------------


def _build_bets_table(bets):
    """Retorna DataFrame com dados das apostas, ordenados por game_date e mapa."""

    def _calculated_prob(b: dict) -> float | None:
        """Probabilidade calculada do evento para a aposta (empírica/ML)."""
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
                # Fallback genérico, se algum produtor gravar outro campo
                p = md.get("calculated_prob") or md.get("probability") or md.get("prob")

            if isinstance(p, (int, float)) and p > 0:
                return float(p)

        return None

    rows = []
    for b in bets:
        ev = (b.get("expected_value") or 0) * 100
        metodo = "ML" if (b.get("metodo") or "").lower() == "ml" else "Empírico"
        jogo = f"{b['home_team']} vs {b['away_team']}"
        game_date = b.get("game_date") or ""
        dt_str = game_date[:16].replace("T", " ") if game_date else ""
        # Mapa: mostra "Map 1", "Map 2" ou vazio se não tiver
        mapa_val = b.get('mapa')
        mapa_display = f"Map {mapa_val}" if mapa_val is not None else ""

        prob = _calculated_prob(b)
        fair_odds = (1.0 / prob) if (prob is not None and prob > 0) else None
        rows.append({
            "id": b["id"],
            "matchup_id": b.get("matchup_id"),
            "game_date": game_date,  # Para ordenação
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
            "mapa_sort": mapa_val if mapa_val is not None else 999,  # Para ordenação (NULL vai pro final)
            # Para checar se já está em user_bets.db como 'feita' (não exibir no dataframe)
            "market_type": b.get("market_type") or "total_kills",
            "side": (b.get("side") or "").strip().lower(),
            "metodo": (b.get("metodo") or "probabilidade_empirica").strip().lower(),
            "mapa_raw": mapa_val if mapa_val is not None else -1,
        })
    # Ordena por data/horário, depois por mapa (1, 2, depois NULL)
    rows.sort(key=lambda x: (x.get("game_date", "") or "", x.get("mapa_sort", 999)))
    df = pd.DataFrame(rows)
    # Remove coluna auxiliar de ordenação
    if "mapa_sort" in df.columns:
        df = df.drop(columns=["mapa_sort"])
    return df


def _get_placed_bets_keys(db_path=None):
    """Retorna set de (matchup_id, market_type, mapa, line_value, side, metodo) das apostas já feitas em user_bets.db."""
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


def _render_bets_table_with_buttons(df, show_button=True, show_remove=False, *, source: str = "model", key_prefix: str = "", already_placed_keys: set = None):
    """
    Renderiza tabela com botões.

    source:
      - "model": bets do modelo (bets.db) → botão ✓ copia para user_bets.db como 'feita'
      - "user": bets do usuário (user_bets.db) → botão ✓ marca como 'feita' no user_bets.db
    already_placed_keys: set de (matchup_id, market_type, mapa, line_value, side, metodo) já feitas em user_bets (só para source="model").
    """
    if df.empty:
        return
    already_placed_keys = already_placed_keys or set()

    # Prepara dados (remove colunas internas do display)
    cols_to_drop = ["id", "matchup_id", "game_date", "market_type", "side", "metodo", "mapa_raw"]
    df_display = df.drop(columns=[c for c in cols_to_drop if c in df.columns], errors="ignore").copy()
    
    # Formata EV% com cores
    def format_ev(val):
        if val > 0:
            return f"🟢 +{val:.1f}%"
        elif val < 0:
            return f"🔴 {val:.1f}%"
        else:
            return f"{val:.1f}%"
    
    df_display["EV%"] = df_display["EV%"].apply(format_ev)
    
    # Se não tem botão nem remover, usa dataframe simples
    if not show_button and not show_remove:
        column_config = {
            "Data/Hora": st.column_config.TextColumn("Data/Hora", width="small"),
            "Liga": st.column_config.TextColumn("Liga", width="small"),
            "Jogo": st.column_config.TextColumn("Jogo", width="medium"),
            "Mapa": st.column_config.TextColumn("Mapa", width="small"),
            "Mercado": st.column_config.TextColumn("Mercado", width="small"),
            "Linha": st.column_config.NumberColumn("Linha", format="%.1f", width="small"),
            "Odd": st.column_config.NumberColumn("Odd", format="%.2f", width="small"),
            "fair_odds": st.column_config.NumberColumn("fair_odds", format="%.2f", width="small"),
            "EV%": st.column_config.TextColumn("EV%", width="small"),
            "Método": st.column_config.TextColumn("Método", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
        }
        st.dataframe(df_display, width="stretch", column_config=column_config, hide_index=True)
        return
    
    # Com botão: cria tabela customizada com botões inline sutis ao lado de cada linha
    # Larguras proporcionais das colunas (última coluna é para o botão)
    # [Data/Hora, Liga, Jogo, Mapa, Mercado, Linha, Odd, fair_odds, EV%, Método, Status, Botão]
    widths = [1.3, 1.0, 2.5, 0.7, 1.3, 0.8, 0.8, 0.9, 1.0, 0.9, 0.9, 0.5]
    
    # Cabeçalho
    header_cols = st.columns(widths)
    headers = ["Data/Hora", "Liga", "Jogo", "Mapa", "Mercado", "Linha", "Odd", "fair_odds", "EV%", "Método", "Status", ""]
    for i, h in enumerate(headers):
        with header_cols[i]:
            if h:  # Não mostra header na última coluna (botão)
                st.markdown(f"**{h}**")
    
    # Linhas da tabela
    for idx, row in df.iterrows():
        cols = st.columns(widths)
        
        with cols[0]:
            st.text(str(row["Data/Hora"])[:16] if pd.notna(row["Data/Hora"]) else "")
        with cols[1]:
            st.text(str(row["Liga"]) if pd.notna(row["Liga"]) else "")
        with cols[2]:
            st.text(str(row["Jogo"]) if pd.notna(row["Jogo"]) else "")
        with cols[3]:
            # Mapa: destaca Map 1 e Map 2 com cores diferentes
            mapa_val = str(row["Mapa"]) if pd.notna(row["Mapa"]) and str(row["Mapa"]).strip() else ""
            if mapa_val == "Map 1":
                st.markdown(f"<span style='color: #007bff; font-weight: bold'>{mapa_val}</span>", unsafe_allow_html=True)
            elif mapa_val == "Map 2":
                st.markdown(f"<span style='color: #ff6b35; font-weight: bold'>{mapa_val}</span>", unsafe_allow_html=True)
            else:
                st.text(mapa_val)
        with cols[4]:
            st.text(str(row["Mercado"]) if pd.notna(row["Mercado"]) else "")
        with cols[5]:
            linha = row["Linha"]
            st.text(f"{linha:.1f}" if pd.notna(linha) else "")
        with cols[6]:
            odd = row["Odd"]
            st.text(f"{odd:.2f}" if pd.notna(odd) else "")
        with cols[7]:
            fair = row.get("fair_odds")
            st.text(f"{float(fair):.2f}" if pd.notna(fair) else "")
        with cols[8]:
            ev = row["EV%"]
            if pd.notna(ev):
                if ev > 0:
                    st.markdown(f"<span style='color: #28a745; font-weight: bold'>🟢 +{ev:.1f}%</span>", unsafe_allow_html=True)
                elif ev < 0:
                    st.markdown(f"<span style='color: #dc3545; font-weight: bold'>🔴 {ev:.1f}%</span>", unsafe_allow_html=True)
                else:
                    st.text(f"{ev:.1f}%")
            else:
                st.text("")
        with cols[9]:
            st.text(str(row["Método"]) if pd.notna(row["Método"]) else "")
        with cols[10]:
            status = str(row["Status"]).lower() if pd.notna(row["Status"]) else ""
            st.text(f"`{status}`")
        
        # Botão sutil na última coluna - do tamanho da linha
        with cols[11]:
            status_val = str(row["Status"]).lower().strip() if pd.notna(row["Status"]) else ""
            # Para source="model": checar se já está em user_bets.db como feita
            row_key = None
            if source == "model" and already_placed_keys:
                matchup_id = row.get("matchup_id")
                market_type = (row.get("market_type") or "total_kills").strip().lower() if pd.notna(row.get("market_type")) else "total_kills"
                mapa_raw = row.get("mapa_raw")
                if pd.isna(mapa_raw) or mapa_raw is None:
                    mapa_raw = -1
                line_val = row.get("Linha")
                line_val = float(line_val) if line_val is not None and pd.notna(line_val) else None
                side = (row.get("side") or "").strip().lower() if pd.notna(row.get("side")) else ""
                metodo = (row.get("metodo") or "probabilidade_empirica").strip().lower() if pd.notna(row.get("metodo")) else "probabilidade_empirica"
                row_key = (matchup_id, market_type, mapa_raw, line_val, side, metodo)
            is_already_placed = row_key is not None and row_key in already_placed_keys

            if is_already_placed:
                st.caption("✅ Já feita")
            elif status_val == "pending" and show_button:
                # Botão sutil e discreto para marcar como feita
                if st.button(
                    "✓",
                    key=f"{key_prefix}mark_{row['id']}",
                    help="Marcar como feita",
                    use_container_width=True,
                    type="secondary",
                ):
                    if source == "model":
                        ok = _add_model_bet_to_user_db(int(row["id"]))
                    else:
                        ok = mark_bet_placed(int(row["id"]), db_path=USER_BETS_DB)

                    if ok:
                        st.rerun()
            elif status_val == "feita" and show_remove:
                # Botão para remover de apostas feitas
                if st.button(
                    "✗",
                    key=f"{key_prefix}remove_{row['id']}",
                    help="Remover de apostas feitas",
                    use_container_width=True,
                    type="secondary",
                ):
                    if unmark_bet_placed(int(row["id"]), db_path=USER_BETS_DB):
                        st.rerun()
            elif show_remove:
                # Se show_remove está ativo mas status não é "feita", mostra espaço vazio
                st.text("")
            else:
                st.text("")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("🎮 Pinnacle – Apostas & Draft")
st.caption(f"Hoje: {_today()} | Amanhã: {_tomorrow()}")

# Inicializa banco do usuário (separado do banco do modelo)
try:
    init_database(db_path=USER_BETS_DB)
except Exception:
    pass  # Banco já existe ou erro na inicialização


def _add_model_bet_to_user_db(model_bet_id: int) -> bool:
    """
    Copia uma aposta do banco do MODELO (bets.db) para o banco do USUÁRIO (user_bets.db)
    e marca como 'feita' (aposta realizada).
    """
    src = get_bet_by_id(int(model_bet_id), db_path=BETS_DB)
    if not src:
        return False

    # Metadata: preserva e anota origem
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
        # Importante: no banco do usuário a aposta entra como FEITA
        "status": "feita",
        "metadata": md,
    }

    new_id = save_bet(bet_data, db_path=USER_BETS_DB)
    if new_id:
        return True

    # Já existe no user_bets.db: tenta achar e marcar como feita (se estiver pending)
    conn = sqlite3.connect(USER_BETS_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, status FROM bets
        WHERE matchup_id = ?
          AND market_type = ?
          AND COALESCE(mapa, -1) = COALESCE(?, -1)
          AND line_value = ?
          AND side = ?
          AND metodo = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            bet_data["matchup_id"],
            bet_data["market_type"],
            bet_data.get("mapa"),
            bet_data.get("line_value"),
            bet_data["side"],
            bet_data.get("metodo", "probabilidade_empirica"),
        ),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return False

    status = str(row["status"]).lower().strip()
    if status == "pending":
        return mark_bet_placed(int(row["id"]), db_path=USER_BETS_DB)

    # Se já está feita / resolvida, consideramos OK
    return True

TAB_APOSTAS_HOJE = "📋 Apostas (Hoje)"
TAB_APOSTAS_FUTUROS = "📅 Apostas (Futuros)"
TAB_APOSTAS_FEITAS = "✅ Apostas Feitas"
TAB_DRAFT_ML = "🃏 Draft + ML"
TAB_ESTATISTICAS = "📊 Estatísticas (EV15+)"
TAB_OPTIONS = [TAB_APOSTAS_HOJE, TAB_APOSTAS_FUTUROS, TAB_APOSTAS_FEITAS, TAB_DRAFT_ML, TAB_ESTATISTICAS]

if "main_tab" not in st.session_state:
    st.session_state["main_tab"] = TAB_APOSTAS_HOJE
chosen = st.radio(
    "Aba",
    options=TAB_OPTIONS,
    key="main_tab",
    horizontal=True,
    label_visibility="collapsed",
)

# ----- Tab 1: Apostas Hoje -----
if chosen == TAB_APOSTAS_HOJE:
    if not BETS_DB.exists():
        st.warning("Banco do modelo (`bets.db`) não encontrado. Rode `bets_tracker/main.py collect` primeiro.")
    else:
        hoje = get_bets_by_date(_today(), _today(), db_path=BETS_DB)
        hoje = [b for b in hoje if float(b.get("expected_value") or 0.0) >= EV_MIN_APP]
        df_hoje = _build_bets_table(hoje)

        if df_hoje.empty:
            st.info("Nenhuma aposta para hoje.")
        else:
            # Filtro por mapa
            if "Mapa" in df_hoje.columns:
                mapas_disponiveis = sorted([m for m in df_hoje["Mapa"].unique() if pd.notna(m) and str(m).strip()], key=lambda x: str(x))
            else:
                mapas_disponiveis = []
            
            if mapas_disponiveis:
                filtro_mapa = st.selectbox(
                    "🔍 Filtrar por mapa",
                    ["Todos"] + mapas_disponiveis,
                    key="filtro_mapa_hoje"
                )
            else:
                filtro_mapa = "Todos"
            
            # Aplica filtro
            if filtro_mapa != "Todos" and "Mapa" in df_hoje.columns:
                df_hoje_filtrado = df_hoje[df_hoje["Mapa"] == filtro_mapa].copy()
            else:
                df_hoje_filtrado = df_hoje.copy()
            
            # Estatísticas por mapa
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📅 Apostas hoje", f"{len(df_hoje_filtrado)}", delta=f"{len(df_hoje_filtrado) - len(df_hoje)}" if filtro_mapa != "Todos" else None)
            with col2:
                if "Mapa" in df_hoje.columns:
                    total_map1 = len(df_hoje[df_hoje["Mapa"] == "Map 1"])
                else:
                    total_map1 = 0
                st.metric("🗺️ Map 1", total_map1)
            with col3:
                if "Mapa" in df_hoje.columns:
                    total_map2 = len(df_hoje[df_hoje["Mapa"] == "Map 2"])
                else:
                    total_map2 = 0
                st.metric("🗺️ Map 2", total_map2)
            with col4:
                if "Mapa" in df_hoje.columns:
                    total_sem_mapa = len(df_hoje[df_hoje["Mapa"].isna() | (df_hoje["Mapa"].astype(str) == "")])
                else:
                    total_sem_mapa = len(df_hoje)
                st.metric("❓ Sem mapa", total_sem_mapa)
            
            _render_bets_table_with_buttons(
                df_hoje_filtrado,
                show_button=True,
                source="model",
                key_prefix="hoje_all_",
                already_placed_keys=_get_placed_bets_keys(USER_BETS_DB),
            )
            
            # Estatísticas
            stats = get_bet_stats(db_path=BETS_DB)
            st.divider()
            st.caption(
                f"Total geral: {stats['total']} apostas | "
                f"Por status: {stats.get('by_status') or {}} | "
                f"Empírico: {stats.get('by_metodo', {}).get('probabilidade_empirica', 0)} | "
                f"ML: {stats.get('by_metodo', {}).get('ml', 0)}"
            )


# ----- Tab 2: Apostas Futuros -----
elif chosen == TAB_APOSTAS_FUTUROS:
    if not BETS_DB.exists():
        st.warning("Banco do modelo (`bets.db`) não encontrado. Rode `bets_tracker/main.py collect` primeiro.")
    else:
        # Busca apostas futuras (depois de hoje)
        futuros = get_bets_by_date(_tomorrow(), "2099-12-31", db_path=BETS_DB)  # Todos os futuros
        futuros = [b for b in futuros if float(b.get("expected_value") or 0.0) >= EV_MIN_APP]
        df_futuros = _build_bets_table(futuros)

        if df_futuros.empty:
            st.info("Nenhuma aposta futura.")
        else:
            # Filtro por mapa
            if "Mapa" in df_futuros.columns:
                mapas_disponiveis = sorted([m for m in df_futuros["Mapa"].unique() if pd.notna(m) and str(m).strip()], key=lambda x: str(x))
            else:
                mapas_disponiveis = []
            
            if mapas_disponiveis:
                filtro_mapa = st.selectbox(
                    "🔍 Filtrar por mapa",
                    ["Todos"] + mapas_disponiveis,
                    key="filtro_mapa_futuros"
                )
            else:
                filtro_mapa = "Todos"
            
            # Aplica filtro
            if filtro_mapa != "Todos" and "Mapa" in df_futuros.columns:
                df_futuros_filtrado = df_futuros[df_futuros["Mapa"] == filtro_mapa].copy()
            else:
                df_futuros_filtrado = df_futuros.copy()
            
            # Estatísticas por mapa
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("📅 Apostas futuras", f"{len(df_futuros_filtrado)}", delta=f"{len(df_futuros_filtrado) - len(df_futuros)}" if filtro_mapa != "Todos" else None)
            with col2:
                if "Mapa" in df_futuros.columns:
                    total_map1 = len(df_futuros[df_futuros["Mapa"] == "Map 1"])
                else:
                    total_map1 = 0
                st.metric("🗺️ Map 1", total_map1)
            with col3:
                if "Mapa" in df_futuros.columns:
                    total_map2 = len(df_futuros[df_futuros["Mapa"] == "Map 2"])
                else:
                    total_map2 = 0
                st.metric("🗺️ Map 2", total_map2)
            with col4:
                if "Mapa" in df_futuros.columns:
                    total_sem_mapa = len(df_futuros[df_futuros["Mapa"].isna() | (df_futuros["Mapa"].astype(str) == "")])
                else:
                    total_sem_mapa = len(df_futuros)
                st.metric("❓ Sem mapa", total_sem_mapa)
            
            _render_bets_table_with_buttons(
                df_futuros_filtrado,
                show_button=True,
                source="model",
                key_prefix="fut_all_",
                already_placed_keys=_get_placed_bets_keys(USER_BETS_DB),
            )
            
            # Estatísticas
            stats = get_bet_stats(db_path=BETS_DB)
            st.divider()
            st.caption(
                f"Total geral: {stats['total']} apostas | "
                f"Por status: {stats.get('by_status') or {}} | "
                f"Empírico: {stats.get('by_metodo', {}).get('probabilidade_empirica', 0)} | "
                f"ML: {stats.get('by_metodo', {}).get('ml', 0)}"
            )


# ----- Tab 3: Apostas Feitas -----
elif chosen == TAB_APOSTAS_FEITAS:
    if not USER_BETS_DB.exists():
        st.warning("Banco do usuário (`user_bets.db`) ainda não existe. Marque alguma aposta como feita (✓) nas abas de hoje/futuros.")
    else:
        # ROI/Resumo (sempre visível)
        stats = get_bet_stats(db_path=USER_BETS_DB)
        roi = stats.get("roi") or {}
        if roi.get("total_resolved", 0) > 0:
            st.subheader("📈 Resumo (apostas resolvidas)")
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            with c1:
                st.metric("Resolvidas", int(roi.get("total_resolved", 0)))
            with c2:
                st.metric("Vitórias", int(roi.get("wins", 0)))
            with c3:
                st.metric("Derrotas", int(roi.get("losses", 0)))
            with c4:
                st.metric("Winrate", f"{float(roi.get('win_rate', 0)):.1f}%")
            with c5:
                st.metric("Lucro (u)", f"{float(roi.get('lucro', 0)):+.2f}")
            with c6:
                st.metric("ROI", f"{float(roi.get('return_pct', 0)):+.2f}%")
        else:
            st.caption("Sem apostas resolvidas ainda (status `won/lost`).")

        # Apostas aguardando resultado (status = 'feita')
        feitas = get_placed_bets(db_path=USER_BETS_DB)
        feitas = [b for b in feitas if float(b.get("expected_value") or 0.0) >= EV_MIN_APP]
        df_feitas = _build_bets_table(feitas)

        if df_feitas.empty:
            st.info("Nenhuma aposta aguardando resultado (status `feita`).")
        else:
            st.subheader("⏳ Aguardando resultado")
            # Filtro por mapa
            if "Mapa" in df_feitas.columns:
                mapas_disponiveis = sorted([m for m in df_feitas["Mapa"].unique() if pd.notna(m) and str(m).strip()], key=lambda x: str(x))
            else:
                mapas_disponiveis = []
            
            if mapas_disponiveis:
                filtro_mapa = st.selectbox(
                    "🔍 Filtrar por mapa",
                    ["Todos"] + mapas_disponiveis,
                    key="filtro_mapa_feitas"
                )
            else:
                filtro_mapa = "Todos"
            
            # Aplica filtro
            if filtro_mapa != "Todos" and "Mapa" in df_feitas.columns:
                df_feitas_filtrado = df_feitas[df_feitas["Mapa"] == filtro_mapa].copy()
            else:
                df_feitas_filtrado = df_feitas.copy()
            
            # Estatísticas por mapa
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("✅ Apostas feitas", f"{len(df_feitas_filtrado)}", delta=f"{len(df_feitas_filtrado) - len(df_feitas)}" if filtro_mapa != "Todos" else None)
            with col2:
                if "Mapa" in df_feitas.columns:
                    total_map1 = len(df_feitas[df_feitas["Mapa"] == "Map 1"])
                else:
                    total_map1 = 0
                st.metric("🗺️ Map 1", total_map1)
            with col3:
                if "Mapa" in df_feitas.columns:
                    total_map2 = len(df_feitas[df_feitas["Mapa"] == "Map 2"])
                else:
                    total_map2 = 0
                st.metric("🗺️ Map 2", total_map2)
            with col4:
                if "Mapa" in df_feitas.columns:
                    total_sem_mapa = len(df_feitas[df_feitas["Mapa"].isna() | (df_feitas["Mapa"].astype(str) == "")])
                else:
                    total_sem_mapa = len(df_feitas)
                st.metric("❓ Sem mapa", total_sem_mapa)
            
            st.caption("Apostas que você já realizou, aguardando resultado.")
            
            # Botão para atualizar resultados
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("🔄 Atualizar Resultados", type="primary", use_container_width=True):
                    with st.spinner("Atualizando resultados das apostas feitas..."):
                        try:
                            updater = ResultsUpdater(db_path=USER_BETS_DB)
                            stats = updater.update_all_results(dry_run=False)
                            
                            # Mostra estatísticas
                            st.success("✅ Atualização concluída!")
                            st.json({
                                "Apostas pendentes": stats['pending_bets'],
                                "Matches encontrados": stats['matched'],
                                "Resultados atualizados": stats['updated'],
                                "Não encontrados": stats['not_found'],
                                "Erros": stats['errors']
                            })
                            
                            # Recarrega a página para mostrar resultados atualizados
                            st.rerun()
                        except Exception as e:
                            st.error(f"Erro ao atualizar resultados: {e}")
            
            _render_bets_table_with_buttons(df_feitas_filtrado, show_button=False, show_remove=True, source="user", key_prefix="user_feitas_")
            
            st.divider()
            st.caption("💡 Clique em 'Atualizar Resultados' para cruzar essas apostas com o histórico e atualizar resultados.")

        # Apostas resolvidas (won/lost/void) — não somem após o update
        resolved = get_resolved_bets(db_path=USER_BETS_DB)
        resolved = [b for b in resolved if float(b.get("expected_value") or 0.0) >= EV_MIN_APP]
        df_resolved = _build_bets_table(resolved)
        if not df_resolved.empty:
            st.subheader("✅ Resolvidas (won/lost/void)")
            _render_bets_table_with_buttons(df_resolved, show_button=False, show_remove=False, source="user", key_prefix="user_resolved_")


# ----- Tab 4: Draft + ML -----
elif chosen == TAB_DRAFT_ML:
    st.subheader("Draft do jogo + ML")
    st.caption(
        "Selecione um jogo do dia para preencher liga e times automaticamente, "
        "informe os campeões e rode o modelo. Apostas empíricas + convergência ML = boa/ruim."
    )

    # Próximos jogos do dia (LoL Esports) + ao vivo
    with st.container(border=True):
        st.markdown("**📅 Próximos jogos do dia (LoL Esports)**")
        st.caption("Fonte: esports-api.lolesports.com (schedule + live).")
        try:
            schedule_events = _ls_get_schedule_events()
            live_events = _ls_get_live_events()
            live_match_ids = set()
            for ev in (live_events or []):
                if ev.get("type") == "match":
                    mid = ev.get("match") and ev.get("match", {}).get("id")
                    if mid:
                        live_match_ids.add(str(mid))
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            rows = []
            for ev in (schedule_events or [])[:80]:
                if ev.get("type") != "match":
                    continue
                match = ev.get("match") or {}
                teams = match.get("teams") or []
                if len(teams) < 2:
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
                league = (ev.get("league") or {}).get("name", "") or "—"
                t1 = (teams[0].get("name") or teams[0].get("code") or "").strip() or "—"
                t2 = (teams[1].get("name") or teams[1].get("code") or "").strip() or "—"
                state = "🔴 Ao vivo" if mid in live_match_ids else "⏳ Próximo"
                rows.append({"Liga": league, "Jogo": f"{t1} vs {t2}", "Horário": start_display, "Status": state})
            if rows:
                df_ls = pd.DataFrame(rows)
                st.dataframe(df_ls, use_container_width=True, hide_index=True, column_config={
                    "Liga": st.column_config.TextColumn("Liga", width="medium"),
                    "Jogo": st.column_config.TextColumn("Jogo", width="large"),
                    "Horário": st.column_config.TextColumn("Horário", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small"),
                })
            else:
                st.info("Nenhum jogo encontrado no schedule do LoL Esports.")
        except Exception as e:
            st.warning(f"Não foi possível carregar jogos do LoL Esports: {e}")

    st.divider()

    games_today, games_tomorrow = _games_today_tomorrow()
    games_for_picker = (games_today or []) + (games_tomorrow or [])
    champs = _champions_from_history()
    empty = [""] + (champs or ["Nenhum campeão"])

    mode = st.radio("Modo", ["Jogo do dia (liga/times automático)", "Manual (liga e times)"], horizontal=True)

    league_sel = None
    team1_sel = None
    team2_sel = None
    matchup_id_sel = None
    start_time_sel = None

    if mode == "Jogo do dia (liga/times automático)":
        if not games_for_picker:
            st.info("Nenhum jogo hoje/amanhã no Pinnacle. Rode `python main.py` para atualizar o `pinnacle_data.db` ou use modo Manual.")
        else:
            opts = [
                f"{g['league_name']} — {g['home_team']} vs {g['away_team']} ({g['start_time'][:16]})"
                for g in games_for_picker
            ]
            idx = st.selectbox(
                "Jogo do dia",
                range(len(opts)),
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
        league_sel = st.selectbox("Liga", [""] + (leagues or ["—"]))
        teams = _teams_by_league(league_sel) if league_sel else []
        team1_sel = st.selectbox("Time 1", [""] + (teams or ["—"]))
        team2_sel = st.selectbox("Time 2", [""] + (teams or ["—"]))
        matchup_id_sel = None
        start_time_sel = None

    # -------------------------------------------------------------------
    # Draft ao vivo (LoL Esports)
    # -------------------------------------------------------------------
    def _norm_key(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())

    LOL_CHAMPION_ID_MAP = {
        # Casos comuns (mesmo mapping do seu app antigo)
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
        "Renata": "Renata Glasc",  # API às vezes retorna só "Renata" (ex.: Map 2 Misa)
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
        """Converte championId da API para string que existe no selectbox (options)."""
        if not champ_id:
            return ""
        raw = str(champ_id).strip()
        candidates = [raw]
        mapped = LOL_CHAMPION_ID_MAP.get(raw)
        if mapped:
            candidates.append(mapped)
        # fallback: tenta inserir espaços em CamelCase simples (ex: RenataGlasc -> Renata Glasc)
        if raw and raw.isascii():
            camel = re.sub(r"(?<!^)([A-Z])", r" \1", raw).strip()
            if camel and camel != raw:
                candidates.append(camel)

        # 1) match exato
        for c in candidates:
            if c in options:
                return c

        # 2) match por normalização (remove espaços/apóstrofo etc)
        opt_map = {_norm_key(o): o for o in options if o}
        for c in candidates:
            nk = _norm_key(c)
            if nk in opt_map:
                return opt_map[nk]

        # 3) match por prefixo: "Renata" casa com "Renata Glasc" (API às vezes manda só primeiro nome)
        raw_lower = raw.lower()
        for opt in options:
            if not opt:
                continue
            if opt.lower().startswith(raw_lower) or raw_lower.startswith(_norm_key(opt)):
                return opt
        # 4) opção que contém o champ_id como palavra (ex: "Renata" em "Renata Glasc")
        for opt in options:
            if not opt:
                continue
            if raw_lower in _norm_key(opt) or _norm_key(opt).startswith(raw_lower):
                return opt

        return ""

    ls_enabled = st.checkbox(
        "📡 Buscar draft ao vivo automaticamente (LoL Esports)",
        value=False,
        help="Tenta achar a partida no LoL Esports e preencher os campeões do mapa selecionado.",
        key="ls_enable_live_draft",
    )

    if ls_enabled and league_sel and team1_sel and team2_sel:
        with st.container(border=True):
            st.markdown("**Draft ao vivo (LoL Esports)**")
            st.caption("Fonte: `esports-api.lolesports.com` + `feed.lolesports.com` (livestats window).")

            map_choice = st.selectbox(
                "Mapa que você está assistindo",
                [1, 2, 3, 4, 5],
                index=0,
                key="ls_map_choice",
            )

            col_a, col_b = st.columns([1, 1])
            with col_a:
                do_fetch = st.button("🔄 Buscar draft deste mapa", type="secondary", use_container_width=True)
            with col_b:
                do_fill = st.button("✅ Preencher campeões no formulário", type="primary", use_container_width=True)

            # Busca só quando o usuário pedir (evita travar a aba)
            if do_fetch or do_fill:
                try:
                    # Prioriza LIVE, depois SCHEDULE (cacheado)
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
                        events,
                        league_name=league_sel,
                        team1=team1_sel,
                        team2=team2_sel,
                        start_time_iso=start_time_sel,
                    )

                    if not cand:
                        st.warning("Não consegui identificar essa partida no LoL Esports (schedule/live).")
                    else:
                        st.success(f"Match encontrado no LoL Esports: id={cand.match_id} (score {cand.score:.2f})")
                        details = _ls_get_event_details(cand.match_id)
                        game_ids, sides = ls_draft.extract_game_ids_by_map(details)

                        game_id = game_ids.get(int(map_choice))
                        if not game_id:
                            st.info(f"Sem `gameId` disponível para Map {map_choice} ainda.")
                        else:
                            window = _ls_get_window(game_id)
                            draft = ls_draft.extract_draft_from_window(window)

                            # Decide se Team 1 é blue/red nesse mapa
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
                                st.warning(
                                    "Não consegui mapear automaticamente quem está BLUE/RED nesse mapa. "
                                    "Vou assumir uma opção manual abaixo."
                                )
                                team1_side = st.radio(
                                    "No Map selecionado, o Time 1 é:",
                                    ["BLUE side", "RED side"],
                                    horizontal=True,
                                    key="ls_team1_side_choice",
                                )
                                team1_is_blue = team1_side == "BLUE side"
                            else:
                                st.caption(f"Detectado: Time 1 está no {'BLUE' if team1_is_blue else 'RED'} side.")

                            if team1_is_blue:
                                t1_draft = draft.get("blue", {})
                                t2_draft = draft.get("red", {})
                            else:
                                t1_draft = draft.get("red", {})
                                t2_draft = draft.get("blue", {})

                            # Preview
                            df_preview = pd.DataFrame(
                                [
                                    {"Role": "TOP", "Time 1": t1_draft.get("top", ""), "Time 2": t2_draft.get("top", "")},
                                    {"Role": "JUNG", "Time 1": t1_draft.get("jung", ""), "Time 2": t2_draft.get("jung", "")},
                                    {"Role": "MID", "Time 1": t1_draft.get("mid", ""), "Time 2": t2_draft.get("mid", "")},
                                    {"Role": "ADC", "Time 1": t1_draft.get("adc", ""), "Time 2": t2_draft.get("adc", "")},
                                    {"Role": "SUP", "Time 1": t1_draft.get("sup", ""), "Time 2": t2_draft.get("sup", "")},
                                ]
                            )
                            st.markdown("**Preview do draft (IDs vindos do LoL Esports)**")
                            st.dataframe(df_preview, width="stretch", hide_index=True)

                            if do_fill:
                                # Preenche selectboxes (precisa casar com `empty`)
                                opts = empty  # [""] + champs
                                st.session_state["top_t1"] = _match_champ_to_options(t1_draft.get("top", ""), opts)
                                st.session_state["jung_t1"] = _match_champ_to_options(t1_draft.get("jung", ""), opts)
                                st.session_state["mid_t1"] = _match_champ_to_options(t1_draft.get("mid", ""), opts)
                                st.session_state["adc_t1"] = _match_champ_to_options(t1_draft.get("adc", ""), opts)
                                st.session_state["sup_t1"] = _match_champ_to_options(t1_draft.get("sup", ""), opts)

                                st.session_state["top_t2"] = _match_champ_to_options(t2_draft.get("top", ""), opts)
                                st.session_state["jung_t2"] = _match_champ_to_options(t2_draft.get("jung", ""), opts)
                                st.session_state["mid_t2"] = _match_champ_to_options(t2_draft.get("mid", ""), opts)
                                st.session_state["adc_t2"] = _match_champ_to_options(t2_draft.get("adc", ""), opts)
                                st.session_state["sup_t2"] = _match_champ_to_options(t2_draft.get("sup", ""), opts)

                                st.success("Campeões preenchidos no formulário. (Se algum veio vazio, é porque não achei match no histórico.)")
                                st.rerun()

                except Exception as e:
                    st.warning(f"Falha ao consultar LoL Esports/draft ao vivo: {e}")

    st.markdown("**Campeões**")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("*Time 1*")
        top_t1 = st.selectbox("Top T1", empty, key="top_t1")
        jung_t1 = st.selectbox("Jungle T1", empty, key="jung_t1")
        mid_t1 = st.selectbox("Mid T1", empty, key="mid_t1")
        adc_t1 = st.selectbox("ADC T1", empty, key="adc_t1")
        sup_t1 = st.selectbox("Sup T1", empty, key="sup_t1")
    with c2:
        st.markdown("*Time 2*")
        top_t2 = st.selectbox("Top T2", empty, key="top_t2")
        jung_t2 = st.selectbox("Jungle T2", empty, key="jung_t2")
        mid_t2 = st.selectbox("Mid T2", empty, key="mid_t2")
        adc_t2 = st.selectbox("ADC T2", empty, key="adc_t2")
        sup_t2 = st.selectbox("Sup T2", empty, key="sup_t2")

    # Mapa das apostas: evita duplicatas (empírico retorna Map 1 e Map 2); associa ao draft que você preencheu
    mapa_sel = None
    if matchup_id_sel is not None:
        mapa_sel = st.selectbox(
            "Mapa das apostas (para salvar no banco)",
            [1, 2],
            format_func=lambda x: f"Map {x}",
            key="draft_ml_mapa_sel",
            help="Associe as apostas ao mapa do draft que você preencheu (evita duplicatas Map 1/Map 2).",
        )

    run_ml = st.button("Rodar modelo (empírico + ML)")
    results = []
    value_bets = []
    draft_data = {}

    if run_ml:
        if not league_sel or not team1_sel or not team2_sel:
            st.warning("Selecione liga e times.")
        elif not all([top_t1, jung_t1, mid_t1, adc_t1, sup_t1, top_t2, jung_t2, mid_t2, adc_t2, sup_t2]):
            st.warning("Preencha todos os 10 campeões.")
        else:
            # Normalizar liga para ML (normalizer do odds_analysis)
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

            # Normaliza nomes dos campeões (remove espaços extras, garante formato consistente)
            def normalize_champ_name(champ):
                if not champ or champ == "":
                    return ""
                return ' '.join(str(champ).strip().split())
            
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
            
            # Debug: mostra nomes que estão sendo enviados (apenas se houver problema)
            if st.checkbox("🔍 Mostrar dados enviados ao modelo", key="debug_ml_data"):
                st.json({
                    "league": league_norm,
                    "champions": {
                        "t1": {
                            "top": draft_data["top_t1"],
                            "jung": draft_data["jung_t1"],
                            "mid": draft_data["mid_t1"],
                            "adc": draft_data["adc_t1"],
                            "sup": draft_data["sup_t1"],
                        },
                        "t2": {
                            "top": draft_data["top_t2"],
                            "jung": draft_data["jung_t2"],
                            "mid": draft_data["mid_t2"],
                            "adc": draft_data["adc_t2"],
                            "sup": draft_data["sup_t2"],
                        }
                    }
                })

            # Empírico: só se temos matchup (jogo do dia)
            value_bets = []
            emp_stats = None
            emp_markets_rows = []
            if matchup_id_sel is not None:
                with st.spinner("Rodando análise empírica..."):
                    emp = _run_empirical(matchup_id_sel)
                if emp and not emp.get("error"):
                    # Stats do empírico
                    emp_stats = {
                        "total_markets": len(emp.get("markets", [])),
                        "value_bets_count": 0,
                        "avg_ev": 0,
                        "avg_edge": 0,
                    }
                    
                    markets = emp.get("markets") or []
                    evs = []
                    edges = []
                    for m in markets:
                        if m.get("error"):
                            continue
                        ad = m.get("analysis") or {}

                        mk = m.get("market") or {}
                        mapa_val = mk.get("mapa")
                        mapa_display = f"Map {mapa_val}" if mapa_val is not None else ""
                        odd = mk.get("odd_decimal")
                        implied_prob = (1.0 / float(odd)) if odd else None
                        emp_prob = ad.get("empirical_prob")
                        ev = ad.get("expected_value", 0)
                        edge = ad.get("edge", 0)
                        emp_markets_rows.append({
                            "Mapa": mapa_display,
                            "Side": (mk.get("side") or "").upper(),
                            "Linha": mk.get("line_value"),
                            "Odd": round(float(odd), 2) if odd else None,
                            "Prob. implícita": implied_prob,
                            "Prob. empírica": emp_prob,
                            "EV%": ev * 100 if ev is not None else None,
                            "Edge%": edge if edge is not None else None,
                            "Valor?": bool(ad.get("value")),
                        })

                        if not ad.get("value"):
                            continue
                        if ad.get("empirical_prob") is None:
                            continue
                        emp_stats["value_bets_count"] += 1
                        if ev:
                            evs.append(ev)
                        if edge:
                            edges.append(edge)
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
                    if evs:
                        emp_stats["avg_ev"] = sum(evs) / len(evs)
                    if edges:
                        emp_stats["avg_edge"] = sum(edges) / len(edges)
                elif emp and emp.get("error"):
                    st.warning(f"Empírico: {emp['error']}")
            else:
                st.info("Modo manual: sem matchup. Apenas predição ML por linha.")

            # Regra do app: só consideramos empírico se existir alguma bet EV >= EV_MIN_APP
            value_bets_ev = [
                vb for vb in value_bets
                if vb.get("expected_value") is not None and float(vb.get("expected_value") or 0.0) >= EV_MIN_APP
            ]

            # ML por LINHA (não precisa duplicar por over/under: já temos P(OVER)/P(UNDER))
            lines_to_check = [vb["line_value"] for vb in value_bets_ev]

            def _round_to_step(x: float, step: float = 0.5) -> float:
                # Ex: 31.0888 -> 31.0 ; 30.26 -> 30.5
                return round(float(x) / step) * step

            if not lines_to_check and league_norm:
                # Manual: usar média da liga como linha exemplo
                try:
                    analyzer = _get_analyzer()
                    ls = (analyzer.ml_league_stats or {}).get(league_norm, {})
                    mean_val = ls.get("mean")
                    if mean_val is not None:
                        mean_line = _round_to_step(float(mean_val), 0.5)
                        lines_to_check = [mean_line]
                except Exception:
                    lines_to_check = [25.5]

            results = []
            ml_stats = {"total": 0, "predictions": [], "probabilities": []}
            ml_by_line = {}
            # Remove duplicatas mantendo apenas uma entrada por line_val
            seen = set()
            for line_val in lines_to_check:
                if line_val is None:
                    continue
                key = float(line_val)
                if key in seen:
                    continue
                seen.add(key)
                
                ml_res = _run_ml_with_draft(draft_data, float(line_val))
                
                # Se ML retornou None, mostra aviso
                if ml_res is None:
                    st.warning(f"⚠️ Modelo ML não retornou resultado para linha {line_val}. Verifique logs para detalhes.")
                
                ml_pred = (ml_res.get("prediction") or "").upper() if ml_res else ""
                ml_prob_over = ml_res.get("probability_over") if ml_res else None
                ml_prob_under = ml_res.get("probability_under") if ml_res else None
                ml_prediction = ml_res.get("prediction") if ml_res else None
                
                # Stats do ML
                ml_stats["total"] += 1
                if ml_prediction:
                    ml_stats["predictions"].append(ml_prediction)
                if ml_prob_over is not None:
                    ml_stats["probabilities"].append(ml_prob_over)

                ml_by_line[float(line_val)] = {
                    "ml_pred": ml_pred,
                    "ml_prob_over": ml_prob_over,
                    "ml_prob_under": ml_prob_under,
                }

            # Projeta ML por linha de volta para cada bet empírica EV+ (convergência = side bate com ML pred)
            for vb in value_bets_ev:
                line_val = vb.get("line_value")
                if line_val is None:
                    continue
                line_key = float(line_val)
                ml_info = ml_by_line.get(line_key, {})
                side = vb.get("side")
                empirical_side = (side or "").upper()
                ml_pred = (ml_info.get("ml_pred") or "").upper()
                converges = bool(ml_pred) and (ml_pred == empirical_side)

                results.append({
                    "line": line_val,
                    "side": side,
                    "ml_pred": ml_pred,
                    "ml_prob_over": ml_info.get("ml_prob_over"),
                    "ml_prob_under": ml_info.get("ml_prob_under"),
                    "converges": converges,
                    "odd": vb.get("odd_decimal"),
                    "ev": vb.get("expected_value"),
                    "emp_prob": vb.get("empirical_prob"),
                    "implied_prob": vb.get("implied_prob"),
                })

            # Exibe estatísticas
            if matchup_id_sel is not None:
                if value_bets_ev:
                    st.subheader(f"📊 Empírico (somente EV ≥ {EV_MIN_APP*100:.0f}%)")
                    df_emp_ev = pd.DataFrame([
                        {
                            "Side": str(vb.get("side") or "").upper(),
                            "Linha": vb.get("line_value"),
                            "Odd": vb.get("odd_decimal"),
                            "Prob. empírica": vb.get("empirical_prob"),
                            "EV%": (float(vb.get("expected_value") or 0.0) * 100),
                        }
                        for vb in value_bets_ev
                    ])
                    for col in ["Linha", "Odd", "Prob. empírica", "EV%"]:
                        if col in df_emp_ev.columns:
                            df_emp_ev[col] = pd.to_numeric(df_emp_ev[col], errors="coerce")
                    df_emp_ev = df_emp_ev.sort_values(by=["EV%"], ascending=False, na_position="last")
                    st.dataframe(
                        df_emp_ev,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Linha": st.column_config.NumberColumn("Linha", format="%.1f"),
                            "Odd": st.column_config.NumberColumn("Odd", format="%.2f"),
                            "Prob. empírica": st.column_config.NumberColumn("Prob. empírica", format="%.3f"),
                            "EV%": st.column_config.NumberColumn("EV%", format="%.1f"),
                        },
                    )
                else:
                    st.info(f"Empírico: nenhuma aposta com **EV ≥ {EV_MIN_APP*100:.0f}%** para esse jogo.")
            
            if ml_stats["total"] > 0:
                st.subheader("🤖 Estatísticas ML")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Predições realizadas", ml_stats["total"])
                with col2:
                    # `prediction` vem como 'OVER'/'UNDER' no OddsAnalyzer
                    over_count = sum(1 for p in ml_stats["predictions"] if str(p).upper() == "OVER")
                    under_count = sum(1 for p in ml_stats["predictions"] if str(p).upper() == "UNDER")
                    st.metric("OVER", over_count)
                with col3:
                    st.metric("UNDER", under_count)
                if ml_stats["probabilities"]:
                    avg_prob = sum(ml_stats["probabilities"]) / len(ml_stats["probabilities"])
                    st.caption(f"Probabilidade média OVER: {avg_prob*100:.1f}%")

                # Detalhamento do que o ML disse para cada linha
                if ml_by_line:
                    df_ml = pd.DataFrame([
                        {
                            "Linha": line,
                            "ML pred": (info.get("ml_pred") or "").upper(),
                            "P(OVER)": info.get("ml_prob_over"),
                            "P(UNDER)": info.get("ml_prob_under"),
                        }
                        for line, info in ml_by_line.items()
                    ])
                    for col in ["Linha", "P(OVER)", "P(UNDER)"]:
                        if col in df_ml.columns:
                            df_ml[col] = pd.to_numeric(df_ml[col], errors="coerce")
                    df_ml = df_ml.sort_values(by=["Linha"], na_position="last")

                    st.markdown("**📋 Predições por linha (ML)**")
                    st.dataframe(
                        df_ml,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "P(OVER)": st.column_config.NumberColumn("P(OVER)", format="%.3f"),
                            "P(UNDER)": st.column_config.NumberColumn("P(UNDER)", format="%.3f"),
                        },
                    )
            
            # Stats da combinação (método ML)
            if results:
                eligible_results = [
                    r for r in results
                    if r.get("ev") is not None and float(r.get("ev") or 0.0) >= EV_MIN_APP
                ]
                converged = [r for r in eligible_results if bool(r.get("converges"))]

                if eligible_results:
                    st.subheader(f"🔄 Convergência (apenas EV ≥ {EV_MIN_APP*100:.0f}%)")
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.metric(f"EV{int(EV_MIN_APP*100)}+ (total)", len(eligible_results))
                    with c2:
                        st.metric("✅ Convergiu", len(converged))
                    with c3:
                        rate = (len(converged) / len(eligible_results) * 100) if eligible_results else 0.0
                        st.metric("Taxa", f"{rate:.1f}%")

                    if converged:
                        df_conv = pd.DataFrame([
                            {
                                "Side (empírico)": str(r.get("side") or "").upper(),
                                "Linha": r.get("line"),
                                "Odd": r.get("odd"),
                                "EV empírico%": (r.get("ev") * 100) if r.get("ev") is not None else None,
                                "ML pred": r.get("ml_pred"),
                                "P(OVER)": r.get("ml_prob_over"),
                                "P(UNDER)": r.get("ml_prob_under"),
                            }
                            for r in converged
                        ])
                        for col in ["Linha", "Odd", "EV empírico%", "P(OVER)", "P(UNDER)"]:
                            if col in df_conv.columns:
                                df_conv[col] = pd.to_numeric(df_conv[col], errors="coerce")
                        df_conv = df_conv.sort_values(by=["EV empírico%", "Linha"], ascending=[False, True], na_position="last")
                        st.markdown("**✅ Convergiram (empírico e ML na mesma direção)**")
                        st.dataframe(
                            df_conv,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "Linha": st.column_config.NumberColumn("Linha", format="%.1f"),
                                "Odd": st.column_config.NumberColumn("Odd", format="%.2f"),
                                "EV empírico%": st.column_config.NumberColumn("EV empírico%", format="%.1f"),
                                "P(OVER)": st.column_config.NumberColumn("P(OVER)", format="%.3f"),
                                "P(UNDER)": st.column_config.NumberColumn("P(UNDER)", format="%.3f"),
                            },
                        )
                    else:
                        st.warning(f"Nenhuma aposta **EV{int(EV_MIN_APP*100)}%+** convergiu com o ML (mesma direção OVER/UNDER).")

                    # Debug opcional (pra não poluir)
                    with st.expander(f"Ver EV{int(EV_MIN_APP*100)}%+ que divergiram (debug)", expanded=False):
                        diverged = [r for r in eligible_results if not bool(r.get("converges"))]
                        if not diverged:
                            st.caption("Nada aqui.")
                        else:
                            df_div = pd.DataFrame([
                                {
                                    "Side (empírico)": str(r.get("side") or "").upper(),
                                    "Linha": r.get("line"),
                                    "Odd": r.get("odd"),
                                    "EV empírico%": (r.get("ev") * 100) if r.get("ev") is not None else None,
                                    "ML pred": r.get("ml_pred"),
                                    "P(OVER)": r.get("ml_prob_over"),
                                    "P(UNDER)": r.get("ml_prob_under"),
                                }
                                for r in diverged
                            ])
                            for col in ["Linha", "Odd", "EV empírico%", "P(OVER)", "P(UNDER)"]:
                                if col in df_div.columns:
                                    df_div[col] = pd.to_numeric(df_div[col], errors="coerce")
                            df_div = df_div.sort_values(by=["EV empírico%", "Linha"], ascending=[False, True], na_position="last")
                            st.dataframe(
                                df_div,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "Linha": st.column_config.NumberColumn("Linha", format="%.1f"),
                                    "Odd": st.column_config.NumberColumn("Odd", format="%.2f"),
                                    "EV empírico%": st.column_config.NumberColumn("EV empírico%", format="%.1f"),
                                    "P(OVER)": st.column_config.NumberColumn("P(OVER)", format="%.3f"),
                                    "P(UNDER)": st.column_config.NumberColumn("P(UNDER)", format="%.3f"),
                                },
                            )


    # Bloco de apostas boas: roda sempre (não só quando run_ml), para após clicar em ✓ o rerun
    # reexibir a tabela e processar o clique (results/value_bets já inicializados acima).
    if results and value_bets and matchup_id_sel is not None:
        good_bet_rows = _draft_ml_build_bet_rows(
            results, value_bets, matchup_id_sel, start_time_sel,
            league_sel, team1_sel, team2_sel, draft_data,
            mapa_sel=mapa_sel,
        )
        if good_bet_rows:
            st.session_state["draft_ml_bet_rows"] = list(good_bet_rows)
            st.subheader(f"✅ Apostas boas (EV ≥ {EV_MIN_APP*100:.0f}% e com dados empíricos)")
            st.caption("Use o botão ✓ ao lado de cada aposta para marcar como feita (igual à aba Apostas Hoje).")
            _render_draft_ml_bets_table(good_bet_rows)
        else:
            st.session_state["draft_ml_bet_rows"] = []
            st.info(f"Nenhuma aposta com EV ≥ {EV_MIN_APP*100:.0f}% e dados empíricos encontrados.")
    elif st.session_state.get("draft_ml_bet_rows"):
        good_bet_rows = st.session_state["draft_ml_bet_rows"]
        st.subheader(f"✅ Apostas boas (EV ≥ {EV_MIN_APP*100:.0f}% e com dados empíricos)")
        st.caption("Use o botão ✓ ao lado de cada aposta para marcar como feita (igual à aba Apostas Hoje).")
        _render_draft_ml_bets_table(good_bet_rows)
    elif results:
        st.warning("Selecione um jogo do dia e rode o modelo para ver apostas e marcar como feitas.")
    else:
        st.warning("Nenhuma aposta com valor empírico e/ou sem linhas para ML.")


# ----- Tab 5: Estatísticas resolvidas EV15+ -----
elif chosen == TAB_ESTATISTICAS:
    st.subheader("📊 Apostas resolvidas (won/lost) com EV ≥ 15%")
    st.caption("Métricas para guiar futuras apostas. Fonte: apostas já resolvidas no banco do modelo ou do usuário.")

    db_stats = st.radio(
        "Fonte",
        ["bets.db (modelo)", "user_bets.db (usuário)"],
        horizontal=True,
        key="stats_db_source",
    )
    db_path = BETS_DB if "modelo" in db_stats else USER_BETS_DB
    if not db_path.exists():
        st.warning(f"Banco não encontrado: {db_path}")
    else:
        bets = fetch_resolved_ev15(db_path)
        df = build_df(bets)

        if df.empty:
            st.info("Nenhuma aposta resolvida (won/lost) com EV ≥ 15% nesta base.")
        else:
            # -------------------------------------------------------------------
            # Resumo por cenário (Top N por jogo+mapa)
            # -------------------------------------------------------------------
            st.markdown("**Resumo por cenário (Top N por jogo+mapa)**")
            st.caption("Objetivo: reduzir duplicatas no mesmo mapa e ver performance quando você escolhe só 1/2/3 apostas por mapa.")

            def _pick_top_n_per_game_map(_df: pd.DataFrame, *, n: int, by: str) -> pd.DataFrame:
                """
                Seleciona top-N por (matchup_id, mapa_label) ordenando por:
                  - by='odd_decimal' (maior odd)
                  - by='expected_value' (maior EV)
                """
                if _df.empty:
                    return _df
                if "matchup_id" not in _df.columns or "mapa_label" not in _df.columns:
                    return _df.iloc[0:0].copy()
                if by not in _df.columns:
                    return _df.iloc[0:0].copy()

                work = _df.copy()
                work["odd_decimal"] = pd.to_numeric(work["odd_decimal"], errors="coerce")
                work["expected_value"] = pd.to_numeric(work["expected_value"], errors="coerce")

                # desempates consistentes
                if by == "odd_decimal":
                    sort_cols = ["odd_decimal", "expected_value"]
                else:
                    sort_cols = ["expected_value", "odd_decimal"]
                work = work.sort_values(by=sort_cols, ascending=[False, False], na_position="last")

                parts = []
                for _, g in work.groupby(["matchup_id", "mapa_label"], dropna=False, sort=False):
                    parts.append(g.head(max(1, int(n))))
                return pd.concat(parts, ignore_index=True) if parts else work.iloc[0:0].copy()

            scenarios = []
            for n_pick in (1, 2, 3):
                df_odd = _pick_top_n_per_game_map(df, n=n_pick, by="odd_decimal")
                s_odd = summary_stats(df_odd)
                scenarios.append({
                    "Cenário": f"Top {n_pick} por Odd (maior odd)",
                    "N": s_odd["n"],
                    "WR%": s_odd["wr"],
                    "Lucro(u)": s_odd["lucro"],
                    "ROI%": s_odd["roi"],
                })

                df_ev = _pick_top_n_per_game_map(df, n=n_pick, by="expected_value")
                s_ev = summary_stats(df_ev)
                scenarios.append({
                    "Cenário": f"Top {n_pick} por EV (maior EV)",
                    "N": s_ev["n"],
                    "WR%": s_ev["wr"],
                    "Lucro(u)": s_ev["lucro"],
                    "ROI%": s_ev["roi"],
                })

            df_scen = pd.DataFrame(scenarios)
            st.dataframe(
                df_scen,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "N": st.column_config.NumberColumn("N", format="%d"),
                    "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                    "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                    "ROI%": st.column_config.NumberColumn("ROI%", format="%+.2f"),
                },
            )

            st.divider()

            s = summary_stats(df)

            # Resumo geral
            st.markdown("**Resumo geral**")
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
            with c1:
                st.metric("N", s["n"])
            with c2:
                st.metric("W", s["w"])
            with c3:
                st.metric("L", s["l"])
            with c4:
                st.metric("WR%", f"{s['wr']:.1f}")
            with c5:
                st.metric("Lucro (u)", f"{s['lucro']:+.2f}")
            with c6:
                st.metric("ROI%", f"{s['roi']:+.2f}")
            with c7:
                st.metric("Odd média (W)", f"{s['avg_odd_w']:.2f}" if s["avg_odd_w"] is not None else "—")
            with c8:
                st.metric("Odd média (L)", f"{s['avg_odd_l']:.2f}" if s["avg_odd_l"] is not None else "—")

            # Lucro por janelas (ontem/hoje/semanal/mensal)
            # Usa game_date (data do jogo) como referência.
            if "game_date_day" in df.columns:
                today = datetime.now().date()
                yesterday = today - timedelta(days=1)
                day_s = pd.to_datetime(df["game_date_day"], errors="coerce")

                def _lucro_mask(mask) -> float:
                    sub = df[mask].copy()
                    if sub.empty:
                        return 0.0
                    return float(pd.to_numeric(sub["lucro_u"], errors="coerce").fillna(0).sum())

                lucro_hoje = _lucro_mask(day_s.dt.date == today)
                lucro_ontem = _lucro_mask(day_s.dt.date == yesterday)

                # rolling windows (inclui hoje)
                lucro_7d = _lucro_mask(day_s.dt.date >= (today - timedelta(days=6)))
                lucro_30d = _lucro_mask(day_s.dt.date >= (today - timedelta(days=29)))

                st.markdown("**Lucro por período (u)**")
                l1, l2, l3, l4 = st.columns(4)
                with l1:
                    st.metric("Hoje", f"{lucro_hoje:+.2f}")
                with l2:
                    st.metric("Ontem", f"{lucro_ontem:+.2f}")
                with l3:
                    st.metric("7d", f"{lucro_7d:+.2f}")
                with l4:
                    st.metric("30d", f"{lucro_30d:+.2f}")

            st.divider()

            # Over vs Under
            st.markdown("**Over vs Under**")
            so = agg_stats(df, "side")
            so = so[so["side"].isin(["OVER", "UNDER"])].copy()
            if not so.empty:
                col_t, col_c = st.columns([1, 1])
                with col_t:
                    st.dataframe(
                        so[["side", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "side": st.column_config.TextColumn("Side", width="small"),
                            "N": st.column_config.NumberColumn("N", format="%d"),
                            "W": st.column_config.NumberColumn("W", format="%d"),
                            "L": st.column_config.NumberColumn("L", format="%d"),
                            "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                            "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                            "ROI%": st.column_config.NumberColumn("ROI%", format="%.2f"),
                            "AvgOdd(W)": st.column_config.NumberColumn("AvgOdd(W)", format="%.2f"),
                        },
                    )
                with col_c:
                    chart_ou = so.set_index("side")[["ROI%"]].copy()
                    chart_ou.columns = ["ROI%"]
                    st.bar_chart(chart_ou)

            st.divider()

            # Por liga Empírico: Over | Under (duas tabelas, igual ao ML)
            st.markdown("**Por liga (apenas Empírico) — Over | Under**")
            df_emp = df[df["metodo"] == "Empírico"].copy()
            sl_emp = agg_stats_multi(df_emp, ["league_name", "side"]) if not df_emp.empty else pd.DataFrame()
            sl_emp = sl_emp[(sl_emp["league_name"] != "—") & (sl_emp["side"].isin(["OVER", "UNDER"]))].copy() if not sl_emp.empty else sl_emp
            cfg_liga = {
                "league_name": st.column_config.TextColumn("Liga", width="medium"),
                "N": st.column_config.NumberColumn("N", format="%d"),
                "W": st.column_config.NumberColumn("W", format="%d"),
                "L": st.column_config.NumberColumn("L", format="%d"),
                "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                "ROI%": st.column_config.NumberColumn("ROI%", format="%.2f"),
                "AvgOdd(W)": st.column_config.NumberColumn("AvgOdd(W)", format="%.2f"),
            }
            col_over_emp, col_under_emp = st.columns(2)
            with col_over_emp:
                st.markdown("**Por liga Empírico — OVER**")
                over_emp = sl_emp[sl_emp["side"] == "OVER"].drop(columns=["side"], errors="ignore") if not sl_emp.empty else pd.DataFrame()
                if not over_emp.empty:
                    st.dataframe(over_emp, use_container_width=True, hide_index=True, column_config=cfg_liga)
                else:
                    st.caption("Nenhuma aposta Empírico OVER.")
            with col_under_emp:
                st.markdown("**Por liga Empírico — UNDER**")
                under_emp = sl_emp[sl_emp["side"] == "UNDER"].drop(columns=["side"], errors="ignore") if not sl_emp.empty else pd.DataFrame()
                if not under_emp.empty:
                    st.dataframe(under_emp, use_container_width=True, hide_index=True, column_config=cfg_liga)
                else:
                    st.caption("Nenhuma aposta Empírico UNDER.")

            st.divider()

            # Por liga ML: Over | Under (duas tabelas)
            st.markdown("**Por liga ML (Over | Under)**")
            df_ml = df[df["metodo"] == "ML"].copy()
            sl_ml = agg_stats_multi(df_ml, ["league_name", "side"]) if not df_ml.empty else pd.DataFrame()
            sl_ml = sl_ml[(sl_ml["league_name"] != "—") & (sl_ml["side"].isin(["OVER", "UNDER"]))].copy() if not sl_ml.empty else sl_ml
            col_over, col_under = st.columns(2)
            with col_over:
                st.markdown("**Por liga ML — OVER**")
                over_ml = sl_ml[sl_ml["side"] == "OVER"].drop(columns=["side"], errors="ignore") if not sl_ml.empty else pd.DataFrame()
                if not over_ml.empty:
                    st.dataframe(over_ml, use_container_width=True, hide_index=True, column_config=cfg_liga)
                else:
                    st.caption("Nenhuma aposta ML OVER.")
            with col_under:
                st.markdown("**Por liga ML — UNDER**")
                under_ml = sl_ml[sl_ml["side"] == "UNDER"].drop(columns=["side"], errors="ignore") if not sl_ml.empty else pd.DataFrame()
                if not under_ml.empty:
                    st.dataframe(under_ml, use_container_width=True, hide_index=True, column_config=cfg_liga)
                else:
                    st.caption("Nenhuma aposta ML UNDER.")

            st.divider()

            # Por faixa de odds
            st.markdown("**Por faixa de odds**")
            sb = agg_stats(df, "odds_bucket")
            order = odds_bucket_order()
            sb["_ord"] = sb["odds_bucket"].apply(lambda x: order.index(x) if x in order else 999)
            sb = sb.sort_values("_ord").drop(columns=["_ord"])
            if not sb.empty:
                st.dataframe(
                    sb,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "odds_bucket": st.column_config.TextColumn("Faixa", width="medium"),
                        "N": st.column_config.NumberColumn("N", format="%d"),
                        "W": st.column_config.NumberColumn("W", format="%d"),
                        "L": st.column_config.NumberColumn("L", format="%d"),
                        "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                        "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                        "ROI%": st.column_config.NumberColumn("ROI%", format="%.2f"),
                        "AvgOdd(W)": st.column_config.NumberColumn("AvgOdd(W)", format="%.2f"),
                    },
                )
                chart_odds = sb.set_index("odds_bucket")[["ROI%"]].copy()
                chart_odds.columns = ["ROI%"]
                st.bar_chart(chart_odds)

            st.divider()

            # Por método e por mapa
            col_mtd, col_map = st.columns(2)
            with col_mtd:
                st.markdown("**Por método**")
                sm = agg_stats(df, "metodo")
                if not sm.empty:
                    st.dataframe(
                        sm[["metodo", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "metodo": st.column_config.TextColumn("Método", width="small"),
                            "N": st.column_config.NumberColumn("N", format="%d"),
                            "W": st.column_config.NumberColumn("W", format="%d"),
                            "L": st.column_config.NumberColumn("L", format="%d"),
                            "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                            "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                            "ROI%": st.column_config.NumberColumn("ROI%", format="%.2f"),
                            "AvgOdd(W)": st.column_config.NumberColumn("AvgOdd(W)", format="%.2f"),
                        },
                    )
            with col_map:
                st.markdown("**Por mapa**")
                sp = agg_stats(df, "mapa_label")
                if not sp.empty:
                    st.dataframe(
                        sp[["mapa_label", "N", "W", "L", "WR%", "Lucro(u)", "ROI%", "AvgOdd(W)"]],
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "mapa_label": st.column_config.TextColumn("Mapa", width="small"),
                            "N": st.column_config.NumberColumn("N", format="%d"),
                            "W": st.column_config.NumberColumn("W", format="%d"),
                            "L": st.column_config.NumberColumn("L", format="%d"),
                            "WR%": st.column_config.NumberColumn("WR%", format="%.1f"),
                            "Lucro(u)": st.column_config.NumberColumn("Lucro(u)", format="%+.2f"),
                            "ROI%": st.column_config.NumberColumn("ROI%", format="%.2f"),
                            "AvgOdd(W)": st.column_config.NumberColumn("AvgOdd(W)", format="%.2f"),
                        },
                    )

            st.divider()

            # Outras estatísticas (usa agregação por liga geral para melhor/pior ROI%)
            sl = agg_stats(df, "league_name")
            sl = sl[sl["league_name"] != "—"].copy() if not sl.empty else sl
            st.markdown("**Outras**")
            if not sl.empty and len(sl) >= 2:
                best = sl.loc[sl["ROI%"].idxmax()]
                worst = sl.loc[sl["ROI%"].idxmin()]
                b1, b2, b3 = st.columns(3)
                with b1:
                    st.metric("Melhor liga (ROI%)", f"{best['league_name']}", f"{best['ROI%']:+.2f}%")
                with b2:
                    st.metric("Pior liga (ROI%)", f"{worst['league_name']}", f"{worst['ROI%']:+.2f}%")
                with b3:
                    n_over = int(df[df["side"] == "OVER"].shape[0])
                    n_under = int(df[df["side"] == "UNDER"].shape[0])
                    st.metric("Over vs Under (N)", f"O {n_over} / U {n_under}", None)
            else:
                n_over = int(df[df["side"] == "OVER"].shape[0])
                n_under = int(df[df["side"] == "UNDER"].shape[0])
                st.metric("Over vs Under (N)", f"O {n_over} / U {n_under}", None)
