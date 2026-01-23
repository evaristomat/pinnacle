"""
Script para baixar o arquivo CSV do histórico de jogos de LoL do Google Drive
Versão melhorada com validação, tratamento de erros e logging
"""
import requests
import logging
from pathlib import Path
from typing import Optional
import hashlib

from config import (
    GOOGLE_DRIVE_FILE_ID,
    GOOGLE_DRIVE_URL,
    DATABASE_CSV,
    CHUNK_SIZE,
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


def get_file_hash(file_path: Path) -> Optional[str]:
    """
    Calcula hash MD5 do arquivo para verificar integridade.
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        Hash MD5 em hexadecimal ou None se arquivo não existir
    """
    if not file_path.exists():
        return None
    
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error(f"Erro ao calcular hash: {e}")
        return None


def _get_confirm_token(response: requests.Response) -> Optional[str]:
    """
    Extrai token de confirmação dos cookies da resposta.
    
    Args:
        response: Resposta HTTP do Google Drive
        
    Returns:
        Token de confirmação ou None
    """
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            return value
    return None


def _save_response_content(
    response: requests.Response, 
    destination: Path, 
    chunk_size: int = CHUNK_SIZE
) -> bool:
    """
    Salva conteúdo da resposta em arquivo usando streaming.
    
    Args:
        response: Resposta HTTP
        destination: Caminho de destino
        chunk_size: Tamanho dos chunks para download
        
    Returns:
        True se sucesso, False caso contrário
    """
    try:
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f"\rDownload: {progress:.1f}% ({downloaded / 1024 / 1024:.2f} MB)", end='', flush=True)
        
        print()  # Nova linha após progresso
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar arquivo: {e}")
        if destination.exists():
            destination.unlink()  # Remove arquivo parcial
        return False


def download_file_from_google_drive(
    file_id: str, 
    destination: Path,
    verify_integrity: bool = True
) -> bool:
    """
    Baixa um arquivo público do Google Drive.
    
    Args:
        file_id: ID do arquivo no Google Drive
        destination: Caminho onde salvar o arquivo
        verify_integrity: Se True, verifica integridade após download
        
    Returns:
        True se download bem-sucedido, False caso contrário
    """
    logger.info(f"Iniciando download do arquivo {file_id}")
    
    # Criar diretório se não existir
    destination.parent.mkdir(parents=True, exist_ok=True)
    
    # Hash antes do download (se arquivo já existe)
    hash_before = get_file_hash(destination) if destination.exists() else None
    
    session = requests.Session()
    
    try:
        # Primeira requisição para obter token de confirmação (se houver)
        print(f"Conectando ao Google Drive...")
        response = session.get(
            GOOGLE_DRIVE_URL, 
            params={"id": file_id}, 
            stream=True,
            timeout=30
        )
        response.raise_for_status()
        
        token = _get_confirm_token(response)
        
        if token:
            # Refaz requisição com o token
            print("Confirmando download...")
            response = session.get(
                GOOGLE_DRIVE_URL,
                params={"id": file_id, "confirm": token},
                stream=True,
                timeout=30
            )
            response.raise_for_status()
        
        # Salva conteúdo
        print(f"Baixando para: {destination}")
        success = _save_response_content(response, destination)
        
        if not success:
            logger.error("Falha ao salvar arquivo")
            return False
        
        # Verifica integridade
        if verify_integrity:
            hash_after = get_file_hash(destination)
            if hash_after and hash_before and hash_after == hash_before:
                print("[AVISO] Arquivo ja estava atualizado (hash identico)")
                logger.info("Arquivo não foi modificado (hash idêntico)")
            elif hash_after:
                file_size = destination.stat().st_size / 1024 / 1024
                print(f"[OK] Download concluido: {file_size:.2f} MB")
                print(f"   Hash: {hash_after[:16]}...")
                logger.info(f"Download concluído: {file_size:.2f} MB, Hash: {hash_after}")
        
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro na requisição: {e}")
        print(f"[ERRO] Erro ao baixar arquivo: {e}")
        if destination.exists():
            destination.unlink()
        return False
    except Exception as e:
        logger.error(f"Erro inesperado: {e}")
        print(f"[ERRO] Erro inesperado: {e}")
        if destination.exists():
            destination.unlink()
        return False


def validate_csv_file(file_path: Path) -> bool:
    """
    Valida se o arquivo CSV tem estrutura esperada.
    
    Args:
        file_path: Caminho do arquivo CSV
        
    Returns:
        True se válido, False caso contrário
    """
    if not file_path.exists():
        print(f"[ERRO] Arquivo nao encontrado: {file_path}")
        return False
    
    try:
        import pandas as pd
        # Lê apenas as primeiras linhas para validar
        df = pd.read_csv(file_path, nrows=10, low_memory=False)
        
        required_columns = ['gameid', 'league', 'participantid', 'champion']
        missing = [col for col in required_columns if col not in df.columns]
        
        if missing:
            print(f"[ERRO] Colunas obrigatorias faltando: {missing}")
            logger.error(f"Colunas faltando: {missing}")
            return False
        
        print(f"[OK] Arquivo CSV valido: {len(df.columns)} colunas encontradas")
        logger.info(f"Validação OK: {len(df.columns)} colunas")
        return True
        
    except Exception as e:
        print(f"[ERRO] Erro ao validar CSV: {e}")
        logger.error(f"Erro na validação: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Download do Histórico de Jogos de LoL")
    print("=" * 60)
    
    from config import GOOGLE_DRIVE_FILE_ID
    
    success = download_file_from_google_drive(
        GOOGLE_DRIVE_FILE_ID,
        DATABASE_CSV,
        verify_integrity=True
    )
    
    if success:
        print("\n[VALIDANDO] Validando arquivo...")
        if validate_csv_file(DATABASE_CSV):
            print(f"\n[OK] Processo concluido com sucesso!")
            print(f"   Arquivo: {DATABASE_CSV}")
        else:
            print(f"\n[AVISO] Download concluido, mas validacao falhou")
    else:
        print(f"\n[ERRO] Falha no download")
        exit(1)
