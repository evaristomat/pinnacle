"""
Configurações centralizadas para o sistema de processamento de dados LoL
"""
from pathlib import Path

# Diretório base
BASE_DIR = Path(__file__).parent

# Google Drive
GOOGLE_DRIVE_FILE_ID = "1hnpbrUpBMS1TZI7IovfpKeZfWJH1Aptm"
GOOGLE_DRIVE_URL = "https://docs.google.com/uc?export=download"

# Arquivos de dados
DATABASE_CSV = BASE_DIR / "database.csv"
TRANSFORMED_CSV = BASE_DIR / "data_transformed.csv"
LIGAS_JSON = BASE_DIR / "ligas_times.json"

# Banco de dados SQLite
SQLITE_DB = BASE_DIR / "lol_history.db"

# Logging
LOG_FILE = BASE_DIR / "data_processing.log"
LOG_LEVEL = "INFO"

# Configurações de processamento
CHUNK_SIZE = 32768  # Para download
CSV_CHUNK_SIZE = 10000  # Para processamento em chunks (se necessário)

# Colunas obrigatórias no CSV
REQUIRED_CSV_COLUMNS = [
    'gameid',
    'league',
    'participantid',
    'champion',
    'year',
    'date',
    'teamname'
]
