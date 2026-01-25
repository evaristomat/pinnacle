"""
Orquestrador principal do sistema de rastreamento de apostas
"""
import sys
import argparse
from pathlib import Path

from bets_database import init_database, get_bet_stats, get_bets_by_metodo
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
        stats = get_bet_stats()
        print(f"\n[ESTATISTICAS] Estatísticas do Banco:")
        print(f"   Total de apostas: {stats['total']}")
        print(f"   Por status: {stats['by_status']}")
        print(f"   Por metodo: {stats.get('by_metodo', {})}")
        print(f"   Ver apostas separadas: python main.py list")
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
        print(f"   Por metodo: {db_stats.get('by_metodo', {})}")

        def _print_roi(label: str, r: dict):
            if r['total_resolved'] == 0:
                print(f"\n[ROI] {label}: (nenhuma resolvida)")
                return
            print(f"\n[ROI] {label}:")
            print(f"   Resolvidas: {r['total_resolved']}")
            print(f"   Vitorias: {r['wins']} ({r['win_rate']:.1f}%)")
            print(f"   Derrotas: {r['losses']}")
            print(f"   Odd media (vitorias): {r['avg_win_odd']:.2f}")
            print(f"   EV medio: {r['avg_ev']:.2%}")
            print(f"   Lucro: {r.get('lucro', 0):+.2f} u")

        if db_stats['roi']['total_resolved'] > 0:
            _print_roi("ROI (total)", db_stats['roi'])
            _print_roi("ROI Empirico", db_stats.get('roi_empirico', {}))
            _print_roi("ROI ML", db_stats.get('roi_ml', {}))


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
    
    def _print_roi(label: str, r: dict):
        if r['total_resolved'] == 0:
            print(f"\n[ROI] {label}: (nenhuma resolvida)")
            return
        print(f"\n[ROI] {label}:")
        print(f"   Resolvidas: {r['total_resolved']}")
        print(f"   Vitorias: {r['wins']} ({r['win_rate']:.1f}%)")
        print(f"   Derrotas: {r['losses']}")
        print(f"   Odd media (vitorias): {r['avg_win_odd']:.2f}")
        print(f"   EV medio: {r['avg_ev']:.2%}")
        print(f"   Lucro: {r.get('lucro', 0):+.2f} u")

    if stats['roi']['total_resolved'] > 0:
        _print_roi("ROI (total)", stats['roi'])
        _print_roi("ROI Empirico", stats.get('roi_empirico', {}))
        _print_roi("ROI ML", stats.get('roi_ml', {}))
    else:
        print("\n[AVISO] Nenhuma aposta resolvida ainda")

    print("=" * 60)


def list_bets_by_method():
    """Lista apostas do banco separadas por método (empírico | ML)."""
    from config import BETS_DB

    if not BETS_DB.exists():
        print("[ERRO] Banco de apostas não encontrado!")
        return

    emp = get_bets_by_metodo('probabilidade_empirica')
    ml = get_bets_by_metodo('ml')

    print("=" * 80)
    print("[RESULTADOS] Apostas no banco - separadas por método")
    print("=" * 80)
    print(f"   Total: {len(emp) + len(ml)}  |  Empírico: {len(emp)}  |  ML: {len(ml)}")
    print("=" * 80)

    def _fmt(b):
        ev = b.get('expected_value') or 0
        return (
            f"   #{b['id']:4}  {b['home_team']} vs {b['away_team']}  ({b['league_name']})  "
            f"{b['game_date'][:10]}  {b['side']} {b.get('line_value')} @ {b['odd_decimal']:.2f}  "
            f"EV={ev*100:+.1f}%  [{b['status']}]"
        )

    print("\n--- MÉTODO EMPÍRICO ---")
    if not emp:
        print("   (nenhuma)")
    else:
        for b in emp:
            print(_fmt(b))

    print("\n--- MÉTODO ML ---")
    if not ml:
        print("   (nenhuma)")
    else:
        for b in ml:
            print(_fmt(b))

    print("\n" + "=" * 80)


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Sistema de rastreamento de apostas com valor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python main.py collect                    # Coleta apostas com valor
  python main.py collect --league LCK        # Coleta apenas LCK
  python main.py list                       # Lista apostas separadas por metodo (empirico | ML)
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

    # Comando list
    subparsers.add_parser('list', help='Lista apostas separadas por método (empírico | ML)')
    
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

    elif args.command == 'list':
        list_bets_by_method()


if __name__ == "__main__":
    main()
