"""
Pipeline completo para processamento de dados históricos de LoL
Orquestra: download → clean → ligas → database

Uso:
    python main.py                    # Executa pipeline completo
    python main.py --download-only     # Apenas download
    python main.py --clean-only        # Apenas limpeza
    python main.py --ligas-only       # Apenas geração de ligas
    python main.py --database-only    # Apenas atualização do banco
    python main.py --skip-download    # Pula download (usa CSV existente)
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

from config import DATABASE_CSV, TRANSFORMED_CSV, LIGAS_JSON, SQLITE_DB, GOOGLE_DRIVE_FILE_ID
from download import download_file_from_google_drive, validate_csv_file
from clean_database import process_database
from ligas import generate_ligas_times
from database_schema import import_csv_to_database, get_database_stats

# Cores
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
ENDC = "\033[0m"


def print_header():
    """Imprime cabeçalho do pipeline."""
    print("\n" + "=" * 70)
    print(f"{BLUE}Pipeline de Processamento de Dados Históricos de LoL{ENDC}")
    print("=" * 70)
    print(f"Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def print_step(step_num: int, total: int, description: str):
    """Imprime cabeçalho de uma etapa."""
    print(f"\n{BLUE}[ETAPA {step_num}/{total}]{ENDC} {description}")
    print("-" * 70)


def print_summary(results: dict):
    """Imprime resumo final."""
    print("\n" + "=" * 70)
    print(f"{GREEN}[OK] Pipeline Concluido!{ENDC}")
    print("=" * 70)
    
    print(f"\n[RESUMO] Resumo:")
    if results.get('download'):
        size = DATABASE_CSV.stat().st_size / 1024 / 1024 if DATABASE_CSV.exists() else 0
        print(f"   - Download: {size:.2f} MB")
    
    if results.get('clean'):
        if TRANSFORMED_CSV.exists():
            size = TRANSFORMED_CSV.stat().st_size / 1024 / 1024
            with open(TRANSFORMED_CSV, 'r', encoding='utf-8') as f:
                lines = sum(1 for _ in f) - 1  # -1 para header
            print(f"   - Dados limpos: {size:.2f} MB ({lines:,} matchups)")
    
    if results.get('ligas'):
        if LIGAS_JSON.exists():
            import json
            with open(LIGAS_JSON, 'r', encoding='utf-8') as f:
                ligas = json.load(f)
            total_teams = sum(len(times) for times in ligas.values())
            print(f"   - Ligas mapeadas: {len(ligas)} ligas, {total_teams:,} times")
    
    if results.get('database'):
        if SQLITE_DB.exists():
            size = SQLITE_DB.stat().st_size / 1024 / 1024
            stats = get_database_stats()
            if stats:
                print(f"   - Banco de dados: {size:.2f} MB ({stats.get('total_matchups', 0):,} matchups)")
    
    print(f"\n[ARQUIVOS] Arquivos gerados:")
    if DATABASE_CSV.exists():
        print(f"   - {DATABASE_CSV.name}")
    if TRANSFORMED_CSV.exists():
        print(f"   - {TRANSFORMED_CSV.name}")
    if LIGAS_JSON.exists():
        print(f"   - {LIGAS_JSON.name}")
    if SQLITE_DB.exists():
        print(f"   - {SQLITE_DB.name}")
    
    print(f"\n[FINALIZADO] Finalizado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def run_pipeline(
    skip_download: bool = False,
    download_only: bool = False,
    clean_only: bool = False,
    ligas_only: bool = False,
    database_only: bool = False
) -> dict:
    """
    Executa pipeline completo ou etapas específicas.
    
    Args:
        skip_download: Se True, pula etapa de download
        download_only: Se True, executa apenas download
        clean_only: Se True, executa apenas limpeza
        ligas_only: Se True, executa apenas geração de ligas
        database_only: Se True, executa apenas atualização do banco
        
    Returns:
        Dicionário com resultados de cada etapa
    """
    results = {
        'download': False,
        'clean': False,
        'ligas': False,
        'database': False
    }
    
    # ETAPA 1: Download
    if not (clean_only or ligas_only or database_only):
        print_step(1, 4, "Download do CSV do Google Drive")
        
        if skip_download:
            print(f"{YELLOW}[AVISO] Pulando download (usando arquivo existente){ENDC}")
            if DATABASE_CSV.exists():
                if validate_csv_file(DATABASE_CSV):
                    results['download'] = True
                    print(f"{GREEN}[OK] Arquivo existente valido{ENDC}")
                else:
                    print(f"{YELLOW}[AVISO] Arquivo existente invalido, tentando download...{ENDC}")
                    results['download'] = download_file_from_google_drive(
                        GOOGLE_DRIVE_FILE_ID,
                        DATABASE_CSV
                    )
            else:
                print(f"{YELLOW}[AVISO] Arquivo nao encontrado, fazendo download...{ENDC}")
                results['download'] = download_file_from_google_drive(
                    GOOGLE_DRIVE_FILE_ID,
                    DATABASE_CSV
                )
        else:
            results['download'] = download_file_from_google_drive(
                GOOGLE_DRIVE_FILE_ID,
                DATABASE_CSV
            )
        
        if not results['download']:
            print(f"{YELLOW}[ERRO] Falha no download{ENDC}")
            if download_only:
                return results
        
        if download_only:
            return results
    
    # ETAPA 2: Limpeza e Processamento
    if not (download_only or ligas_only or database_only):
        print_step(2, 4, "Processamento e Limpeza de Dados")
        
        if not DATABASE_CSV.exists():
            print(f"{YELLOW}[ERRO] Arquivo database.csv nao encontrado{ENDC}")
            print(f"   Execute primeiro o download ou use --skip-download=false")
            return results
        
        results['clean'] = process_database()
        
        if not results['clean']:
            print(f"{YELLOW}[ERRO] Falha no processamento{ENDC}")
            if clean_only:
                return results
    
    # ETAPA 3: Geração de Ligas
    if not (download_only or clean_only or database_only):
        print_step(3, 4, "Geracao de Mapeamento Liga -> Times")
        
        if not TRANSFORMED_CSV.exists():
            print(f"{YELLOW}[ERRO] Arquivo data_transformed.csv nao encontrado{ENDC}")
            print(f"   Execute primeiro o processamento")
            return results
        
        ligas_result = generate_ligas_times()
        results['ligas'] = bool(ligas_result)
        
        if not results['ligas']:
            print(f"{YELLOW}[ERRO] Falha na geracao de ligas{ENDC}")
    
    # ETAPA 4: Atualização do Banco de Dados
    if not (download_only or clean_only or ligas_only):
        print_step(4, 4, "Atualizacao do Banco de Dados SQLite")
        
        if not TRANSFORMED_CSV.exists():
            print(f"{YELLOW}[ERRO] Arquivo data_transformed.csv nao encontrado{ENDC}")
            print(f"   Execute primeiro o processamento")
            return results
        
        results['database'] = import_csv_to_database()
        
        if not results['database']:
            print(f"{YELLOW}[ERRO] Falha na atualizacao do banco{ENDC}")
        else:
            print(f"{GREEN}[OK] Banco de dados atualizado com sucesso{ENDC}")
    
    if database_only:
        return results
    
    return results


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Pipeline de processamento de dados históricos de LoL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py                    # Pipeline completo
  python main.py --download-only     # Apenas download
  python main.py --clean-only        # Apenas limpeza
  python main.py --ligas-only        # Apenas geração de ligas
  python main.py --database-only     # Apenas atualização do banco
  python main.py --skip-download     # Pula download (usa CSV existente)
        """
    )
    
    parser.add_argument(
        '--download-only',
        action='store_true',
        help='Executa apenas a etapa de download'
    )
    parser.add_argument(
        '--clean-only',
        action='store_true',
        help='Executa apenas a etapa de limpeza'
    )
    parser.add_argument(
        '--ligas-only',
        action='store_true',
        help='Executa apenas a geração de ligas'
    )
    parser.add_argument(
        '--database-only',
        action='store_true',
        help='Executa apenas a atualização do banco de dados'
    )
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Pula download e usa arquivo CSV existente'
    )
    
    args = parser.parse_args()
    
    # Validação de argumentos
    exclusive_args = [args.download_only, args.clean_only, args.ligas_only, args.database_only]
    if sum(exclusive_args) > 1:
        print("[ERRO] Erro: Use apenas uma opcao --*-only por vez")
        parser.print_help()
        sys.exit(1)
    
    print_header()
    
    try:
        results = run_pipeline(
            skip_download=args.skip_download,
            download_only=args.download_only,
            clean_only=args.clean_only,
            ligas_only=args.ligas_only,
            database_only=args.database_only
        )
        
        print_summary(results)
        
        # Verifica se houve falhas
        if not any(results.values()):
            print(f"{YELLOW}[AVISO] Nenhuma etapa foi executada com sucesso{ENDC}")
            sys.exit(1)
        
        # Verifica se todas as etapas necessárias foram bem-sucedidas
        if not args.download_only and not args.clean_only and not args.ligas_only and not args.database_only:
            if not all(results.values()):
                print(f"{YELLOW}[AVISO] Algumas etapas falharam{ENDC}")
                sys.exit(1)
        
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}[AVISO] Pipeline interrompido pelo usuario{ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{YELLOW}[ERRO] Erro inesperado: {e}{ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
