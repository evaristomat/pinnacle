"""
Configurações para o sistema de rastreamento de apostas
"""
from pathlib import Path

# Diretórios
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent

# Bancos de dados
PINNACLE_DB = PROJECT_ROOT / "pinnacle_data.db"
BETS_DB = BASE_DIR / "bets.db"
HISTORY_CSV = PROJECT_ROOT / "database_improved" / "data_transformed.csv"
HISTORY_DB = PROJECT_ROOT / "database_improved" / "lol_history.db"

# Mapeamento de ligas e times
LIGAS_TIMES_JSON = PROJECT_ROOT / "database_improved" / "ligas_times.json"
if not LIGAS_TIMES_JSON.exists():
    LIGAS_TIMES_JSON = PROJECT_ROOT / "database" / "ligas_times.json"

# Configurações de matching
DATE_TOLERANCE_HOURS = 24  # Tolerância para matching de datas (horas)
MIN_CONFIDENCE_SCORE = 0.7  # Score mínimo para considerar match válido

# Configurações de resultados
RESULT_COLUMNS = {
    'total_kills': 'total_kills',
    'result_t1': 'result_t1',  # 0 = perdeu, 1 = ganhou
    'date': 'date'
}
