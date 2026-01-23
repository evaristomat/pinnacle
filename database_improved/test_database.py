"""
Script de teste para validar o banco de dados
"""
import sqlite3
import sys
from pathlib import Path
from config import SQLITE_DB, TRANSFORMED_CSV
from database_schema import init_database, import_csv_to_database, get_database_stats

def test_database_integrity():
    """Testa a integridade do banco de dados."""
    print("\n" + "=" * 70)
    print("TESTE DE INTEGRIDADE DO BANCO DE DADOS")
    print("=" * 70)
    
    errors = []
    warnings = []
    
    # Teste 1: Verificar se o banco existe
    print("\n[TESTE 1] Verificando se o banco existe...")
    if not SQLITE_DB.exists():
        errors.append("Banco de dados não encontrado")
        print("   [ERRO] Banco não encontrado")
    else:
        print("   [OK] Banco encontrado")
    
    # Teste 2: Verificar estrutura das tabelas
    print("\n[TESTE 2] Verificando estrutura das tabelas...")
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            
            # Verifica tabela matchups
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matchups'")
            if not cursor.fetchone():
                errors.append("Tabela 'matchups' não existe")
                print("   [ERRO] Tabela 'matchups' não existe")
            else:
                print("   [OK] Tabela 'matchups' existe")
                
                # Verifica colunas essenciais
                cursor.execute("PRAGMA table_info(matchups)")
                columns = [col[1] for col in cursor.fetchall()]
                required_cols = ['gameid', 'league', 't1', 't2', 'date', 'created_at', 'updated_at']
                missing_cols = [col for col in required_cols if col not in columns]
                if missing_cols:
                    errors.append(f"Colunas faltando em matchups: {missing_cols}")
                    print(f"   [ERRO] Colunas faltando: {missing_cols}")
                else:
                    print("   [OK] Todas as colunas essenciais presentes")
            
            # Verifica tabela compositions
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='compositions'")
            if not cursor.fetchone():
                errors.append("Tabela 'compositions' não existe")
                print("   [ERRO] Tabela 'compositions' não existe")
            else:
                print("   [OK] Tabela 'compositions' existe")
            
            # Verifica tabela leagues_teams
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leagues_teams'")
            if not cursor.fetchone():
                errors.append("Tabela 'leagues_teams' não existe")
                print("   [ERRO] Tabela 'leagues_teams' não existe")
            else:
                print("   [OK] Tabela 'leagues_teams' existe")
                
    except Exception as e:
        errors.append(f"Erro ao verificar estrutura: {e}")
        print(f"   [ERRO] {e}")
    
    # Teste 3: Verificar índices
    print("\n[TESTE 3] Verificando índices...")
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = [row[0] for row in cursor.fetchall()]
            expected_indexes = [
                'idx_matchups_league', 'idx_matchups_date', 'idx_matchups_t1',
                'idx_matchups_t2', 'idx_matchups_year', 'idx_compositions_gameid',
                'idx_leagues_teams_league'
            ]
            missing_indexes = [idx for idx in expected_indexes if idx not in indexes]
            if missing_indexes:
                warnings.append(f"Índices faltando: {missing_indexes}")
                print(f"   [AVISO] Índices faltando: {missing_indexes}")
            else:
                print("   [OK] Todos os índices presentes")
    except Exception as e:
        warnings.append(f"Erro ao verificar índices: {e}")
        print(f"   [AVISO] {e}")
    
    # Teste 4: Verificar integridade referencial
    print("\n[TESTE 4] Verificando integridade referencial...")
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            
            # Verifica se há composições sem matchup correspondente
            cursor.execute("""
                SELECT COUNT(*) FROM compositions c
                LEFT JOIN matchups m ON c.gameid = m.gameid
                WHERE m.gameid IS NULL
            """)
            orphan_compositions = cursor.fetchone()[0]
            if orphan_compositions > 0:
                errors.append(f"{orphan_compositions} composições órfãs (sem matchup)")
                print(f"   [ERRO] {orphan_compositions} composições órfãs encontradas")
            else:
                print("   [OK] Nenhuma composição órfã")
            
            # Verifica duplicatas em matchups
            cursor.execute("""
                SELECT gameid, COUNT(*) as count
                FROM matchups
                GROUP BY gameid
                HAVING count > 1
            """)
            duplicates = cursor.fetchall()
            if duplicates:
                errors.append(f"{len(duplicates)} gameids duplicados encontrados")
                print(f"   [ERRO] {len(duplicates)} duplicatas encontradas")
            else:
                print("   [OK] Nenhuma duplicata em matchups")
            
            # Verifica duplicatas em compositions
            cursor.execute("""
                SELECT gameid, team, COUNT(*) as count
                FROM compositions
                GROUP BY gameid, team
                HAVING count > 1
            """)
            duplicates = cursor.fetchall()
            if duplicates:
                errors.append(f"{len(duplicates)} composições duplicadas encontradas")
                print(f"   [ERRO] {len(duplicates)} duplicatas encontradas")
            else:
                print("   [OK] Nenhuma duplicata em compositions")
                
    except Exception as e:
        errors.append(f"Erro ao verificar integridade: {e}")
        print(f"   [ERRO] {e}")
    
    # Teste 5: Verificar preservação de created_at
    print("\n[TESTE 5] Verificando preservação de created_at...")
    try:
        with sqlite3.connect(SQLITE_DB) as conn:
            cursor = conn.cursor()
            
            # Verifica se há registros sem created_at
            cursor.execute("SELECT COUNT(*) FROM matchups WHERE created_at IS NULL")
            null_created = cursor.fetchone()[0]
            if null_created > 0:
                warnings.append(f"{null_created} registros sem created_at")
                print(f"   [AVISO] {null_created} registros sem created_at")
            else:
                print("   [OK] Todos os registros têm created_at")
            
            # Verifica se há registros sem updated_at
            cursor.execute("SELECT COUNT(*) FROM matchups WHERE updated_at IS NULL")
            null_updated = cursor.fetchone()[0]
            if null_updated > 0:
                warnings.append(f"{null_updated} registros sem updated_at")
                print(f"   [AVISO] {null_updated} registros sem updated_at")
            else:
                print("   [OK] Todos os registros têm updated_at")
                
    except Exception as e:
        warnings.append(f"Erro ao verificar timestamps: {e}")
        print(f"   [AVISO] {e}")
    
    # Teste 6: Estatísticas
    print("\n[TESTE 6] Estatísticas do banco...")
    stats = get_database_stats()
    if stats:
        print(f"   Matchups: {stats.get('total_matchups', 0):,}")
        print(f"   Composições: {stats.get('total_compositions', 0):,}")
        print(f"   Ligas: {stats.get('total_leagues', 0)}")
        print(f"   Times: {stats.get('total_teams', 0):,}")
        if stats.get('date_range') and stats['date_range'][0]:
            print(f"   Período: {stats['date_range'][0]} até {stats['date_range'][1]}")
    else:
        warnings.append("Não foi possível obter estatísticas")
        print("   [AVISO] Não foi possível obter estatísticas")
    
    # Resumo
    print("\n" + "=" * 70)
    print("RESUMO DOS TESTES")
    print("=" * 70)
    
    if errors:
        print(f"\n[ERRO] ERROS ENCONTRADOS: {len(errors)}")
        for error in errors:
            print(f"   - {error}")
    else:
        print("\n[OK] NENHUM ERRO ENCONTRADO")
    
    if warnings:
        print(f"\n[AVISO] AVISOS: {len(warnings)}")
        for warning in warnings:
            print(f"   - {warning}")
    else:
        print("\n[OK] NENHUM AVISO")
    
    print("\n" + "=" * 70)
    
    return len(errors) == 0


