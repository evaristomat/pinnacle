"""
Orquestrador principal do sistema de rastreamento de apostas
"""
import sys
import argparse
from pathlib import Path

from bets_database import init_database, get_bet_stats, get_bets_by_metodo, prune_bets_by_ev, filter_best_per_map_db
from collect_value_bets import ValueBetsCollector, EV_MIN_DEFAULT
from update_results import ResultsUpdater
from analyze_results import run_complete_analysis
from analyze_by_odds import run_odds_analysis


def collect_bets(league: str = None, init_db: bool = False, ev_min: float = EV_MIN_DEFAULT, prune_existing: bool = False):
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
    
    if prune_existing:
        pr = prune_bets_by_ev(float(ev_min), statuses=("pending", "feita"), all_statuses=False, backup=True)
        if pr.get("deleted"):
            print(f"[PRUNE] Removidas {pr['deleted']} apostas (EV < {ev_min:.2f}) de status pending/feita")
            if pr.get("backup_path"):
                print(f"        Backup: {pr['backup_path']}")
        else:
            print(f"[PRUNE] Nenhuma aposta pendente/feita com EV < {ev_min:.2f} para remover")

    collector = ValueBetsCollector(ev_min=float(ev_min))
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


def update_results(
    *,
    dry_run: bool = False,
    db: str = "bets",
    include_pending: bool = False,
    min_hours: float | None = None,
    limit: int | None = None,
    summary: bool = False,
):
    """Atualiza resultados das apostas."""
    from config import BETS_DB, USER_BETS_DB

    if db == "user":
        db_path = USER_BETS_DB
    else:
        db_path = BETS_DB

    if not db_path.exists():
        print("[ERRO] Banco de apostas não encontrado!")
        print(f"   DB esperado: {db_path}")
        print(f"   Execute primeiro: python main.py collect")
        return

    updater = ResultsUpdater(db_path=db_path)
    stats = updater.update_all_results(
        dry_run=dry_run,
        include_pending=include_pending,
        min_hours=min_hours,
        limit=limit,
        summary=summary,
    )
    updater.print_stats()

    if not dry_run:
        print("\n[ESTATISTICAS] Estatisticas Atualizadas do Banco:")
        db_stats = get_bet_stats(db_path=db_path)
        print(f"   Total de apostas: {db_stats['total']}")
        print(f"   Por status: {db_stats['by_status']}")
        print(f"   Por metodo: {db_stats.get('by_metodo', {})}")

    def _print_roi(label: str, r: dict, compact: bool = False):
        if r['total_resolved'] == 0:
            if compact:
                print(f"   {label}: (nenhuma resolvida)")
            else:
                print(f"\n[ROI] {label}: (nenhuma resolvida)")
            return
        ret = r.get('return_pct', 0)
        lucro = r.get('lucro', 0)
        if compact:
            print(f"   {label}: {r['total_resolved']} resolvidas | {r['wins']}V-{r['losses']}L | Return {ret:+.1f}% | Lucro {lucro:+.2f} u")
            return
        print(f"\n[ROI] {label}:")
        print(f"   Resolvidas: {r['total_resolved']}")
        print(f"   Vitorias: {r['wins']} ({r['win_rate']:.1f}%)")
        print(f"   Derrotas: {r['losses']}")
        print(f"   Odd media (vitorias): {r['avg_win_odd']:.2f}")
        print(f"   Return: {ret:+.2f}% (lucro/total u apostadas)")
        print(f"   Lucro: {lucro:+.2f} u")

    if not dry_run and db_stats['roi']['total_resolved'] > 0:
        _print_roi("ROI (total)", db_stats['roi'])
        print(f"\n[ROI] Empirico:")
        _print_roi("Geral", db_stats.get('roi_empirico', {}), compact=True)
        _print_roi("ROI 10+", db_stats.get('roi_empirico_10', {}), compact=True)
        _print_roi("ROI 20+", db_stats.get('roi_empirico_20', {}), compact=True)
        print(f"\n[ROI] ML:")
        _print_roi("Geral", db_stats.get('roi_ml', {}), compact=True)
        _print_roi("ROI 10+", db_stats.get('roi_ml_10', {}), compact=True)
        _print_roi("ROI 20+", db_stats.get('roi_ml_20', {}), compact=True)


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
    
    def _print_roi(label: str, r: dict, compact: bool = False):
        if r['total_resolved'] == 0:
            if compact:
                print(f"   {label}: (nenhuma resolvida)")
            else:
                print(f"\n[ROI] {label}: (nenhuma resolvida)")
            return
        ret = r.get('return_pct', 0)
        lucro = r.get('lucro', 0)
        if compact:
            print(f"   {label}: {r['total_resolved']} resolvidas | {r['wins']}V-{r['losses']}L | Return {ret:+.1f}% | Lucro {lucro:+.2f} u")
            return
        print(f"\n[ROI] {label}:")
        print(f"   Resolvidas: {r['total_resolved']}")
        print(f"   Vitorias: {r['wins']} ({r['win_rate']:.1f}%)")
        print(f"   Derrotas: {r['losses']}")
        print(f"   Odd media (vitorias): {r['avg_win_odd']:.2f}")
        print(f"   Return: {ret:+.2f}% (lucro/total u apostadas)")
        print(f"   Lucro: {lucro:+.2f} u")

    if stats['roi']['total_resolved'] > 0:
        _print_roi("ROI (total)", stats['roi'])
        print(f"\n[ROI] Empirico:")
        _print_roi("Geral", stats.get('roi_empirico', {}), compact=True)
        _print_roi("ROI 10+", stats.get('roi_empirico_10', {}), compact=True)
        _print_roi("ROI 20+", stats.get('roi_empirico_20', {}), compact=True)
        print(f"\n[ROI] ML:")
        _print_roi("Geral", stats.get('roi_ml', {}), compact=True)
        _print_roi("ROI 10+", stats.get('roi_ml_10', {}), compact=True)
        _print_roi("ROI 20+", stats.get('roi_ml_20', {}), compact=True)
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
  python main.py analyze                     # Análise completa de resultados
  python main.py analyze --summary-only      # Análise apenas com resumo
  python main.py analyze-odds                # Análise por faixas de odds
  python main.py analyze-odds --exclude-low-lines  # Análise por odds sem under <= 27.5
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comando a executar')
    
    # Comando collect
    collect_parser = subparsers.add_parser('collect', help='Coleta apostas com valor')
    collect_parser.add_argument('--league', type=str, help='Filtrar por liga')
    collect_parser.add_argument('--init-db', action='store_true', help='Inicializar banco')
    collect_parser.add_argument('--ev-min', type=float, default=EV_MIN_DEFAULT, help='EV mínimo para salvar no banco (0.05 = 5%%)')
    collect_parser.add_argument(
        '--prune-existing',
        action=argparse.BooleanOptionalAction,
        default=False,
        help='Remove do banco apostas pending/feita com EV abaixo do mínimo (faz backup antes)',
    )
    
    # Comando update
    update_parser = subparsers.add_parser('update', help='Atualiza resultados')
    update_parser.add_argument('--dry-run', action='store_true', help='Apenas simula')
    update_parser.add_argument(
        '--db',
        choices=['bets', 'user'],
        default='bets',
        help="Qual banco atualizar: bets (bets.db) | user (user_bets.db)",
    )
    update_parser.add_argument(
        '--include-pending',
        action='store_true',
        help="Inclui apostas 'pending' na atualização (além de 'feita')",
    )
    update_parser.add_argument(
        '--min-hours',
        type=float,
        default=None,
        help="Só tenta atualizar apostas com game_date pelo menos X horas no passado (ex: 24)",
    )
    update_parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help="Limita quantas apostas processar (útil para testar)",
    )
    update_parser.add_argument(
        '--summary',
        action='store_true',
        help='Mostra apenas resumo + amostra (evita imprimir cada aposta)',
    )
    
    # Comando stats
    subparsers.add_parser('stats', help='Mostra estatísticas')

    # Comando list
    subparsers.add_parser('list', help='Lista apostas separadas por método (empírico | ML)')
    
    # Comando analyze
    analyze_parser = subparsers.add_parser('analyze', help='Análise completa de resultados')
    analyze_parser.add_argument('--summary-only', action='store_true', help='Mostra apenas resumo geral')
    
    # Comando analyze-odds
    analyze_odds_parser = subparsers.add_parser('analyze-odds', help='Análise por faixas de odds')
    analyze_odds_parser.add_argument('--summary-only', action='store_true', help='Mostra apenas resumo geral')
    analyze_odds_parser.add_argument('--exclude-low-lines', action='store_true', help='Exclui apostas under <= 27.5')
    
    # Comando init
    subparsers.add_parser('init', help='Inicializa banco de dados')

    # Comando filter-map
    filter_map_parser = subparsers.add_parser('filter-map', help='Filtra banco mantendo N melhores apostas por mapa')
    filter_map_parser.add_argument('--max-per-map', type=int, default=3,
                                   help='Máximo de apostas por (matchup, mapa, método). Default: 3')

    # Comando prune-ev
    prune_parser = subparsers.add_parser('prune-ev', help='Remove apostas com EV abaixo do mínimo')
    prune_parser.add_argument('--min-ev', type=float, default=EV_MIN_DEFAULT, help='EV mínimo (0.05 = 5%%)')
    prune_parser.add_argument(
        '--all-statuses',
        action='store_true',
        help="Se setado, remove também won/lost/void (por padrão só pending/feita)",
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    if args.command == 'init':
        print("[INIT] Inicializando banco de dados...")
        init_database()
        print("[OK] Banco inicializado!")
    
    elif args.command == 'collect':
        collect_bets(league=args.league, init_db=args.init_db, ev_min=args.ev_min, prune_existing=args.prune_existing)
    
    elif args.command == 'update':
        update_results(
            dry_run=args.dry_run,
            db=args.db,
            include_pending=bool(getattr(args, "include_pending", False)),
            min_hours=getattr(args, "min_hours", None),
            limit=getattr(args, "limit", None),
            summary=bool(getattr(args, "summary", False)),
        )
    
    elif args.command == 'stats':
        show_stats()

    elif args.command == 'list':
        list_bets_by_method()
    
    elif args.command == 'analyze':
        run_complete_analysis(show_details=not args.summary_only)
    
    elif args.command == 'analyze-odds':
        run_odds_analysis(show_details=not args.summary_only, exclude_low_lines=args.exclude_low_lines)

    elif args.command == 'filter-map':
        result = filter_best_per_map_db(
            max_per_map=int(args.max_per_map),
            backup=True,
        )
        print(f"\n[OK] Banco filtrado: {result['total_before']} -> {result['total_after']} apostas")
        if result.get("backup_path"):
            print(f"     Backup: {result['backup_path']}")

    elif args.command == 'prune-ev':
        pr = prune_bets_by_ev(
            float(args.min_ev),
            statuses=("pending", "feita"),
            all_statuses=bool(args.all_statuses),
            backup=True,
        )
        deleted = pr.get("deleted", 0)
        print(f"[OK] Removidas {deleted} apostas com EV < {float(args.min_ev):.2f}")
        if pr.get("backup_path"):
            print(f"     Backup: {pr['backup_path']}")


if __name__ == "__main__":
    main()
