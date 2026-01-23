"""
Orquestrador principal do sistema de rastreamento de apostas
"""
import sys
import argparse
from pathlib import Path

from bets_database import init_database, get_bet_stats
from collect_value_bets import ValueBetsCollector
from update_results import ResultsUpdater


def collect_bets(league: str = None, init_db: bool = False):
    """Coleta apostas com valor."""
    if init_db:
        print("[INIT] Inicializando banco de dados...")
        init_database()
        print()
    
    from config import BETS_DB
    if not BETS_DB.exists():
        print("[AVISO] Banco de dados não encontrado. Inicializando...")
        init_database()
        print()
    
    collector = ValueBetsCollector()
    value_bets = collector.collect_all_value_bets(league_filter=league)
    
    if value_bets:
        collector.save_bets(value_bets)
        collector.print_stats()
    else:
        print("\n[AVISO] Nenhuma aposta com valor encontrada")


def update_results(dry_run: bool = False):
    """Atualiza resultados das apostas."""
    from config import BETS_DB
    
    if not BETS_DB.exists():
        print("[ERRO] Banco de apostas não encontrado!")
        print(f"   Execute primeiro: python main.py collect")
        return
    
    updater = ResultsUpdater()
    stats = updater.update_all_results(dry_run=dry_run)
    updater.print_stats()
    
    if not dry_run:
        print("\n[ESTATISTICAS] Estatisticas Atualizadas do Banco:")
        db_stats = get_bet_stats()
        print(f"   Total de apostas: {db_stats['total']}")
        print(f"   Por status: {db_stats['by_status']}")
        
        if db_stats['roi']['total_resolved'] > 0:
            roi = db_stats['roi']
            print(f"\n[ROI] ROI:")
            print(f"   Resolvidas: {roi['total_resolved']}")
            print(f"   Vitorias: {roi['wins']} ({roi['win_rate']:.1f}%)")
            print(f"   Derrotas: {roi['losses']}")
            print(f"   Odd media (vitorias): {roi['avg_win_odd']:.2f}")
            print(f"   EV medio: {roi['avg_ev']:.2%}")


def show_stats():
    """Mostra estatísticas do banco."""
    from config import BETS_DB
    
    if not BETS_DB.exists():
        print("[ERRO] Banco de apostas não encontrado!")
        return
    
    stats = get_bet_stats()
    
    print("=" * 60)
    print("[ESTATISTICAS] Estatísticas do Banco de Apostas")
    print("=" * 60)
    print(f"   Total de apostas: {stats['total']}")
    print(f"   Por status: {stats['by_status']}")
    print(f"   Por metodo: {stats.get('by_metodo', {})}")
    
    if stats['roi']['total_resolved'] > 0:
        roi = stats['roi']
        print(f"\n[ROI] ROI:")
        print(f"   Resolvidas: {roi['total_resolved']}")
        print(f"   Vitorias: {roi['wins']} ({roi['win_rate']:.1f}%)")
        print(f"   Derrotas: {roi['losses']}")
        print(f"   Odd media (vitorias): {roi['avg_win_odd']:.2f}")
        print(f"   EV medio: {roi['avg_ev']:.2%}")
    else:
        print("\n[AVISO] Nenhuma aposta resolvida ainda")
    
    print("=" * 60)


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Sistema de rastreamento de apostas com valor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py collect                    # Coleta apostas com valor
  python main.py collect --league LCK        # Coleta apenas LCK
  python main.py update                      # Atualiza resultados
  python main.py update --dry-run            # Simula atualização
  python main.py stats                      # Mostra estatísticas
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comando a executar')
    
    # Comando collect
    collect_parser = subparsers.add_parser('collect', help='Coleta apostas com valor')
    collect_parser.add_argument('--league', type=str, help='Filtrar por liga')
    collect_parser.add_argument('--init-db', action='store_true', help='Inicializar banco')
    
    # Comando update
    update_parser = subparsers.add_parser('update', help='Atualiza resultados')
    update_parser.add_argument('--dry-run', action='store_true', help='Apenas simula')
    
    # Comando stats
    subparsers.add_parser('stats', help='Mostra estatísticas')
    
    # Comando init
    subparsers.add_parser('init', help='Inicializa banco de dados')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'init':
        print("[INIT] Inicializando banco de dados...")
        init_database()
        print("[OK] Banco inicializado!")
    
    elif args.command == 'collect':
        collect_bets(league=args.league, init_db=args.init_db)
    
    elif args.command == 'update':
        update_results(dry_run=args.dry_run)
    
    elif args.command == 'stats':
        show_stats()


if __name__ == "__main__":
    main()
