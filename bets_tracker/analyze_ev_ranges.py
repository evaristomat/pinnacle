"""
Análise detalhada de apostas por faixas de EV (Expected Value)
Mostra resultados separados por EV >= 5%, >= 10%, >= 15% e >= 20%
"""
import sqlite3
from pathlib import Path
from typing import Dict, List
from config import BETS_DB


def analyze_by_ev_ranges(metodo: str = None, best_per_game: bool = False) -> Dict:
    """
    Analisa apostas resolvidas por faixas de EV.
    
    Args:
        metodo: Filtro opcional por método ('probabilidade_empirica' ou 'machinelearning')
        best_per_game: Se True, considera apenas a melhor aposta (maior EV) por jogo
    
    Returns:
        Dict com estatísticas por faixa de EV
    """
    if not BETS_DB.exists():
        print(f"[ERRO] Banco não encontrado: {BETS_DB}")
        return {}
    
    conn = sqlite3.connect(BETS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Query base
    base_query = """
        SELECT 
            id,
            metodo,
            expected_value,
            odd_decimal,
            status,
            edge,
            league_name,
            matchup_id
        FROM bets
        WHERE status IN ('won', 'lost')
    """
    
    params = []
    if metodo:
        base_query += " AND metodo = ?"
        params.append(metodo)
    
    cursor.execute(base_query, params)
    bets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Se best_per_game=True, filtra para manter apenas a melhor aposta (maior EV) por jogo
    if best_per_game:
        from collections import defaultdict
        bets_by_game = defaultdict(list)
        
        # Agrupa apostas por matchup_id
        for bet in bets:
            bets_by_game[bet['matchup_id']].append(bet)
        
        # Para cada jogo, pega apenas a aposta com maior EV
        filtered_bets = []
        for matchup_id, game_bets in bets_by_game.items():
            # Ordena por EV (decrescente) e pega a primeira
            best_bet = max(game_bets, key=lambda x: x['expected_value'])
            filtered_bets.append(best_bet)
        
        bets = filtered_bets
        print(f"[FILTRO] Considerando apenas melhor aposta por jogo: {len(bets)} apostas (de {sum(len(gb) for gb in bets_by_game.values())} totais)")
        print()
    
    if not bets:
        return {}
    
    # Define faixas de EV (em decimal: 0.05 = 5%, 0.10 = 10%, etc)
    ev_ranges = {
        'all': {'min': 0.0, 'label': 'Todas as apostas'},
        'ev_5_plus': {'min': 0.05, 'label': 'EV >= 5%'},
        'ev_10_plus': {'min': 0.10, 'label': 'EV >= 10%'},
        'ev_15_plus': {'min': 0.15, 'label': 'EV >= 15%'},
        'ev_20_plus': {'min': 0.20, 'label': 'EV >= 20%'},
    }
    
    results = {}
    
    for range_key, range_info in ev_ranges.items():
        # Filtra apostas por faixa de EV
        filtered_bets = [
            bet for bet in bets 
            if bet['expected_value'] >= range_info['min']
        ]
        
        if not filtered_bets:
            continue
        
        # Calcula estatísticas
        total = len(filtered_bets)
        wins = sum(1 for bet in filtered_bets if bet['status'] == 'won')
        losses = sum(1 for bet in filtered_bets if bet['status'] == 'lost')
        win_rate = (wins / total * 100) if total > 0 else 0
        
        # Odd média das vitórias
        win_odds = [bet['odd_decimal'] for bet in filtered_bets if bet['status'] == 'won']
        avg_win_odd = sum(win_odds) / len(win_odds) if win_odds else 0
        
        # EV médio
        avg_ev = sum(bet['expected_value'] for bet in filtered_bets) / total
        
        # Lucro (assumindo stake de 1 unidade)
        profit = sum(
            (bet['odd_decimal'] - 1) if bet['status'] == 'won' else -1
            for bet in filtered_bets
        )
        
        # ROI (Return on Investment)
        roi = (profit / total * 100) if total > 0 else 0
        
        # Edge médio
        avg_edge = sum(bet['edge'] for bet in filtered_bets) / total if filtered_bets else 0
        
        results[range_key] = {
            'label': range_info['label'],
            'total': total,
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'avg_win_odd': avg_win_odd,
            'avg_ev': avg_ev,
            'avg_edge': avg_edge,
            'profit': profit,
            'roi': roi
        }
    
    return results


def print_analysis(metodo: str = None, best_per_game: bool = False):
    """Imprime análise formatada por faixas de EV."""
    metodo_label = metodo if metodo else "Todos os métodos"
    filter_label = " (Melhor aposta por jogo)" if best_per_game else ""
    
    print("=" * 80)
    print(f"ANÁLISE DETALHADA POR FAIXAS DE EV - {metodo_label.upper()}{filter_label}")
    print("=" * 80)
    print()
    
    results = analyze_by_ev_ranges(metodo=metodo, best_per_game=best_per_game)
    
    if not results:
        print("[AVISO] Nenhuma aposta resolvida encontrada")
        return
    
    # Ordem de exibição
    display_order = ['all', 'ev_5_plus', 'ev_10_plus', 'ev_15_plus', 'ev_20_plus']
    
    for range_key in display_order:
        if range_key not in results:
            continue
        
        stats = results[range_key]
        
        print(f"[{stats['label']}]")
        print(f"   Total resolvidas: {stats['total']}")
        print(f"   Vitorias: {stats['wins']} ({stats['win_rate']:.1f}%)")
        print(f"   Derrotas: {stats['losses']}")
        print(f"   Odd media (vitorias): {stats['avg_win_odd']:.2f}")
        print(f"   EV medio: {stats['avg_ev']*100:.2f}%")
        print(f"   Edge medio: {stats['avg_edge']:.2f}%")
        print(f"   Lucro: {stats['profit']:.2f} unidades")
        print(f"   ROI: {stats['roi']:.2f}%")
        
        # Calcula win rate esperado baseado na odd média
        if stats['avg_win_odd'] > 0:
            expected_win_rate = (1 / stats['avg_win_odd']) * 100
            actual_win_rate = stats['win_rate']
            difference = actual_win_rate - expected_win_rate
            print(f"   Win rate esperado (1/odd): {expected_win_rate:.1f}%")
            print(f"   Win rate real: {actual_win_rate:.1f}%")
            print(f"   Diferenca: {difference:+.1f}% ({'MELHOR' if difference > 0 else 'PIOR'} que esperado)")
        
        # Lucro por aposta (média)
        avg_profit_per_bet = stats['profit'] / stats['total'] if stats['total'] > 0 else 0
        print(f"   Lucro medio por aposta: {avg_profit_per_bet:.3f} unidades")
        
        print()
    
    # Análise comparativa detalhada
    print("=" * 80)
    print("RESUMO COMPARATIVO")
    print("=" * 80)
    
    if 'all' in results:
        all_stats = results['all']
        print(f"\nTodas as apostas:")
        print(f"   Win Rate: {all_stats['win_rate']:.1f}% | ROI: {all_stats['roi']:.2f}% | EV medio: {all_stats['avg_ev']*100:.2f}%")
    
    for range_key in ['ev_5_plus', 'ev_10_plus', 'ev_15_plus', 'ev_20_plus']:
        if range_key in results:
            stats = results[range_key]
            if 'all' in results:
                all_stats = results['all']
                win_rate_diff = stats['win_rate'] - all_stats['win_rate']
                roi_diff = stats['roi'] - all_stats['roi']
                print(f"\n{stats['label']}:")
                print(f"   Win Rate: {stats['win_rate']:.1f}% ({win_rate_diff:+.1f}% vs todas) | ROI: {stats['roi']:.2f}% ({roi_diff:+.2f}% vs todas)")
                print(f"   EV medio: {stats['avg_ev']*100:.2f}% | Apostas: {stats['total']}")
    
    # Análise detalhada de distribuição de odds e EV por faixa
    print("=" * 80)
    print("DETALHAMENTO POR FAIXA DE EV")
    print("=" * 80)
    
    conn = sqlite3.connect(BETS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    for range_key in ['ev_5_plus', 'ev_10_plus', 'ev_15_plus', 'ev_20_plus']:
        if range_key not in results:
            continue
        
        stats = results[range_key]
        min_ev = {'ev_5_plus': 0.05, 'ev_10_plus': 0.10, 'ev_15_plus': 0.15, 'ev_20_plus': 0.20}[range_key]
        
        # Query para buscar apostas dessa faixa
        query = """
            SELECT 
                expected_value,
                odd_decimal,
                status,
                edge,
                matchup_id
            FROM bets
            WHERE status IN ('won', 'lost')
            AND expected_value >= ?
        """
        params = [min_ev]
        if metodo:
            query += " AND metodo = ?"
            params.append(metodo)
        
        cursor.execute(query, params)
        bets = [dict(row) for row in cursor.fetchall()]
        
        if not bets:
            continue
        
        # Se best_per_game, filtra novamente para esta faixa
        if best_per_game:
            from collections import defaultdict
            bets_by_game = defaultdict(list)
            for bet in bets:
                bets_by_game[bet['matchup_id']].append(bet)
            bets = [max(game_bets, key=lambda x: x['expected_value']) for game_bets in bets_by_game.values()]
        
        # Estatísticas detalhadas
        evs = [bet['expected_value'] for bet in bets]
        odds = [bet['odd_decimal'] for bet in bets]
        win_odds = [bet['odd_decimal'] for bet in bets if bet['status'] == 'won']
        loss_odds = [bet['odd_decimal'] for bet in bets if bet['status'] == 'lost']
        
        print(f"\n{stats['label']} (EV >= {min_ev*100:.0f}%):")
        print(f"   Total: {len(bets)} apostas")
        print(f"   EV minimo: {min(evs)*100:.2f}%")
        print(f"   EV maximo: {max(evs)*100:.2f}%")
        print(f"   EV medio: {stats['avg_ev']*100:.2f}%")
        print(f"   Odd minima: {min(odds):.2f}")
        print(f"   Odd maxima: {max(odds):.2f}")
        print(f"   Odd media (todas): {sum(odds)/len(odds):.2f}")
        if win_odds:
            print(f"   Odd media (vitorias): {sum(win_odds)/len(win_odds):.2f}")
        if loss_odds:
            print(f"   Odd media (derrotas): {sum(loss_odds)/len(loss_odds):.2f}")
        print(f"   Vitorias: {stats['wins']} ({stats['win_rate']:.1f}%)")
        print(f"   Derrotas: {stats['losses']}")
        print(f"   Lucro total: {stats['profit']:.2f} unidades")
        print(f"   ROI: {stats['roi']:.2f}%")
        print(f"   Lucro medio/aposta: {stats['profit']/len(bets):.3f} unidades")
        
        # Win rate esperado vs real
        if stats['avg_win_odd'] > 0:
            expected_wr = (1 / stats['avg_win_odd']) * 100
            actual_wr = stats['win_rate']
            diff = actual_wr - expected_wr
            print(f"   Win rate esperado: {expected_wr:.1f}% | Real: {actual_wr:.1f}% | Diff: {diff:+.1f}%")
    
    conn.close()
    
    # Análise por ligas
    print("=" * 80)
    print("ANALISE POR LIGAS")
    print("=" * 80)
    
    conn = sqlite3.connect(BETS_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Busca todas as ligas
    query = """
        SELECT DISTINCT league_name
        FROM bets
        WHERE status IN ('won', 'lost')
    """
    params = []
    if metodo:
        query += " AND metodo = ?"
        params.append(metodo)
    
    cursor.execute(query, params)
    leagues = [row[0] for row in cursor.fetchall()]
    
    if not leagues:
        print("[AVISO] Nenhuma liga encontrada")
        conn.close()
        return
    
    # Analisa cada liga
    for league in sorted(leagues):
        query = """
            SELECT 
                expected_value,
                odd_decimal,
                status,
                edge,
                matchup_id
            FROM bets
            WHERE status IN ('won', 'lost')
            AND league_name = ?
        """
        params = [league]
        if metodo:
            query += " AND metodo = ?"
            params.append(metodo)
        
        cursor.execute(query, params)
        bets = [dict(row) for row in cursor.fetchall()]
        
        if not bets:
            continue
        
        # Se best_per_game, filtra para manter apenas melhor aposta por jogo
        if best_per_game:
            from collections import defaultdict
            bets_by_game = defaultdict(list)
            for bet in bets:
                bets_by_game[bet['matchup_id']].append(bet)
            bets = [max(game_bets, key=lambda x: x['expected_value']) for game_bets in bets_by_game.values()]
        
        # Calcula estatísticas da liga
        total = len(bets)
        wins = sum(1 for bet in bets if bet['status'] == 'won')
        losses = sum(1 for bet in bets if bet['status'] == 'lost')
        win_rate = (wins / total * 100) if total > 0 else 0
        
        win_odds = [bet['odd_decimal'] for bet in bets if bet['status'] == 'won']
        avg_win_odd = sum(win_odds) / len(win_odds) if win_odds else 0
        
        avg_ev = sum(bet['expected_value'] for bet in bets) / total
        
        profit = sum(
            (bet['odd_decimal'] - 1) if bet['status'] == 'won' else -1
            for bet in bets
        )
        
        roi = (profit / total * 100) if total > 0 else 0
        
        expected_wr = (1 / avg_win_odd * 100) if avg_win_odd > 0 else 0
        diff_wr = win_rate - expected_wr
        
        print(f"\n[{league}]")
        print(f"   Total: {total} apostas")
        print(f"   Vitorias: {wins} ({win_rate:.1f}%)")
        print(f"   Derrotas: {losses}")
        print(f"   Odd media (vitorias): {avg_win_odd:.2f}")
        print(f"   EV medio: {avg_ev*100:.2f}%")
        print(f"   Lucro: {profit:.2f} unidades")
        print(f"   ROI: {roi:.2f}%")
        if avg_win_odd > 0:
            print(f"   Win rate esperado: {expected_wr:.1f}% | Real: {win_rate:.1f}% | Diff: {diff_wr:+.1f}%")
    
    conn.close()
    print()


def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Analisa apostas por faixas de EV (Expected Value)"
    )
    parser.add_argument(
        '--metodo',
        type=str,
        choices=['probabilidade_empirica', 'machinelearning'],
        help='Filtrar por método específico'
    )
    parser.add_argument(
        '--best-per-game',
        action='store_true',
        help='Considerar apenas a melhor aposta (maior EV) por jogo'
    )
    
    args = parser.parse_args()
    
    print_analysis(metodo=args.metodo, best_per_game=args.best_per_game)


if __name__ == "__main__":
    main()
