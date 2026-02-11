"""Teste rápido: jogos do mês no pinnacle_dota.db x OpenDota API."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BETS_TRACKER = PROJECT_ROOT / "bets_tracker"
PINNACLE_DOTA = PROJECT_ROOT / "pinnacle_dota.db"

# Importa a função de teste do run_dota
sys.path.insert(0, str(PROJECT_ROOT))
from run_dota import test_opendota_jogos_do_mes

if __name__ == "__main__":
    print("Teste OpenDota - jogos deste mês (já realizados) no pinnacle_dota.db\n")
    total, found = test_opendota_jogos_do_mes(PINNACLE_DOTA)
    print(f"Jogos no DB (mês atual, já realizados): {total}")
    print(f"Encontrados na OpenDota API: {found}")
    if total > 0:
        print(f"Taxa: {found}/{total} = {100*found/total:.0f}%")
