"""
Script para gerar mapeamento de ligas e times
Útil para identificar diferenças na escrita dos nomes entre sites de apostas
Versão melhorada com validação e tratamento de erros
"""
import pandas as pd
import json
import logging
from pathlib import Path
from typing import Dict, Set

from config import (
    TRANSFORMED_CSV,
    LIGAS_JSON,
    LOG_FILE,
    LOG_LEVEL
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
    """Imprime mensagem colorida e registra no log."""
    color = YELLOW if level == "info" else (GREEN if level == "success" else RED)
    print(f"{color}[{message}]{ENDC}")
    
    log_func = getattr(logger, level, logger.info)
    log_func(message)


def generate_ligas_times() -> Dict[str, list]:
    """
    Gera dicionário com liga como chave e lista de times como valor.
    
    Returns:
        Dicionário {liga: [lista de times]}
    """
    log("=" * 60)
    log("Geracao de Mapeamento Liga -> Times")
    log("=" * 60)
    
    # Verifica se arquivo existe
    if not TRANSFORMED_CSV.exists():
        log(f"Arquivo não encontrado: {TRANSFORMED_CSV}", "error")
        log("Execute primeiro o clean_database.py", "error")
        return {}
    
    log(f"Lendo arquivo: {TRANSFORMED_CSV.name}")
    
    try:
        # Carrega DataFrame
        df = pd.read_csv(TRANSFORMED_CSV)
        log(f"Linhas carregadas: {len(df):,}")
        
        # Verifica colunas necessárias
        required_cols = ['league', 't1', 't2']
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            log(f"Colunas faltando: {missing}", "error")
            return {}
        
        # Dicionário com liga como chave e set de times como valor
        ligas_times: Dict[str, Set[str]] = {}
        
        log("Processando times por liga...")
        for _, row in df.iterrows():
            liga = row["league"]
            time1 = row["t1"]
            time2 = row["t2"]
            
            # Ignora valores NaN
            if pd.isna(liga) or pd.isna(time1) or pd.isna(time2):
                continue
            
            if liga not in ligas_times:
                ligas_times[liga] = set()
            
            ligas_times[liga].add(str(time1))
            ligas_times[liga].add(str(time2))
        
        # Converte sets para listas ordenadas
        ligas_times_sorted = {
            liga: sorted(list(times)) 
            for liga, times in ligas_times.items()
        }
        
        log(f"Ligas processadas: {len(ligas_times_sorted)}", "success")
        
        # Conta total de times
        total_teams = sum(len(times) for times in ligas_times_sorted.values())
        log(f"Total de times únicos: {total_teams:,}", "success")
        
        # Exibe no terminal (formato compacto)
        print("\n[RESUMO] Resumo por Liga:")
        print("-" * 60)
        for liga, times in sorted(ligas_times_sorted.items()):
            print(f"{liga:15} -> {len(times):3} times")
        
        # Salva em JSON
        log(f"Salvando em: {LIGAS_JSON.name}")
        with open(LIGAS_JSON, "w", encoding="utf-8") as f:
            json.dump(ligas_times_sorted, f, ensure_ascii=False, indent=2)
        
        file_size = LIGAS_JSON.stat().st_size / 1024
        log(f"Arquivo salvo: {file_size:.2f} KB", "success")
        
        logger.info(f"Geração concluída: {len(ligas_times_sorted)} ligas, {total_teams} times")
        
        return ligas_times_sorted
        
    except FileNotFoundError:
        log(f"Arquivo não encontrado: {TRANSFORMED_CSV}", "error")
        logger.error(f"Arquivo não encontrado: {TRANSFORMED_CSV}")
        return {}
    except Exception as e:
        log(f"Erro durante processamento: {str(e)}", "error")
        logger.error(f"Erro no processamento: {str(e)}", exc_info=True)
        return {}


def get_team_variations(team_name: str, ligas_times: Dict[str, list]) -> Dict[str, list]:
    """
    Busca variações de um nome de time em diferentes ligas.
    Útil para identificar diferenças de escrita.
    
    Args:
        team_name: Nome do time a buscar
        ligas_times: Dicionário de ligas e times
        
    Returns:
        Dicionário {liga: [times similares]}
    """
    variations = {}
    team_lower = team_name.lower()
    
    for liga, times in ligas_times.items():
        matches = [
            t for t in times 
            if team_lower in t.lower() or t.lower() in team_lower
        ]
        if matches:
            variations[liga] = matches
    
    return variations


if __name__ == "__main__":
    result = generate_ligas_times()
    
    if result:
        print("\n[OK] Processo concluido com sucesso!")
        print(f"   Arquivo: {LIGAS_JSON}")
    else:
        print("\n[ERRO] Falha no processamento")
        exit(1)
