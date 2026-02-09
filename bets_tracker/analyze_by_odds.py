"""
Análise de resultados das apostas por faixas de odds.
Analisa apostas com odds >= 1.6, >= 1.7, >= 1.8, >= 1.9, >= 2.0
"""
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
import sys

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from prettytable import PrettyTable
    HAS_PRETTYTABLE = True
except ImportError:
    HAS_PRETTYTABLE = False

from config import BETS_DB
from analyze_results import BetStats, ResultsAnalyzer


class OddsAnalyzer:
    """Analisador de resultados por faixas de odds."""
    
    def __init__(self):
        self.console = Console(force_terminal=True, width=120) if HAS_RICH else None
        self.base_analyzer = ResultsAnalyzer()
    
    def get_bets_by_odd_range(self, min_odd: float = None, exclude_low_lines: bool = False) -> List[Dict]:
        """
        Busca apostas resolvidas filtradas por odd mínima.
        
        Args:
            min_odd: Odd mínima (ex: 1.6, 1.7, etc.) ou None para todas
            exclude_low_lines: Se True, exclui apostas com line_value <= 27.5 e side = 'under'
        
        Returns:
            Lista de apostas resolvidas (won/lost)
        """
        if not BETS_DB.exists():
            return []
        
        conn = sqlite3.connect(BETS_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT * FROM bets
            WHERE status IN ('won', 'lost')
        """
        params = []
        
        if min_odd is not None:
            query += " AND odd_decimal >= ?"
            params.append(min_odd)
        
        if exclude_low_lines:
            query += " AND NOT (LOWER(side) = 'under' AND line_value <= ?)"
            params.append(27.5)
        
        query += " ORDER BY matchup_id, expected_value DESC"
        
        cursor.execute(query, params)
        bets = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return bets
    
    def analyze_by_odd_ranges(self, exclude_low_lines: bool = False) -> Dict:
        """
        Analisa apostas por diferentes faixas de odds.
        
        Args:
            exclude_low_lines: Se True, exclui under 27.5 ou menos
        
        Returns:
            Dicionário com análises por faixa de odds
        """
        # Define faixas de odds
        odd_ranges = [
            (None, 'Todas as apostas'),
            (1.4, 'Odds >= 1.4'),
            (1.5, 'Odds >= 1.5'),
            (1.6, 'Odds >= 1.6'),
            (1.7, 'Odds >= 1.7'),
            (1.8, 'Odds >= 1.8'),
            (1.9, 'Odds >= 1.9'),
            (2.0, 'Odds >= 2.0'),
            (2.1, 'Odds >= 2.1'),
            (2.2, 'Odds >= 2.2'),
        ]
        
        results = {}
        
        for min_odd, label in odd_ranges:
            bets = self.get_bets_by_odd_range(min_odd=min_odd, exclude_low_lines=exclude_low_lines)
            
            if not bets:
                results[label] = {
                    'stats': None,
                    'count': 0,
                }
                continue
            
            # Calcula estatísticas
            stats = BetStats(bets)
            
            # Análise por liga
            by_league = self.base_analyzer.analyze_by_dimension(bets, 'league')
            
            # Análise por mercado (market_type + side)
            by_market = self.base_analyzer.analyze_by_market_with_side(bets)
            
            # Análise por estratégia
            strategies = {
                'all': 'Todas as apostas',
                'best': 'Apenas a melhor',
                'top2': 'Top 2 melhores',
                'top3': 'Top 3 melhores',
                'top4': 'Top 4 melhores',
                'top5': 'Top 5 melhores',
            }
            
            by_strategy = {}
            for strategy_key, strategy_label in strategies.items():
                filtered_bets = self.base_analyzer.filter_by_strategy(bets, strategy_key)
                by_strategy[strategy_label] = BetStats(filtered_bets)
            
            results[label] = {
                'stats': stats,
                'count': len(bets),
                'by_league': by_league,
                'by_market': by_market,
                'by_strategy': by_strategy,
            }
        
        return results
    
    def print_analysis(self, results: Dict, show_details: bool = True):
        """Imprime análise formatada por faixas de odds."""
        filter_label = ' (SEM under 27.5 ou menos)' if any('exclude_low_lines' in str(r) for r in results.values()) else ''
        title = f"ANÁLISE POR FAIXAS DE ODDS{filter_label}"
        
        if self.console:
            self.console.print(f"\n[bold cyan]{'=' * 100}[/bold cyan]")
            self.console.print(f"[bold yellow]{title}[/bold yellow]")
            self.console.print(f"[bold cyan]{'=' * 100}[/bold cyan]\n")
        else:
            print(f"\n{'=' * 100}")
            print(title)
            print(f"{'=' * 100}\n")
        
        # Imprime resumo de cada faixa
        for label, data in results.items():
            stats = data['stats']
            count = data['count']
            
            if not stats or count == 0:
                if self.console:
                    self.console.print(f"[dim]   {label}: (nenhuma aposta)[/dim]\n")
                else:
                    print(f"   {label}: (nenhuma aposta)\n")
                continue
            
            if self.console:
                self.console.print(f"[bold magenta]{label}[/bold magenta]")
                self.console.print("-" * 100)
            else:
                print(label)
                print("-" * 100)
            
            self.base_analyzer._print_stats_row("Geral", stats)
            
            if show_details:
                # Por liga
                if data['by_league']:
                    if self.console:
                        self.console.print(f"\n[cyan]Por Liga:[/cyan]")
                    else:
                        print(f"\nPor Liga:")
                    for league, league_stats in sorted(data['by_league'].items()):
                        self.base_analyzer._print_stats_row(league, league_stats)
                
                # Por mercado
                if data['by_market']:
                    if self.console:
                        self.console.print(f"\n[cyan]Por Tipo de Mercado:[/cyan]")
                    else:
                        print(f"\nPor Tipo de Mercado:")
                    for market, market_stats in sorted(data['by_market'].items()):
                        self.base_analyzer._print_stats_row(market, market_stats)
                
                # Por estratégia
                if data['by_strategy']:
                    if self.console:
                        self.console.print(f"\n[cyan]Por Estratégia:[/cyan]")
                    else:
                        print(f"\nPor Estratégia:")
                    for strategy, strategy_stats in data['by_strategy'].items():
                        self.base_analyzer._print_stats_row(strategy, strategy_stats)
            
            print()
    
    def print_summary_table(self, results: Dict):
        """Imprime tabela resumo comparando todas as faixas de odds."""
        if self.console:
            self.console.print(f"\n[bold cyan]{'=' * 100}[/bold cyan]")
            self.console.print("[bold yellow]TABELA RESUMO - COMPARAÇÃO POR FAIXAS DE ODDS[/bold yellow]")
            self.console.print(f"[bold cyan]{'=' * 100}[/bold cyan]\n")
        else:
            print(f"\n{'=' * 100}")
            print("TABELA RESUMO - COMPARAÇÃO POR FAIXAS DE ODDS")
            print(f"{'=' * 100}\n")
        
        # Prepara dados para tabela
        rows = []
        for label, data in results.items():
            stats = data['stats']
            if not stats:
                continue
            
            rows.append({
                'label': label,
                'stats': stats,
            })
        
        if not rows:
            if self.console:
                self.console.print("[red]Nenhum dado disponível para comparação[/red]\n")
            else:
                print("Nenhum dado disponível para comparação\n")
            return
        
        # Cria tabela
        if HAS_PRETTYTABLE:
            table = PrettyTable()
            table.field_names = [
                "Faixa de Odds", "Resolvidas", "V", "L", "Win Rate", 
                "ROI", "Lucro", "Odd Média", "EV Médio"
            ]
            for col in table.field_names:
                if col == "Faixa de Odds":
                    table.align[col] = "l"
                else:
                    table.align[col] = "r"
            
            for row in rows:
                stats = row['stats']
                table.add_row([
                    row['label'],
                    stats.resolved,
                    stats.won,
                    stats.lost,
                    f"{stats.win_rate:.1f}%",
                    f"{stats.roi:+.2f}%",
                    f"{stats.profit:+.2f}",
                    f"{stats.avg_win_odd:.2f}",
                    f"{stats.avg_ev*100:.2f}%",
                ])
            
            print(table)
        elif self.console:
            table = Table(
                show_header=True,
                header_style="bold magenta",
                box=box.SIMPLE,
                show_lines=False,
                min_width=110
            )
            table.add_column("Faixa de Odds", style="cyan", width=25)
            table.add_column("Resolvidas", justify="right", width=10)
            table.add_column("V", justify="right", width=5)
            table.add_column("L", justify="right", width=5)
            table.add_column("Win Rate", justify="right", width=10)
            table.add_column("ROI", justify="right", width=10)
            table.add_column("Lucro", justify="right", width=12)
            table.add_column("Odd Média", justify="right", width=10)
            table.add_column("EV Médio", justify="right", width=10)
            
            for row in rows:
                stats = row['stats']
                roi_style = "green" if stats.roi > 0 else "red" if stats.roi < 0 else "white"
                profit_style = "green" if stats.profit > 0 else "red" if stats.profit < 0 else "white"
                
                table.add_row(
                    row['label'],
                    str(stats.resolved),
                    str(stats.won),
                    str(stats.lost),
                    f"{stats.win_rate:.1f}%",
                    f"[{roi_style}]{stats.roi:+.2f}%[/{roi_style}]",
                    f"[{profit_style}]{stats.profit:+.2f}[/{profit_style}]",
                    f"{stats.avg_win_odd:.2f}",
                    f"{stats.avg_ev*100:.2f}%",
                )
            
            self.console.print(table)
        else:
            # Fallback ASCII
            print(f"{'Faixa de Odds':<25} {'Resolvidas':>10} {'V':>5} {'L':>5} {'Win Rate':>10} {'ROI':>10} {'Lucro':>12} {'Odd Média':>10} {'EV Médio':>10}")
            print("-" * 100)
            for row in rows:
                stats = row['stats']
                print(
                    f"{row['label']:<25} "
                    f"{stats.resolved:>10} "
                    f"{stats.won:>5} "
                    f"{stats.lost:>5} "
                    f"{stats.win_rate:>9.1f}% "
                    f"{stats.roi:>+9.2f}% "
                    f"{stats.profit:>+11.2f} "
                    f"{stats.avg_win_odd:>9.2f} "
                    f"{stats.avg_ev*100:>9.2f}%"
                )
        
        print()
    
    def print_strategy_tables(self, results: Dict):
        """Imprime tabelas resumo por estratégia (melhor, top 2, top 3, top 4, top 5)."""
        strategies = [
            ('best', 'Apenas a melhor'),
            ('top2', 'Top 2 melhores'),
            ('top3', 'Top 3 melhores'),
            ('top4', 'Top 4 melhores'),
            ('top5', 'Top 5 melhores'),
        ]
        
        for strategy_key, strategy_label in strategies:
            if self.console:
                self.console.print(f"\n[bold cyan]{'=' * 100}[/bold cyan]")
                self.console.print(f"[bold yellow]TABELA RESUMO - {strategy_label.upper()} POR FAIXA DE ODDS[/bold yellow]")
                self.console.print(f"[bold cyan]{'=' * 100}[/bold cyan]\n")
            else:
                print(f"\n{'=' * 100}")
                print(f"TABELA RESUMO - {strategy_label.upper()} POR FAIXA DE ODDS")
                print(f"{'=' * 100}\n")
            
            # Prepara dados para tabela
            rows = []
            for label, data in results.items():
                stats = data.get('by_strategy', {}).get(strategy_label)
                if not stats or stats.resolved == 0:
                    continue
                
                rows.append({
                    'label': label,
                    'stats': stats,
                })
            
            if not rows:
                if self.console:
                    self.console.print(f"[dim]Nenhum dado disponível para {strategy_label}[/dim]\n")
                else:
                    print(f"Nenhum dado disponível para {strategy_label}\n")
                continue
            
            # Cria tabela
            if HAS_PRETTYTABLE:
                table = PrettyTable()
                table.field_names = [
                    "Faixa de Odds", "Resolvidas", "V", "L", "Win Rate", 
                    "ROI", "Lucro", "Odd Média", "EV Médio"
                ]
                for col in table.field_names:
                    if col == "Faixa de Odds":
                        table.align[col] = "l"
                    else:
                        table.align[col] = "r"
                
                for row in rows:
                    stats = row['stats']
                    table.add_row([
                        row['label'],
                        stats.resolved,
                        stats.won,
                        stats.lost,
                        f"{stats.win_rate:.1f}%",
                        f"{stats.roi:+.2f}%",
                        f"{stats.profit:+.2f}",
                        f"{stats.avg_win_odd:.2f}",
                        f"{stats.avg_ev*100:.2f}%",
                    ])
                
                print(table)
            elif self.console:
                table = Table(
                    show_header=True,
                    header_style="bold magenta",
                    box=box.SIMPLE,
                    show_lines=False,
                    min_width=110
                )
                table.add_column("Faixa de Odds", style="cyan", width=25)
                table.add_column("Resolvidas", justify="right", width=10)
                table.add_column("V", justify="right", width=5)
                table.add_column("L", justify="right", width=5)
                table.add_column("Win Rate", justify="right", width=10)
                table.add_column("ROI", justify="right", width=10)
                table.add_column("Lucro", justify="right", width=12)
                table.add_column("Odd Média", justify="right", width=10)
                table.add_column("EV Médio", justify="right", width=10)
                
                for row in rows:
                    stats = row['stats']
                    roi_style = "green" if stats.roi > 0 else "red" if stats.roi < 0 else "white"
                    profit_style = "green" if stats.profit > 0 else "red" if stats.profit < 0 else "white"
                    
                    table.add_row(
                        row['label'],
                        str(stats.resolved),
                        str(stats.won),
                        str(stats.lost),
                        f"{stats.win_rate:.1f}%",
                        f"[{roi_style}]{stats.roi:+.2f}%[/{roi_style}]",
                        f"[{profit_style}]{stats.profit:+.2f}[/{profit_style}]",
                        f"{stats.avg_win_odd:.2f}",
                        f"{stats.avg_ev*100:.2f}%",
                    )
                
                self.console.print(table)
            else:
                # Fallback ASCII
                print(f"{'Faixa de Odds':<25} {'Resolvidas':>10} {'V':>5} {'L':>5} {'Win Rate':>10} {'ROI':>10} {'Lucro':>12} {'Odd Média':>10} {'EV Médio':>10}")
                print("-" * 100)
                for row in rows:
                    stats = row['stats']
                    print(
                        f"{row['label']:<25} "
                        f"{stats.resolved:>10} "
                        f"{stats.won:>5} "
                        f"{stats.lost:>5} "
                        f"{stats.win_rate:>9.1f}% "
                        f"{stats.roi:>+9.2f}% "
                        f"{stats.profit:>+11.2f} "
                        f"{stats.avg_win_odd:>9.2f} "
                        f"{stats.avg_ev*100:>9.2f}%"
                    )
            
            print()


def run_odds_analysis(show_details: bool = True, exclude_low_lines: bool = False):
    """
    Executa análise completa por faixas de odds.
    
    Args:
        show_details: Se True, mostra detalhes por liga, mercado e estratégia
        exclude_low_lines: Se True, exclui under 27.5 ou menos
    """
    # Força encoding UTF-8 para Windows
    import os
    if os.name == 'nt':
        os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    analyzer = OddsAnalyzer()
    
    # Análise completa
    results = analyzer.analyze_by_odd_ranges(exclude_low_lines=exclude_low_lines)
    analyzer.print_analysis(results, show_details=show_details)
    
    # Tabela resumo principal (todas as apostas)
    analyzer.print_summary_table(results)
    
    # Tabelas resumo por estratégia (melhor, top 2, top 3, top 4, top 5)
    analyzer.print_strategy_tables(results)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Análise de resultados por faixas de odds"
    )
    parser.add_argument(
        '--summary-only',
        action='store_true',
        help='Mostra apenas resumo geral, sem detalhes por liga/mercado/estratégia'
    )
    parser.add_argument(
        '--exclude-low-lines',
        action='store_true',
        help='Exclui apostas under com linha <= 27.5'
    )
    
    args = parser.parse_args()
    
    run_odds_analysis(show_details=not args.summary_only, exclude_low_lines=args.exclude_low_lines)
