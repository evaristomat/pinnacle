"""
Configurações para o sistema de rastreamento de apostas
"""
import os
import shutil
from pathlib import Path

# Diretórios
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent

# ── Detecção de Streamlit Cloud ──
# No Cloud, o repo é montado em modo read-only; /tmp/ é gravável.
IS_CLOUD = bool(os.getenv("STREAMLIT_SHARING_MODE")) or Path("/mount/src").exists()

# Bancos de dados (read-only no Cloud, ok)
PINNACLE_DB = PROJECT_ROOT / "pinnacle_data.db"
BETS_DB = BASE_DIR / "bets.db"
HISTORY_CSV = PROJECT_ROOT / "database_improved" / "data_transformed.csv"
HISTORY_DB = PROJECT_ROOT / "database_improved" / "lol_history.db"

# Banco separado para apostas do usuário (Streamlit / apostas reais)
# No Cloud, usa /tmp/ para permitir escrita
if IS_CLOUD:
    _cloud_tmp = Path("/tmp/pinnacle")
    _cloud_tmp.mkdir(parents=True, exist_ok=True)
    USER_BETS_DB = _cloud_tmp / "user_bets.db"
    # Copia bets.db para /tmp/ se precisar de escrita (pipeline)
    if BETS_DB.exists() and not (_cloud_tmp / "bets.db").exists():
        shutil.copy2(BETS_DB, _cloud_tmp / "bets.db")
else:
    USER_BETS_DB = BASE_DIR / "user_bets.db"

# Mapeamento de ligas e times
LIGAS_TIMES_JSON = PROJECT_ROOT / "database_improved" / "ligas_times.json"
if not LIGAS_TIMES_JSON.exists():
    LIGAS_TIMES_JSON = PROJECT_ROOT / "database" / "ligas_times.json"

# Configurações de matching
DATE_TOLERANCE_HOURS = 24  # Tolerância para matching de datas (horas)
MIN_CONFIDENCE_SCORE = 0.7  # Score mínimo para considerar match válido

# Estratégia de seleção por mapa
# Limita apostas por (matchup_id, mapa) para controlar risco/exposição.
# ML: top N por EV (melhor expected value)
# Empírico: top N por odd (melhor payoff)
MAX_BETS_PER_MAP = 3

# Configurações de resultados
RESULT_COLUMNS = {
    'total_kills': 'total_kills',
    'result_t1': 'result_t1',  # 0 = perdeu, 1 = ganhou
    'date': 'date'
}
