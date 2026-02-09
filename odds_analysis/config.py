"""
Configurações para análise de valor nas odds
"""
from pathlib import Path

# Diretórios
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent

# Bancos de dados
PINNACLE_DB = PROJECT_ROOT / "pinnacle_data.db"
HISTORY_DB = PROJECT_ROOT / "database_improved" / "lol_history.db"
HISTORY_CSV = PROJECT_ROOT / "database_improved" / "data_transformed.csv"

# Mapeamento de ligas e times
LIGAS_TIMES_JSON = PROJECT_ROOT / "database_improved" / "ligas_times.json"
# Fallback para pasta original
if not LIGAS_TIMES_JSON.exists():
    LIGAS_TIMES_JSON = PROJECT_ROOT / "database" / "ligas_times.json"

# Configurações de análise
MIN_GAMES_FOR_ANALYSIS = 5  # Mínimo de jogos históricos para considerar análise válida
# Threshold usado pelo odds_analyzer para marcar "value".
# Mantemos baixo (EV>=5%) para guardar volume no banco; os UIs/relatórios filtram com outro EV_MIN.
# EV em decimal: 0.05 = 5%
VALUE_THRESHOLD = 0.05

# Confidence threshold do modelo ML.
# Só faz predição ML se max(prob_over, prob_under) >= threshold.
# 0.65 = sweet-spot entre ROI (+41.9%) e volume (71% das apostas).
ML_CONFIDENCE_THRESHOLD = 0.65

# Match Pinnacle <-> histórico (fontes diferentes, sem ID em comum)
# "Finalizado" = jogo existe no histórico. Match por liga + times + data ± N dias (horários diferem).
MATCH_DATE_TOLERANCE_DAYS = 1
