"""
Script 3 - Verifica se apostas em bets_dota.db já têm resultado (pinnacle_to_result)
e atualiza status (won/lost/void).
"""
import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from config import BETS_DOTA_DB, DOTA_RESULTS_DB
from bets_database import get_pending_bets, get_placed_bets, update_bet_result


def _bet_get(bet, key, default=None):
    """Acesso seguro a campo da aposta (dict ou sqlite3.Row)."""
    if hasattr(bet, "get") and callable(getattr(bet, "get")):
        return bet.get(key, default)
    try:
        keys = bet.keys() if hasattr(bet, "keys") else []
        return bet[key] if key in keys else default
    except Exception:
        return default


def determine_bet_result(bet: Dict, total_kills: float) -> Tuple[str, float]:
    """Determina won/lost/void a partir de total_kills e line_value/side."""
    if total_kills is None:
        return ("void", None)
    try:
        total_kills = float(total_kills)
    except Exception:
        return ("void", None)
    line_value = _bet_get(bet, "line_value")
    try:
        line_value = float(line_value) if line_value is not None else None
    except (TypeError, ValueError):
        line_value = None
    side = (_bet_get(bet, "side") or "").upper()
    if line_value is None:
        return ("void", total_kills)
    if side == "OVER":
        if total_kills > line_value:
            return ("won", total_kills)
        if total_kills < line_value:
            return ("lost", total_kills)
        return ("void", total_kills)
    if side == "UNDER":
        if total_kills < line_value:
            return ("won", total_kills)
        if total_kills > line_value:
            return ("lost", total_kills)
        return ("void", total_kills)
    return ("void", total_kills)


def main():
    parser = argparse.ArgumentParser(description="Atualiza resultados das apostas Dota (bets_dota.db)")
    parser.add_argument("--dry-run", action="store_true", help="Nao gravar no banco")
    parser.add_argument("--summary", action="store_true", help="Resumo apenas")
    parser.add_argument("--include-pending", action="store_true", default=True, help="Incluir pending e feita")
    args = parser.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if not BETS_DOTA_DB.exists():
        print("[dota_update_bet_results] bets_dota.db nao encontrado.")
        return 1
    if not DOTA_RESULTS_DB.exists():
        print("[dota_update_bet_results] dota_results.db nao encontrado. Rode os scripts 1 e 2 antes.")
        return 1

    if args.include_pending:
        pending = get_pending_bets(db_path=BETS_DOTA_DB) + get_placed_bets(db_path=BETS_DOTA_DB)
        by_id = {b["id"]: b for b in pending}
        bets = list(by_id.values())
    else:
        bets = get_placed_bets(db_path=BETS_DOTA_DB)

    if not bets:
        print("[dota_update_bet_results] Nenhuma aposta aguardando resultado.")
        return 0

    conn_dota = sqlite3.connect(DOTA_RESULTS_DB)
    conn_dota.row_factory = sqlite3.Row
    cur = conn_dota.cursor()

    updated = 0
    not_found = 0
    for bet in bets:
        bet_id = bet["id"]
        matchup_id = bet["matchup_id"]
        cur.execute("SELECT total_kills FROM pinnacle_to_result WHERE matchup_id = ?", (matchup_id,))
        row = cur.fetchone()
        if not row:
            not_found += 1
            if not args.summary:
                print(f"   [AVISO] Aposta #{bet_id} matchup_id={matchup_id} sem resultado em pinnacle_to_result")
            continue
        total_kills = row["total_kills"]
        status, result_value = determine_bet_result(bet, total_kills)
        if not args.summary:
            suf = " [DRY-RUN]" if args.dry_run else ""
            print(f"   Aposta #{bet_id}: {status.upper()} | total_kills={result_value}{suf}")
        if not args.dry_run:
            update_bet_result(bet_id, result_value, status, db_path=BETS_DOTA_DB)
            updated += 1

    conn_dota.close()
    print(f"\n[dota_update_bet_results] Apostas processadas: {len(bets)} | Atualizadas: {updated} | Sem resultado: {not_found}")
    if not_found == len(bets) and len(bets) > 0:
        print("   (Resultados sao preenchidos por dota_collect_value_bets quando o jogo ja foi realizado e encontrado na OpenDota.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
