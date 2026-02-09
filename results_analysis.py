"""
Análise de resultados — apenas apostas com EV >= 15%.

Imprime Empírico e ML separados (GERAL / OVER / UNDER).
Métricas: N, W, L, WR%, Lucro(u), ROI%, AvgOdd(W). 1u por aposta.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import os
from pathlib import Path
from typing import Any, Iterable

# Mantém o mesmo padrão do app: importa config de bets_tracker via sys.path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "bets_tracker"))
from config import BETS_DB  # noqa: E402

# Apenas EV >= 15%. Override via --ev-min (ex.: 0.20 = 20%).
EV_MIN_DEFAULT = float(os.getenv("PINNACLE_ANALYSIS_EV_MIN", "0.15"))

DEFAULT_POLICY = os.getenv("PINNACLE_ANALYSIS_POLICY", "all")
DEFAULT_MAX_BETS_PER_MATCHUP = int(os.getenv("PINNACLE_ANALYSIS_MAX_BETS_PER_MATCHUP", "0"))
DEFAULT_ODD_MIN = os.getenv("PINNACLE_ANALYSIS_ODD_MIN", "")
DEFAULT_ODD_MAX = os.getenv("PINNACLE_ANALYSIS_ODD_MAX", "")


def _fmt_float(x: float | None, ndigits: int = 2) -> str:
    if x is None:
        return "-"
    try:
        return f"{float(x):.{ndigits}f}"
    except Exception:
        return "-"


def _fmt_int(x: Any) -> str:
    try:
        return str(int(x or 0))
    except Exception:
        return "0"


def _as_float_or_none(s: str | None) -> float | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _fetch_resolved_bets(
    conn: sqlite3.Connection,
    *,
    metodos: Iterable[str] | None,
    side: str | None,
    ev_min: float | None,
    odd_min: float | None,
    odd_max: float | None,
) -> list[dict[str, Any]]:
    """
    Busca bets resolvidas (won/lost) com colunas suficientes para seleção.

    Retorna dicts com:
    - id, matchup_id, mapa, expected_value, odd_decimal, status, side, metodo
    """
    where = ["status IN ('won','lost')"]
    params: list[Any] = []

    if metodos:
        met_list = list(metodos)
        where.append("(" + " OR ".join(["metodo = ?"] * len(met_list)) + ")")
        params.extend(met_list)

    if side:
        where.append("LOWER(side) = ?")
        params.append(side.lower())

    if ev_min is not None:
        where.append("expected_value >= ?")
        params.append(float(ev_min))

    if odd_min is not None:
        where.append("odd_decimal >= ?")
        params.append(float(odd_min))

    if odd_max is not None:
        where.append("odd_decimal <= ?")
        params.append(float(odd_max))

    sql = f"""
        SELECT
            id,
            matchup_id,
            mapa,
            expected_value,
            odd_decimal,
            status,
            side,
            metodo
        FROM bets
        WHERE {' AND '.join(where)}
    """
    cur = conn.cursor()
    cur.execute(sql, params)
    out: list[dict[str, Any]] = []
    for (bid, matchup_id, mapa, ev, odd, status, side_val, metodo) in cur.fetchall():
        out.append(
            {
                "id": int(bid),
                "matchup_id": int(matchup_id),
                "mapa": int(mapa) if mapa is not None else None,
                "expected_value": float(ev or 0.0),
                "odd_decimal": float(odd or 0.0),
                "status": str(status),
                "side": str(side_val or ""),
                "metodo": str(metodo or ""),
            }
        )
    return out


def _pick_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # Maior EV primeiro; empate → menor odd (menos variância); empate → id menor
    return sorted(
        rows,
        key=lambda r: (
            float(r.get("expected_value") or 0.0),
            -float(r.get("odd_decimal") or 0.0),  # maior (-odd) == odd menor
            -int(r.get("id") or 0),  # como sort é reverse=True, id menor deve "ganhar"
        ),
        reverse=True,
    )[0]


def _apply_selection_policy(
    rows: list[dict[str, Any]],
    *,
    policy: str,
    max_bets_per_matchup: int | None,
) -> list[dict[str, Any]]:
    """
    Reduz apostas altamente correlacionadas (mesmo jogo/mapa).

    Policies:
    - all: usa tudo
    - best_per_map: escolhe 1 bet por (matchup_id, mapa) com maior EV
    - best_per_matchup: escolhe 1 bet por matchup_id com maior EV
    """
    pol = str(policy or "all").strip().lower()

    if pol in ("all", "raw"):
        selected = list(rows)
    elif pol in ("best_per_map", "per_map", "map"):
        groups: dict[tuple[int, int | None], list[dict[str, Any]]] = {}
        for r in rows:
            key = (int(r["matchup_id"]), r.get("mapa"))
            groups.setdefault(key, []).append(r)
        selected = [_pick_best(v) for v in groups.values() if v]
    elif pol in ("best_per_matchup", "per_matchup", "matchup"):
        groups2: dict[int, list[dict[str, Any]]] = {}
        for r in rows:
            groups2.setdefault(int(r["matchup_id"]), []).append(r)
        selected = [_pick_best(v) for v in groups2.values() if v]
    else:
        # fallback seguro
        selected = list(rows)

    # Cap adicional por matchup (exposição por série)
    if max_bets_per_matchup is not None and max_bets_per_matchup > 0:
        by_matchup: dict[int, list[dict[str, Any]]] = {}
        for r in selected:
            by_matchup.setdefault(int(r["matchup_id"]), []).append(r)

        capped: list[dict[str, Any]] = []
        for mid, lst in by_matchup.items():
            lst.sort(key=lambda r: float(r.get("expected_value") or 0.0), reverse=True)
            capped.extend(lst[: int(max_bets_per_matchup)])
        selected = capped

    return selected


def _roi_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = 0
    wins = 0
    losses = 0
    lucro = 0.0
    win_odds: list[float] = []

    for r in rows:
        st = str(r.get("status") or "").lower()
        odd = float(r.get("odd_decimal") or 0.0)
        if st not in ("won", "lost"):
            continue
        n += 1
        if st == "won":
            wins += 1
            lucro += (odd - 1.0)
            if odd > 0:
                win_odds.append(odd)
        else:
            losses += 1
            lucro -= 1.0

    avg_win_odd = (sum(win_odds) / len(win_odds)) if win_odds else None
    roi_pct = (lucro / n * 100.0) if n > 0 else 0.0
    win_rate = (wins / n * 100.0) if n > 0 else 0.0

    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win_odd": avg_win_odd,
        "lucro": lucro,
        "roi_pct": roi_pct,
    }


def _status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) FROM bets GROUP BY status")
    return {str(s): int(n or 0) for (s, n) in cur.fetchall()}


def _print_block(
    conn: sqlite3.Connection,
    title: str,
    *,
    metodos: list[str],
    ev_min: float | None,
    policy: str,
    max_bets_per_matchup: int | None,
    odd_min: float | None,
    odd_max: float | None,
):
    print(f"\n{title}")
    print("-" * len(title))
    print(f"{'Side':<8} {'N':>5} {'W':>5} {'L':>5} {'WR%':>7} {'Lucro(u)':>10} {'ROI%':>7} {'AvgOdd(W)':>10}")

    for label, side in [("GERAL", None), ("OVER", "over"), ("UNDER", "under")]:
        rows = _fetch_resolved_bets(
            conn,
            metodos=metodos,
            side=side,
            ev_min=ev_min,
            odd_min=odd_min,
            odd_max=odd_max,
        )
        sel = _apply_selection_policy(rows, policy=policy, max_bets_per_matchup=max_bets_per_matchup)
        r = _roi_from_rows(sel)
        print(
            f"{label:<8} "
            f"{_fmt_int(r['n']):>5} "
            f"{_fmt_int(r['wins']):>5} "
            f"{_fmt_int(r['losses']):>5} "
            f"{_fmt_float(r['win_rate'], 1):>7} "
            f"{_fmt_float(r['lucro'], 2):>10} "
            f"{_fmt_float(r['roi_pct'], 2):>7} "
            f"{_fmt_float(r['avg_win_odd'], 2):>10}"
        )


def results(
    *,
    bets_db: Path | None = None,
    ev_min: float | None = None,
    policy: str = DEFAULT_POLICY,
    max_bets_per_matchup: int | None = DEFAULT_MAX_BETS_PER_MATCHUP,
    odd_min: float | None = _as_float_or_none(DEFAULT_ODD_MIN),
    odd_max: float | None = _as_float_or_none(DEFAULT_ODD_MAX),
):
    """Imprime análise Empírico e ML para apostas com EV >= ev_min."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    db_path = bets_db or BETS_DB
    if not Path(db_path).exists():
        print(f"[ERRO] bets.db não encontrado em: {db_path}")
        return

    ev = float(ev_min if ev_min is not None else EV_MIN_DEFAULT)
    conn = sqlite3.connect(db_path)
    try:
        print(f"DB: {db_path}")
        counts = _status_counts(conn)
        if counts:
            counts_str = ", ".join([f"{k}={v}" for k, v in sorted(counts.items())])
            print(f"Status: {counts_str}")

        pct = int(round(ev * 100))
        print(f"\nApenas apostas com EV >= {pct}%.")
        print("ROI em apostas resolvidas: status IN ('won','lost').")
        pol = str(policy or DEFAULT_POLICY).strip().lower()
        cap_use = max_bets_per_matchup if pol not in ("all", "raw") else None
        print(f"Policy: {pol}" + (f" | cap_per_matchup={cap_use}" if cap_use else ""))
        if odd_min is not None or odd_max is not None:
            print(f"Odd: min={odd_min if odd_min is not None else '-'} max={odd_max if odd_max is not None else '-'}")

        _print_block(
            conn,
            "Método: Empírico",
            metodos=["probabilidade_empirica"],
            ev_min=ev,
            policy=policy,
            max_bets_per_matchup=cap_use,
            odd_min=odd_min,
            odd_max=odd_max,
        )
        _print_block(
            conn,
            "Método: ML",
            metodos=["ml", "machinelearning"],
            ev_min=ev,
            policy=policy,
            max_bets_per_matchup=cap_use,
            odd_min=odd_min,
            odd_max=odd_max,
        )
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Análise de resultados — apenas EV >= 15% (bets_tracker/bets.db)")
    parser.add_argument("--bets-db", type=str, default=None, help="Caminho para o bets.db (opcional)")
    parser.add_argument(
        "--ev-min",
        type=float,
        default=EV_MIN_DEFAULT,
        help=f"EV mínimo em decimal (default {EV_MIN_DEFAULT} = 15%%). Ex: 0.20 = 20%%.",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default=DEFAULT_POLICY,
        help="Seleção: all | best_per_map | best_per_matchup. Default: all.",
    )
    parser.add_argument(
        "--max-bets-per-matchup",
        type=int,
        default=DEFAULT_MAX_BETS_PER_MATCHUP,
        help="Cap de bets por matchup (0 = sem cap). Default: 0.",
    )
    parser.add_argument(
        "--odd-min",
        type=float,
        default=_as_float_or_none(DEFAULT_ODD_MIN),
        help="Odd mínima (opcional).",
    )
    parser.add_argument(
        "--odd-max",
        type=float,
        default=_as_float_or_none(DEFAULT_ODD_MAX),
        help="Odd máxima (opcional).",
    )
    args = parser.parse_args()

    max_bets = int(args.max_bets_per_matchup or 0)
    results(
        bets_db=Path(args.bets_db) if args.bets_db else None,
        ev_min=args.ev_min,
        policy=str(args.policy or DEFAULT_POLICY),
        max_bets_per_matchup=(max_bets if max_bets > 0 else None),
        odd_min=args.odd_min,
        odd_max=args.odd_max,
    )


if __name__ == "__main__":
    main()
