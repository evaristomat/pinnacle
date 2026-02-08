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


def run_command(cmd: list, cwd: Path = None, description: str = None, capture_output: bool = True) -> bool:
    """
    Executa um comando e retorna True se sucesso.
    
    Args:
        cmd: Lista com comando e argumentos
        cwd: Diretório de trabalho
        description: Descrição do comando (opcional)
        capture_output: Se False, output vai direto para terminal (preserva cores)
        
    Returns:
        True se sucesso, False caso contrário
    """
    if description:
        print(f"   Executando: {description}")
    
    try:
        if capture_output:
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
        else:
            # Executa sem capturar output para preservar cores/formatação
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=True,
                encoding='utf-8',
                errors='replace'
            )
            return True
    
    except subprocess.CalledProcessError as e:
        print(f"{RED}   ERRO: {e}{RESET}")
        if capture_output and e.stdout:
            print(f"   Output: {e.stdout}")
        if capture_output and e.stderr:
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
            [sys.executable, "main.py", "--skip-download-if-downloaded-today-after-noon"],
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
        
        # Verifica estatísticas do banco (independente de success)
        import sqlite3
        bets_db = BETS_TRACKER / "bets.db"
        if bets_db.exists():
            try:
                conn = sqlite3.connect(bets_db)
                cursor = conn.cursor()
                
                # Total de apostas
                cursor.execute("SELECT COUNT(*) FROM bets")
                total = cursor.fetchone()[0]
                
                # Por status
                cursor.execute("""
                    SELECT status, COUNT(*) 
                    FROM bets 
                    GROUP BY status
                """)
                by_status = {row[0]: row[1] for row in cursor.fetchall()}
                
                # Por método
                try:
                    cursor.execute("""
                        SELECT metodo, COUNT(*) 
                        FROM bets 
                        GROUP BY metodo
                    """)
                    by_metodo = {row[0]: row[1] for row in cursor.fetchall()}
                except:
                    by_metodo = {}
                
                # ROI básico (apenas resolvidas)
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_resolved,
                        SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
                        SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
                        AVG(CASE WHEN status = 'won' THEN odd_decimal ELSE NULL END) as avg_win_odd,
                        SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
                    FROM bets
                    WHERE status IN ('won', 'lost')
                """)
                roi_row = cursor.fetchone()
                conn.close()
                
                if total > 0:
                    print(f"\n{BOLD}{CYAN}Estatísticas do Banco de Apostas:{RESET}")
                    print(f"   {BOLD}Total de apostas:{RESET} {total}")
                    print(f"   {BOLD}Por status:{RESET} {by_status}")
                    if by_metodo:
                        # Formata métodos
                        metodo_display = {}
                        for metodo, count in by_metodo.items():
                            if metodo == 'probabilidade_empirica':
                                metodo_display['Empírico'] = count
                            elif metodo in ('ml', 'machinelearning'):
                                metodo_display['ML'] = metodo_display.get('ML', 0) + count
                            else:
                                metodo_display[metodo] = count
                        print(f"   {BOLD}Por método:{RESET} {metodo_display}")
                    
                    # ROI se houver apostas resolvidas
                    if roi_row and roi_row[0] and roi_row[0] > 0:
                        total_resolved = roi_row[0]
                        wins = roi_row[1] or 0
                        losses = roi_row[2] or 0
                        avg_win_odd = roi_row[3] or 0
                        lucro = roi_row[4] or 0
                        win_rate = (wins / total_resolved * 100) if total_resolved > 0 else 0
                        roi_pct = (lucro / total_resolved * 100) if total_resolved > 0 else 0
                        
                        print(f"\n{BOLD}{CYAN}ROI:{RESET}")
                        print(f"   Resolvidas: {BOLD}{total_resolved}{RESET}")
                        print(f"   {GREEN}Vitórias:{RESET} {BOLD}{GREEN}{wins}{RESET} ({win_rate:.1f}%)")
                        print(f"   {RED}Derrotas:{RESET} {BOLD}{RED}{losses}{RESET}")
                        if avg_win_odd > 0:
                            print(f"   Odd média (vitórias): {BOLD}{avg_win_odd:.2f}{RESET}")
                        roi_color = GREEN if roi_pct > 0 else RED if roi_pct < 0 else YELLOW
                        profit_color = GREEN if lucro > 0 else RED if lucro < 0 else YELLOW
                        print(f"   {BOLD}Return:{RESET} {BOLD}{roi_color}{roi_pct:+.2f}%{RESET} (lucro/total u apostadas)")
                        print(f"   {BOLD}Lucro:{RESET} {BOLD}{profit_color}{lucro:+.2f} u{RESET}")
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
            # Inclui pending e filtra por idade para evitar resolver jogos que ainda não aconteceram
            [sys.executable, "main.py", "update", "--db", "bets", "--include-pending", "--min-hours", "24", "--summary"],
            cwd=BETS_TRACKER,
            description="Atualizando resultados"
        )
        results['bets_update'] = success
        
        if success:
            print(f"{GREEN}   [OK] Resultados atualizados{RESET}")
            
            # Mostra estatísticas atualizadas após update
            bets_db = BETS_TRACKER / "bets.db"
            if bets_db.exists():
                try:
                    import sqlite3
                    conn = sqlite3.connect(bets_db)
                    cursor = conn.cursor()
                    
                    # ROI atualizado
                    cursor.execute("""
                        SELECT
                            COUNT(*) as total_resolved,
                            SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END) as wins,
                            SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END) as losses,
                            AVG(CASE WHEN status = 'won' THEN odd_decimal ELSE NULL END) as avg_win_odd,
                            SUM(CASE WHEN status = 'won' THEN odd_decimal - 1 ELSE -1 END) as lucro
                        FROM bets
                        WHERE status IN ('won', 'lost')
                    """)
                    roi_row = cursor.fetchone()
                    conn.close()
                    
                    if roi_row and roi_row[0] and roi_row[0] > 0:
                        total_resolved = roi_row[0]
                        wins = roi_row[1] or 0
                        losses = roi_row[2] or 0
                        avg_win_odd = roi_row[3] or 0
                        lucro = roi_row[4] or 0
                        win_rate = (wins / total_resolved * 100) if total_resolved > 0 else 0
                        roi_pct = (lucro / total_resolved * 100) if total_resolved > 0 else 0
                        
                        print(f"\n{BOLD}{CYAN}Estatísticas Atualizadas:{RESET}")
                        print(f"   Resolvidas: {BOLD}{total_resolved}{RESET}")
                        print(f"   {GREEN}Vitórias:{RESET} {BOLD}{GREEN}{wins}{RESET} ({win_rate:.1f}%)")
                        print(f"   {RED}Derrotas:{RESET} {BOLD}{RED}{losses}{RESET}")
                        if avg_win_odd > 0:
                            print(f"   Odd média (vitórias): {BOLD}{avg_win_odd:.2f}{RESET}")
                        roi_color = GREEN if roi_pct > 0 else RED if roi_pct < 0 else YELLOW
                        profit_color = GREEN if lucro > 0 else RED if lucro < 0 else YELLOW
                        print(f"   {BOLD}Return:{RESET} {BOLD}{roi_color}{roi_pct:+.2f}%{RESET}")
                        print(f"   {BOLD}Lucro:{RESET} {BOLD}{profit_color}{lucro:+.2f} u{RESET}")
                except Exception as e:
                    pass  # Ignora erros ao mostrar stats
        else:
            print(f"{YELLOW}   [AVISO] Nenhum resultado atualizado{RESET}")
    
    # Resumo final
    print_header("RESUMO DO PIPELINE")
    
    print(f"{BOLD}Etapas executadas:{RESET}")
    for step, success in results.items():
        status = f"{GREEN}[OK]{RESET}" if success else f"{YELLOW}[AVISO]{RESET}"
        step_name = step.replace('_', ' ').title()
        print(f"   {status} {step_name}")
    
    # Estatísticas do bets_tracker usando results_analysis.py
    if BETS_TRACKER.exists():
        bets_db = BETS_TRACKER / "bets.db"
        if bets_db.exists():
            print(f"\n{BOLD}Estatísticas Detalhadas:{RESET}")
            # Não captura output para preservar cores do Rich
            run_command(
                [sys.executable, "results_analysis.py", "--bets-db", str(bets_db)],
                cwd=BASE_DIR,
                description="Análise detalhada de resultados",
                capture_output=False
            )
        else:
            print(f"\n{YELLOW}   [AVISO] Banco de apostas não encontrado para análise{RESET}")
    
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
