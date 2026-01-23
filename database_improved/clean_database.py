"""
Script para processar e limpar dados brutos de jogos de LoL
Transforma dados de formato 'por jogador' para formato 'por matchup'
Versão melhorada com validação, tratamento de erros e otimizações
"""
import pandas as pd
from tqdm import tqdm
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple

from config import (
    DATABASE_CSV,
    TRANSFORMED_CSV,
    LOG_FILE,
    LOG_LEVEL,
    REQUIRED_CSV_COLUMNS
)

# Configurar logging
logging.basicConfig(
    filename=LOG_FILE,
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode='a'
)

logger = logging.getLogger(__name__)

# Cores para output
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
ENDC = "\033[0m"


def log(message: str, level: str = "info"):
    """
    Imprime mensagem colorida e registra no log.
    
    Args:
        message: Mensagem a ser exibida
        level: Nível do log (info, warning, error)
    """
    color = YELLOW if level == "info" else (GREEN if level == "success" else RED)
    print(f"{color}[{message}]{ENDC}")
    
    log_func = getattr(logger, level, logger.info)
    log_func(message)


def validate_dataframe(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
    """
    Valida se o DataFrame tem estrutura esperada.
    
    Args:
        df: DataFrame a validar
        
    Returns:
        Tupla (é_válido, mensagem_erro)
    """
    missing_cols = [col for col in REQUIRED_CSV_COLUMNS if col not in df.columns]
    if missing_cols:
        return False, f"Colunas obrigatórias faltando: {missing_cols}"
    
    if df.empty:
        return False, "DataFrame está vazio"
    
    if 'gameid' not in df.columns or df['gameid'].isna().all():
        return False, "Coluna 'gameid' está vazia ou inválida"
    
    return True, None


def build_champion_dict(df: pd.DataFrame) -> Dict[Tuple[str, int], str]:
    """
    Constrói dicionário mapeando (gameid, participantid) para champion.
    
    Args:
        df: DataFrame com dados brutos
        
    Returns:
        Dicionário com (gameid, participantid) -> champion
    """
    champion_dict = {
        (game_id, participant_id): champion_name
        for game_id, participant_id, champion_name in zip(
            df["gameid"], df["participantid"], df["champion"]
        )
        if pd.notna(champion_name) and pd.notna(game_id) and pd.notna(participant_id)
    }
    
    log(f"Dicionário de champions criado: {len(champion_dict):,} entradas")
    return champion_dict


def get_champion_optimized(
    row: pd.Series, 
    role: int, 
    champion_dict: Dict[Tuple[str, int], str]
) -> Optional[str]:
    """
    Recupera champion baseado em role e participant ID.
    
    Args:
        row: Linha do DataFrame
        role: Índice da role (0=top, 1=jung, 2=mid, 3=adc, 4=sup)
        champion_dict: Dicionário de champions
        
    Returns:
        Nome do champion ou None
    """
    try:
        # Determina participant ID base baseado no time
        base_participant_id = 1 if row["participantid"] == 100 else 6
        
        # Calcula participant ID específico para a role
        specific_participant_id = base_participant_id + role
        
        # Busca champion usando game ID e participant ID
        champion = champion_dict.get((row["gameid"], specific_participant_id))
        
        return champion
    except Exception as e:
        logger.warning(f"Erro ao buscar champion: {e}")
        return None


def get_league_matchups_global(
    df: pd.DataFrame, 
    league_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Processa DataFrame para gerar matchups de ligas baseado em participant IDs.
    
    Args:
        df: DataFrame de entrada com dados brutos
        league_name: Nome da liga para filtrar (opcional)
        
    Returns:
        DataFrame com matchups processados (uma linha por partida)
    """
    log("Iniciando processamento de matchups...")
    
    # Validação inicial
    is_valid, error_msg = validate_dataframe(df)
    if not is_valid:
        raise ValueError(f"DataFrame inválido: {error_msg}")
    
    # Filtra por liga se especificado
    if league_name:
        df = df[df.league == league_name].copy()
        log(f"Filtrado para liga: {league_name} ({len(df):,} linhas)")
    
    # Filtra dados para manter apenas participant IDs 100 e 200 (times)
    league_compositions = df[df.participantid.isin([100, 200])].copy()
    log(f"Linhas com participant IDs 100/200: {len(league_compositions):,}")
    
    if league_compositions.empty:
        raise ValueError("Nenhum dado encontrado com participant IDs 100 ou 200")
    
    # Constrói mapeamento de champions
    champion_mapping = build_champion_dict(df)
    
    # Atribui champions para respectivas roles
    roles = ["top", "jung", "mid", "adc", "sup"]
    log("Atribuindo champions às roles...")
    
    for idx, role in enumerate(roles):
        league_compositions[role] = league_compositions.apply(
            lambda row: get_champion_optimized(row, idx, champion_mapping), 
            axis=1
        )
    
    # Separa composições baseado em participant IDs e faz merge
    league_100_compositions = league_compositions[
        league_compositions["participantid"] == 100
    ].copy()
    
    league_200_compositions = league_compositions[
        league_compositions["participantid"] == 200
    ].copy()
    
    log(f"Time 100: {len(league_100_compositions):,} linhas")
    log(f"Time 200: {len(league_200_compositions):,} linhas")
    
    merged_leagues = league_100_compositions.merge(
        league_200_compositions, 
        how="left", 
        on="gameid",
        suffixes=("_x", "_y")
    )
    
    log(f"Matchups mesclados: {len(merged_leagues):,}")
    
    # Renomeia colunas
    renamed_columns = {
        "league_x": "league",
        "year_x": "year",
        "date_x": "date",
        "game_x": "game",
        "patch_x": "patch",
        "side_x": "side",
        "teamname_x": "t1",
        "teamname_y": "t2",
        "result_x": "result_t1",
        "gamelength_x": "gamelength",
        "top_x": "top_t1",
        "jung_x": "jung_t1",
        "mid_x": "mid_t1",
        "adc_x": "adc_t1",
        "sup_x": "sup_t1",
        "kills_x": "kills_t1",
        "firstdragon_x": "firstdragon_t1",
        "dragons_x": "dragons_t1",
        "barons_x": "barons_t1",
        "firstherald_x": "firstherald_t1",
        "firstbaron_x": "firstbaron_t1",
        "firsttower_x": "firsttower_t1",
        "towers_x": "towers_t1",
        "top_y": "top_t2",
        "jung_y": "jung_t2",
        "mid_y": "mid_t2",
        "adc_y": "adc_t2",
        "sup_y": "sup_t2",
        "kills_y": "kills_t2",
        "firstdragon_y": "firstdragon_t2",
        "dragons_y": "dragons_t2",
        "barons_y": "barons_t2",
        "firstherald_y": "firstherald_t2",
        "firstbaron_y": "firstbaron_t2",
        "firsttower_y": "firsttower_t2",
        "towers_y": "towers_t2",
        "inhibitors_x": "inhibitors_t1",
        "inhibitors_y": "inhibitors_t2",
    }
    
    # Filtra e renomeia colunas
    available_cols = [col for col in renamed_columns.keys() if col in merged_leagues.columns]
    final_df = merged_leagues[available_cols].copy()
    final_df = final_df.rename(columns=renamed_columns)
    
    # Converte coluna de data para datetime
    if 'date' in final_df.columns:
        try:
            final_df["date"] = pd.to_datetime(final_df["date"], format="%Y-%m-%d %H:%M:%S", errors='coerce')
        except Exception as e:
            logger.warning(f"Erro ao converter data: {e}")
    
    # Converte gamelength para minutos
    if 'gamelength' in final_df.columns:
        try:
            final_df["gamelength"] = pd.to_numeric(final_df["gamelength"], errors='coerce').astype(float) / 60
            final_df["gamelength"] = final_df["gamelength"].round(2)
        except Exception as e:
            logger.warning(f"Erro ao converter gamelength: {e}")
    
    # Calcula totais
    numeric_cols_t1 = ['kills_t1', 'barons_t1', 'towers_t1', 'dragons_t1', 'inhibitors_t1']
    numeric_cols_t2 = ['kills_t2', 'barons_t2', 'towers_t2', 'dragons_t2', 'inhibitors_t2']
    
    if all(col in final_df.columns for col in numeric_cols_t1 + numeric_cols_t2):
        final_df["total_kills"] = (
            pd.to_numeric(final_df["kills_t1"], errors='coerce').fillna(0) +
            pd.to_numeric(final_df["kills_t2"], errors='coerce').fillna(0)
        ).astype(int)
        
        final_df["total_barons"] = (
            pd.to_numeric(final_df["barons_t1"], errors='coerce').fillna(0) +
            pd.to_numeric(final_df["barons_t2"], errors='coerce').fillna(0)
        ).astype(int)
        
        final_df["total_towers"] = (
            pd.to_numeric(final_df["towers_t1"], errors='coerce').fillna(0) +
            pd.to_numeric(final_df["towers_t2"], errors='coerce').fillna(0)
        ).astype(int)
        
        final_df["total_dragons"] = (
            pd.to_numeric(final_df["dragons_t1"], errors='coerce').fillna(0) +
            pd.to_numeric(final_df["dragons_t2"], errors='coerce').fillna(0)
        ).astype(int)
        
        final_df["total_inhibitors"] = (
            pd.to_numeric(final_df["inhibitors_t1"], errors='coerce').fillna(0) +
            pd.to_numeric(final_df["inhibitors_t2"], errors='coerce').fillna(0)
        ).astype(int)
    
    log(f"Processamento concluído: {len(final_df):,} matchups gerados", "success")
    return final_df


def process_database() -> bool:
    """
    Processa o arquivo database.csv e gera data_transformed.csv.
    
    Returns:
        True se sucesso, False caso contrário
    """
    log("=" * 60)
    log("Processamento de Dados de LoL")
    log("=" * 60)
    
    # Verifica se arquivo existe
    if not DATABASE_CSV.exists():
        log(f"Arquivo não encontrado: {DATABASE_CSV}", "error")
        return False
    
    file_size = DATABASE_CSV.stat().st_size / 1024 / 1024
    log(f"Lendo arquivo: {DATABASE_CSV.name} ({file_size:.2f} MB)")
    
    try:
        # Lê CSV
        log("Carregando dados...")
        data = pd.read_csv(DATABASE_CSV, low_memory=False)
        total_rows = len(data)
        log(f"Linhas carregadas: {total_rows:,}")
        
        # Processa dados
        log("Processando matchups...")
        with tqdm(total=total_rows, desc="Processando", unit="rows") as pbar:
            transformed_data = get_league_matchups_global(data)
            pbar.update(total_rows)
        
        # Salva resultado
        log(f"Salvando resultado em: {TRANSFORMED_CSV.name}")
        transformed_data.to_csv(TRANSFORMED_CSV, index=False)
        
        output_size = TRANSFORMED_CSV.stat().st_size / 1024 / 1024
        log(f"Arquivo salvo: {output_size:.2f} MB", "success")
        log(f"Shape final: {transformed_data.shape}", "success")
        log(f"Redução: {((1 - output_size/file_size) * 100):.1f}%", "success")
        
        logger.info("Processamento concluído com sucesso")
        return True
        
    except Exception as e:
        log(f"Erro durante processamento: {str(e)}", "error")
        logger.error(f"Erro no processamento: {str(e)}", exc_info=True)
        return False


if __name__ == "__main__":
    success = process_database()
    if not success:
        exit(1)
