"""
Script orquestrador que executa todo o pipeline:
1. Atualiza database_improved
2. Coleta odds da Pinnacle
3. Analisa apostas com valor
4. Coleta e salva apostas no bets_tracker
5. Atualiza resultados das apostas
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Cores para output
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_header(text: str):
    """Imprime cabeçalho formatado."""
    print(f"\n{BOLD}{BLUE}{'=' * 70}{RESET}")
    print(f"{BOLD}{CYAN}{text}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 70}{RESET}\n")


def print_step(step_num: int, total: int, description: str):
    """Imprime etapa do pipeline."""
    print(f"\n{BOLD}[ETAPA {step_num}/{total}]{RESET} {YELLOW}{description}{RESET}")
    print("-" * 70)


def run_command(cmd: list, cwd: Path = None, description: str = None) -> bool:
    """
    Executa um comando e retorna True se sucesso.
    
    Args:
        cmd: Lista com comando e argumentos
        cwd: Diretório de trabalho
        description: Descrição do comando (opcional)
        
    Returns:
        True se sucesso, False caso contrário
    """
    if description:
        print(f"   Executando: {description}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        if result.stdout:
            print(result.stdout)
        
        return True
    
    except subprocess.CalledProcessError as e:
        print(f"{RED}   ERRO: {e}{RESET}")
        if e.stdout:
            print(f"   Output: {e.stdout}")
        if e.stderr:
            print(f"   Erro: {e.stderr}")
        return False
    
    except Exception as e:
        print(f"{RED}   ERRO inesperado: {e}{RESET}")
        return False


def main():
    """Função principal."""
    # Configura encoding para Windows
    if sys.platform == 'win32':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    
    print_header("PIPELINE COMPLETO - Sistema Pinnacle LoL")
    print(f"Iniciado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Diretórios
    BASE_DIR = Path(__file__).parent
    DATABASE_IMPROVED = BASE_DIR / "database_improved"
    ODDS_ANALYSIS = BASE_DIR / "odds_analysis"
    BETS_TRACKER = BASE_DIR / "bets_tracker"
    
    results = {
        'database_improved': False,
        'pinnacle_collect': False,
        'odds_analysis': False,
        'bets_collect': False,
        'bets_update': False
    }
    
    # ETAPA 1: Atualizar database_improved
    print_step(1, 5, "Atualizando dados históricos (database_improved)")
    
    if not DATABASE_IMPROVED.exists():
        print(f"{RED}   ERRO: Pasta database_improved não encontrada!{RESET}")
    else:
        success = run_command(
            [sys.executable, "main.py", "--skip-download"],
            cwd=DATABASE_IMPROVED,
            description="Processando dados históricos"
        )
        results['database_improved'] = success
        
        if success:
            print(f"{GREEN}   [OK] Dados históricos atualizados{RESET}")
        else:
            print(f"{YELLOW}   [AVISO] Falha ao atualizar dados históricos (continuando...){RESET}")
    
    # ETAPA 2: Coletar odds da Pinnacle
    print_step(2, 5, "Coletando odds da Pinnacle")
    
    success = run_command(
        [sys.executable, "main.py"],
        cwd=BASE_DIR,
        description="Buscando dados da API Pinnacle"
    )
    results['pinnacle_collect'] = success
    
    if success:
        print(f"{GREEN}   [OK] Odds da Pinnacle coletadas{RESET}")
    else:
        print(f"{RED}   [ERRO] Falha ao coletar odds da Pinnacle{RESET}")
        print(f"{YELLOW}   Continuando com dados existentes...{RESET}")
    
    # ETAPA 3: Analisar apostas com valor (teste) - OPCIONAL
    # Esta etapa é apenas para visualização, não é obrigatória
    print_step(3, 5, "Analisando apostas com valor (odds_analysis) - OPCIONAL")
    
    if not ODDS_ANALYSIS.exists():
        print(f"{YELLOW}   [AVISO] Pasta odds_analysis não encontrada (pulando...){RESET}")
        results['odds_analysis'] = True  # Não é crítico
    else:
        # Roda teste com LCK Cup para verificar se há apostas (opcional)
        print(f"   [INFO] Esta etapa é opcional - apenas para visualização")
        success = run_command(
            [sys.executable, "test_lckc.py"],
            cwd=ODDS_ANALYSIS,
            description="Testando análise de valor (LCK Cup)"
        )
        results['odds_analysis'] = True  # Sempre True, não é crítico
        
        if success:
            print(f"{GREEN}   [OK] Análise de valor executada{RESET}")
        else:
            print(f"{YELLOW}   [AVISO] Análise de valor teve problemas (não crítico){RESET}")
    
    # ETAPA 4: Coletar apostas com valor no bets_tracker
    print_step(4, 5, "Coletando apostas com valor (bets_tracker)")
    
    if not BETS_TRACKER.exists():
        print(f"{RED}   ERRO: Pasta bets_tracker não encontrada!{RESET}")
    else:
        # Inicializa banco se necessário
        print(f"   Inicializando banco de apostas...")
        run_command(
            [sys.executable, "main.py", "init"],
            cwd=BETS_TRACKER,
            description="Inicializando banco"
        )
        
        # Coleta apostas (sem filtro de liga para pegar todas)
        print(f"   Coletando apostas com valor de todos os jogos...")
        success = run_command(
            [sys.executable, "main.py", "collect"],
            cwd=BETS_TRACKER,
            description="Coletando apostas"
        )
        results['bets_collect'] = success
        
        # Verifica quantas apostas foram salvas (independente de success)
        import sqlite3
        bets_db = BETS_TRACKER / "bets.db"
        if bets_db.exists():
            try:
                conn = sqlite3.connect(bets_db)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM bets")
                total = cursor.fetchone()[0]
                conn.close()
                if total > 0:
                    print(f"{GREEN}   [OK] {total} apostas no banco{RESET}")
                else:
                    print(f"{YELLOW}   [AVISO] Banco criado mas nenhuma aposta foi salva{RESET}")
            except Exception as e:
                print(f"{YELLOW}   [AVISO] Erro ao verificar banco: {e}{RESET}")
        else:
            if success:
                print(f"{GREEN}   [OK] Comando executado{RESET}")
            else:
                print(f"{YELLOW}   [AVISO] Nenhuma aposta coletada ou erro{RESET}")
    
    # ETAPA 5: Atualizar resultados das apostas
    print_step(5, 5, "Atualizando resultados das apostas")
    
    if BETS_TRACKER.exists():
        success = run_command(
            [sys.executable, "main.py", "update"],
            cwd=BETS_TRACKER,
            description="Atualizando resultados"
        )
        results['bets_update'] = success
        
        if success:
            print(f"{GREEN}   [OK] Resultados atualizados{RESET}")
        else:
            print(f"{YELLOW}   [AVISO] Nenhum resultado atualizado{RESET}")
    
    # Resumo final
    print_header("RESUMO DO PIPELINE")
    
    print(f"{BOLD}Etapas executadas:{RESET}")
    for step, success in results.items():
        status = f"{GREEN}[OK]{RESET}" if success else f"{YELLOW}[AVISO]{RESET}"
        step_name = step.replace('_', ' ').title()
        print(f"   {status} {step_name}")
    
    # Estatísticas do bets_tracker
    if BETS_TRACKER.exists():
        print(f"\n{BOLD}Estatísticas do Bets Tracker:{RESET}")
        run_command(
            [sys.executable, "main.py", "stats"],
            cwd=BETS_TRACKER,
            description="Estatísticas"
        )
    
    print(f"\n{BOLD}{GREEN}Pipeline concluído!{RESET}")
    print(f"Finalizado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Pipeline interrompido pelo usuário{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n{RED}ERRO inesperado: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
