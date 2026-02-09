"""
Sistema completo de análise de resultados das apostas
Analisa por método, liga, tipo de mercado, estratégia e com/sem filtro de linha mínima
"""
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple
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


class BetStats:
    """Classe para calcular estatísticas de apostas."""
    
    def __init__(self, bets: List[Dict]):
        self.bets = bets
        self.total = len(bets)
        self.won = sum(1 for b in bets if b.get('status') == 'won')
        self.lost = sum(1 for b in bets if b.get('status') == 'lost')
        self.pending = sum(1 for b in bets if b.get('status') == 'pending')
        self.resolved = self.won + self.lost
        
        # Win rate
        self.win_rate = (self.won / self.resolved * 100) if self.resolved > 0 else 0.0
        
        # Lucro (assumindo stake de 1 unidade por aposta)
        self.total_stake = float(self.resolved)
        self.total_return = sum(b.get('odd_decimal', 0) for b in bets if b.get('status') == 'won')
        self.profit = self.total_return - self.total_stake
        self.roi = (self.profit / self.total_stake * 100) if self.total_stake > 0 else 0.0
        
        # Odd média
        self.avg_odd = sum(b.get('odd_decimal', 0) for b in bets) / self.total if self.total > 0 else 0.0
        
        # Odd média das vitórias
        win_odds = [b.get('odd_decimal', 0) for b in bets if b.get('status') == 'won']
        self.avg_win_odd = sum(win_odds) / len(win_odds) if win_odds else 0.0
        
        # EV médio
        self.avg_ev = sum(b.get('expected_value', 0) for b in bets) / self.total if self.total > 0 else 0.0
        
        # Edge médio
        self.avg_edge = sum(b.get('edge', 0) for b in bets) / self.total if self.total > 0 else 0.0
        
        # Win rate esperado baseado na odd média
        self.expected_win_rate = (1 / self.avg_odd * 100) if self.avg_odd > 0 else 0.0
        self.win_rate_diff = self.win_rate - self.expected_win_rate
        
        # Lucro por aposta (média)
        self.avg_profit_per_bet = self.profit / self.resolved if self.resolved > 0 else 0.0
    
    def to_dict(self) -> Dict:
        """Retorna estatísticas como dicionário."""
        return {
            'total': self.total,
            'resolved': self.resolved,
            'won': self.won,
            'lost': self.lost,
            'pending': self.pending,
            'win_rate': self.win_rate,
            'total_stake': self.total_stake,
            'total_return': self.total_return,
            'profit': self.profit,
            'roi': self.roi,
            'avg_odd': self.avg_odd,
            'avg_win_odd': self.avg_win_odd,
            'avg_ev': self.avg_ev,
            'avg_edge': self.avg_edge,
            'expected_win_rate': self.expected_win_rate,
            'win_rate_diff': self.win_rate_diff,
            'avg_profit_per_bet': self.avg_profit_per_bet,
        }