def test_import_process():
    """Testa o processo de importação."""
    print("\n" + "=" * 70)
    print("TESTE DO PROCESSO DE IMPORTAÇÃO")
    print("=" * 70)
    
    # Verifica se o CSV existe
    if not TRANSFORMED_CSV.exists():
        print(f"\n[ERRO] Arquivo CSV não encontrado: {TRANSFORMED_CSV}")
        return False
    
    print(f"\n[OK] CSV encontrado: {TRANSFORMED_CSV.name}")
    
    # Testa inicialização
    print("\n[TESTE] Inicializando banco...")
    if init_database():
        print("   [OK] Banco inicializado com sucesso")
    else:
        print("   [ERRO] Falha ao inicializar banco")
        return False
    
    # Testa importação
    print("\n[TESTE] Importando dados...")
    if import_csv_to_database():
        print("   [OK] Importação concluída com sucesso")
    else:
        print("   [ERRO] Falha na importação")
        return False
    
    return True


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("SUITE DE TESTES DO BANCO DE DADOS")
    print("=" * 70)
    
    # Teste 1: Processo de importação
    if test_import_process():
        print("\n[OK] TESTE DE IMPORTAÇÃO: PASSOU")
    else:
        print("\n[ERRO] TESTE DE IMPORTAÇÃO: FALHOU")
        sys.exit(1)
    
    # Teste 2: Integridade
    if test_database_integrity():
        print("\n[OK] TESTE DE INTEGRIDADE: PASSOU")
        print("\n[SUCESSO] TODOS OS TESTES PASSARAM!")
        sys.exit(0)
    else:
        print("\n[ERRO] TESTE DE INTEGRIDADE: FALHOU")
        sys.exit(1)