class ResultsAnalyzer:
    """Analisador completo de resultados das apostas."""
    
    def __init__(self):
        # Força terminal e cores mesmo quando executado via subprocess
        if HAS_RICH:
            import os
            # Garante que o Rich detecte o terminal corretamente
            os.environ['TERM'] = os.environ.get('TERM', 'xterm-256color')
            self.console = Console(force_terminal=True, width=120, force_interactive=False)
        else:
            self.console = None
        self.min_line_threshold = 27.5  # Threshold para filtrar under 27.5 ou menos
    
    def get_bets(self, metodo: Optional[str] = None, exclude_low_lines: bool = False) -> List[Dict]:
        """
        Busca apostas resolvidas do banco.
        
        Args:
            metodo: 'probabilidade_empirica' ou 'ml'/'machinelearning' ou None (todas)
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
        
        if metodo:
            # Aceita tanto 'ml' quanto 'machinelearning'
            if metodo == 'ml':
                query += " AND (metodo = 'ml' OR metodo = 'machinelearning')"
            else:
                query += " AND metodo = ?"
                params.append(metodo)
        
        if exclude_low_lines:
            query += " AND NOT (LOWER(side) = 'under' AND line_value <= ?)"
            params.append(self.min_line_threshold)
        
        query += " ORDER BY matchup_id, expected_value DESC"
        
        cursor.execute(query, params)
        bets = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return bets
    
    def filter_by_strategy(self, bets: List[Dict], strategy: str) -> List[Dict]:
        """
        Filtra apostas por estratégia.
        
        Args:
            bets: Lista de apostas
            strategy: 'all', 'best', 'top2', 'top3', 'top4', 'top5'
        
        Returns:
            Lista filtrada de apostas
        """
        if strategy == 'all':
            return bets
        
        # Agrupa por jogo (matchup_id)
        games = defaultdict(list)
        for bet in bets:
            games[bet['matchup_id']].append(bet)
        
        # Ordena apostas de cada jogo por EV (decrescente)
        for matchup_id in games:
            games[matchup_id].sort(key=lambda x: x.get('expected_value', 0), reverse=True)
        
        if strategy == 'best':
            # Apenas a melhor aposta por jogo
            return [game_bets[0] for game_bets in games.values()]
        elif strategy == 'top2':
            # Top 2 apostas por jogo
            return [bet for game_bets in games.values() for bet in game_bets[:2]]
        elif strategy == 'top3':
            # Top 3 apostas por jogo
            return [bet for game_bets in games.values() for bet in game_bets[:3]]
        elif strategy == 'top4':
            # Top 4 apostas por jogo
            return [bet for game_bets in games.values() for bet in game_bets[:4]]
        elif strategy == 'top5':
            # Top 5 apostas por jogo
            return [bet for game_bets in games.values() for bet in game_bets[:5]]
        
        return bets
    
    def analyze_by_dimension(self, bets: List[Dict], dimension: str) -> Dict[str, BetStats]:
        """
        Analisa apostas agrupadas por uma dimensão.
        
        Args:
            bets: Lista de apostas
            dimension: 'league_name', 'market_type', 'metodo'
        
        Returns:
            Dicionário com estatísticas por valor da dimensão
        """
        grouped = defaultdict(list)
        
        for bet in bets:
            # Mapeia dimensões para campos do banco
            field_map = {
                'league': 'league_name',
                'league_name': 'league_name',
                'market': 'market_type',
                'market_type': 'market_type',
                'metodo': 'metodo',
            }
            actual_field = field_map.get(dimension, dimension)
            key = bet.get(actual_field, 'unknown')
            grouped[key].append(bet)
        
        results = {}
        for key, group_bets in sorted(grouped.items()):
            results[key] = BetStats(group_bets)
        
        return results
    
    def analyze_by_market_with_side(self, bets: List[Dict]) -> Dict[str, BetStats]:
        """
        Analisa apostas agrupadas por market_type + side (ex: 'total_kills OVER', 'total_kills UNDER').
        
        Args:
            bets: Lista de apostas
        
        Returns:
            Dicionário com estatísticas por mercado+side
        """
        grouped = defaultdict(list)
        
        for bet in bets:
            market_type = bet.get('market_type', 'unknown')
            side = bet.get('side', '').upper() if bet.get('side') else 'UNKNOWN'
            key = f"{market_type} {side}"
            grouped[key].append(bet)
        
        results = {}
        for key, group_bets in sorted(grouped.items()):
            results[key] = BetStats(group_bets)
        
        return results
    
    def analyze_complete(self, metodo: str, exclude_low_lines: bool = False) -> Dict:
        """
        Análise completa para um método e filtro.
        
        Args:
            metodo: 'probabilidade_empirica' ou 'ml' (aceita 'ml' ou 'machinelearning')
            exclude_low_lines: Se True, exclui under 27.5 ou menos
        
        Returns:
            Dicionário com todas as análises
        """
        # Busca apostas
        bets = self.get_bets(metodo=metodo, exclude_low_lines=exclude_low_lines)
        
        if not bets:
            return {
                'metodo': metodo,
                'exclude_low_lines': exclude_low_lines,
                'summary': None,
                'by_league': {},
                'by_market': {},
                'by_strategy': {},
            }
        
        # Resumo geral
        summary = BetStats(bets)
        
        # Por liga
        by_league = self.analyze_by_dimension(bets, 'league')
        
        # Por tipo de mercado (combinando market_type + side)
        by_market = self.analyze_by_market_with_side(bets)
        
        # Por estratégia
        strategies = {
            'all': 'Todas as apostas',
            'best': 'Apenas a melhor',
            'top2': 'Top 2 melhores',
            'top3': 'Top 3 melhores',
        }
        
        by_strategy = {}
        for strategy_key, strategy_label in strategies.items():
            filtered_bets = self.filter_by_strategy(bets, strategy_key)
            by_strategy[strategy_label] = BetStats(filtered_bets)
        
        return {
            'metodo': metodo,
            'exclude_low_lines': exclude_low_lines,
            'summary': summary,
            'by_league': by_league,
            'by_market': by_market,
            'by_strategy': by_strategy,
        }
    
    def print_analysis(self, analysis: Dict, show_details: bool = True):
        """Imprime análise formatada."""
        metodo = analysis['metodo']
        exclude_low = analysis['exclude_low_lines']
        
        # Título
        if metodo == 'probabilidade_empirica':
            metodo_label = 'Empírico'
        elif metodo in ('ml', 'machinelearning'):
            metodo_label = 'ML'
        else:
            metodo_label = metodo
        filter_label = ' (SEM under 27.5 ou menos)' if exclude_low else ''
        title = f"ANÁLISE - MÉTODO {metodo_label.upper()}{filter_label}"
        
        if self.console:
            self.console.print(f"\n[bold cyan]{'=' * 100}[/bold cyan]")
            self.console.print(f"[bold yellow]{title}[/bold yellow]")
            self.console.print(f"[bold cyan]{'=' * 100}[/bold cyan]\n")
        else:
            print(f"\n{'=' * 100}")
            print(title)
            print(f"{'=' * 100}\n")
        
        summary = analysis['summary']
        if not summary:
            if self.console:
                self.console.print("[red]Nenhuma aposta resolvida encontrada[/red]\n")
            else:
                print("Nenhuma aposta resolvida encontrada\n")
            return
        
        # 1. RESUMO GERAL
        self._print_section("RESUMO GERAL", summary)
        
        if not show_details:
            return
        
        # 2. POR LIGA
        if analysis['by_league']:
            self._print_section("POR LIGA", None, analysis['by_league'])
        
        # 3. POR TIPO DE MERCADO
        if analysis['by_market']:
            self._print_section("POR TIPO DE MERCADO", None, analysis['by_market'])
        
        # 4. POR ESTRATÉGIA
        if analysis['by_strategy']:
            self._print_section("POR ESTRATÉGIA", None, analysis['by_strategy'])
    
    def _print_section(self, title: str, single_stats: Optional[BetStats] = None, 
                      multiple_stats: Optional[Dict[str, BetStats]] = None):
        """Imprime uma seção de análise."""
        if self.console:
            self.console.print(f"[bold magenta]{title}[/bold magenta]")
            self.console.print("-" * 100)
        else:
            print(title)
            print("-" * 100)
        
        if single_stats:
            self._print_stats_row("Geral", single_stats)
        elif multiple_stats:
            for key, stats in multiple_stats.items():
                self._print_stats_row(key, stats)
        
        print()
    
    def _print_stats_row(self, label: str, stats: BetStats):
        """Imprime uma linha de estatísticas."""
        if stats.resolved == 0:
            if self.console:
                self.console.print(f"   [dim]{label}: (nenhuma resolvida)[/dim]")
            else:
                print(f"   {label}: (nenhuma resolvida)")
            return
        
        # Determina cores para ROI e Lucro
        roi_color = "green" if stats.roi > 0 else "red" if stats.roi < 0 else "white"
        profit_color = "green" if stats.profit > 0 else "red" if stats.profit < 0 else "white"
        
        # Limita tamanho do label para evitar quebra de linha (reduzido para caber tudo)
        label_display = label[:25] if len(label) > 25 else label
        
        if self.console:
            # Usa Rich para formatação com cores - formato compacto
            self.console.print(
                f"   {label_display:<25} | "
                f"Res: {stats.resolved:>3} | "
                f"V:{stats.won:>3} L:{stats.lost:>3} | "
                f"WR: {stats.win_rate:>5.1f}% | "
                f"[{roi_color}]ROI: {stats.roi:>+6.2f}%[/{roi_color}] | "
                f"[{profit_color}]Lucro: {stats.profit:>+7.2f}[/{profit_color}] | "
                f"Odd: {stats.avg_win_odd:>4.2f}"
            )
        else:
            # Formatação simples sem cores - formato compacto
            line = (
                f"   {label_display:<25} | "
                f"Res: {stats.resolved:>3} | "
                f"V:{stats.won:>3} L:{stats.lost:>3} | "
                f"WR: {stats.win_rate:>5.1f}% | "
                f"ROI: {stats.roi:>+6.2f}% | "
                f"Lucro: {stats.profit:>+7.2f} | "
                f"Odd: {stats.avg_win_odd:>4.2f}"
            )
            print(line)
    
    def print_summary_table(self, all_analyses: List[Dict]):
        """Imprime tabela resumo comparando todos os métodos e variantes."""
        if self.console:
            self.console.print(f"\n[bold cyan]{'=' * 100}[/bold cyan]")
            self.console.print("[bold yellow]TABELA RESUMO - COMPARAÇÃO DE MÉTODOS E VARIANTES[/bold yellow]")
            self.console.print(f"[bold cyan]{'=' * 100}[/bold cyan]\n")
        else:
            print(f"\n{'=' * 100}")
            print("TABELA RESUMO - COMPARAÇÃO DE MÉTODOS E VARIANTES")
            print(f"{'=' * 100}\n")
        
        # Prepara dados para tabela
        rows = []
        for analysis in all_analyses:
            metodo = analysis['metodo']
            exclude_low = analysis['exclude_low_lines']
            summary = analysis['summary']
            
            if not summary:
                continue
            
            if metodo == 'probabilidade_empirica':
                metodo_label = 'Empírico'
            elif metodo in ('ml', 'machinelearning'):
                metodo_label = 'ML'
            else:
                metodo_label = metodo
            filter_label = ' (sem ≤27.5)' if exclude_low else ''
            
            rows.append({
                'label': f"{metodo_label}{filter_label}",
                'stats': summary,
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
            # Define cabeçalhos
            table.field_names = [
                "Método", "Resolvidas", "V", "L", "Win Rate", 
                "ROI", "Lucro", "Odd Média", "EV Médio"
            ]
            # Alinhamento
            for col in table.field_names:
                if col == "Método":
                    table.align[col] = "l"
                else:
                    table.align[col] = "r"
            
            # Adiciona linhas
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
            
            # Exibe tabela (cabeçalho é exibido automaticamente)
            print(table)
        elif self.console:
            table = Table(
                show_header=True,
                header_style="bold magenta",
                box=box.SIMPLE,
                show_lines=False,
                min_width=110
            )
            table.add_column("Método", style="cyan", width=25)
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
            print(f"{'Método':<25} {'Resolvidas':>10} {'V':>5} {'L':>5} {'Win Rate':>10} {'ROI':>10} {'Lucro':>12} {'Odd Média':>10} {'EV Médio':>10}")
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


def run_complete_analysis(show_details: bool = True):
    """
    Executa análise completa de todos os métodos e variantes.
    
    Args:
        show_details: Se True, mostra detalhes por liga, mercado e estratégia
    """
    # Força encoding UTF-8 para Windows
    import os
    if os.name == 'nt':
        os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    analyzer = ResultsAnalyzer()
    all_analyses = []
    
    # 1. Método Empírico - Completo
    print("\n" + "=" * 100)
    print("INICIANDO ANÁLISE COMPLETA")
    print("=" * 100)
    
    analysis_empirico = analyzer.analyze_complete('probabilidade_empirica', exclude_low_lines=False)
    analyzer.print_analysis(analysis_empirico, show_details=show_details)
    all_analyses.append(analysis_empirico)
    
    # 2. Método Empírico - Sem under 27.5 ou menos
    analysis_empirico_no_low = analyzer.analyze_complete('probabilidade_empirica', exclude_low_lines=True)
    analyzer.print_analysis(analysis_empirico_no_low, show_details=show_details)
    all_analyses.append(analysis_empirico_no_low)
    
    # 3. Método ML - Completo
    analysis_ml = analyzer.analyze_complete('ml', exclude_low_lines=False)
    analyzer.print_analysis(analysis_ml, show_details=show_details)
    all_analyses.append(analysis_ml)
    
    # 4. Método ML - Sem under 27.5 ou menos
    analysis_ml_no_low = analyzer.analyze_complete('ml', exclude_low_lines=True)
    analyzer.print_analysis(analysis_ml_no_low, show_details=show_details)
    all_analyses.append(analysis_ml_no_low)
    
    # 5. Tabela Resumo Final
    analyzer.print_summary_table(all_analyses)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Análise completa de resultados das apostas"
    )
    parser.add_argument(
        '--summary-only',
        action='store_true',
        help='Mostra apenas resumo geral, sem detalhes por liga/mercado/estratégia'
    )
    
    args = parser.parse_args()
    
    run_complete_analysis(show_details=not args.summary_only)
