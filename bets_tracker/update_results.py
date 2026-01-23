"""
Atualiza resultados das apostas comparando com histórico
"""
import sys
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from bets_database import (
    get_pending_bets,
    update_bet_result,
    get_bet_stats
)
from result_matcher import ResultMatcher
from config import BETS_DB


class ResultsUpdater:
    """Atualiza resultados das apostas."""
    
    def __init__(self):
        """Inicializa o atualizador."""
        self.matcher = ResultMatcher()
        self.stats = {
            'pending_bets': 0,
            'matched': 0,
            'updated': 0,
            'not_found': 0,
            'errors': 0
        }
    
    def update_all_results(self, dry_run: bool = False) -> Dict:
        """
        Atualiza resultados de todas as apostas pendentes.
        
        Args:
            dry_run: Se True, apenas mostra o que seria atualizado
            
        Returns:
            Dicionário com estatísticas
        """
        print("[BUSCANDO] Buscando apostas pendentes...")
        pending_bets = get_pending_bets()
        
        if not pending_bets:
            print("   [OK] Nenhuma aposta pendente")
            return self.stats
        
        self.stats['pending_bets'] = len(pending_bets)
        print(f"   [OK] {len(pending_bets)} apostas pendentes encontradas\n")
        
        print("[COMPARANDO] Comparando com historico para encontrar resultados...\n")
        
        for i, bet in enumerate(pending_bets, 1):
            bet_id = bet['id']
            matchup_id = bet['matchup_id']
            
            print(f"[{i}/{len(pending_bets)}] Aposta #{bet_id}: {bet['home_team']} vs {bet['away_team']}")
            print(f"   Market: {bet['side']} {bet['line_value']} @ {bet['odd_decimal']}")
            
            try:
                # Tenta fazer match
                game_result = self.matcher.match_game(bet)
                
                if not game_result:
                    print(f"   [AVISO] Jogo nao encontrado no historico")
                    self.stats['not_found'] += 1
                    continue
                
                confidence = game_result.get('confidence', 0)
                print(f"   [OK] Match encontrado (confianca: {confidence:.1%})")
                
                # Determina resultado
                status, result_value = self.matcher.determine_bet_result(bet, game_result)
                
                print(f"   Resultado: {status.upper()} | Total kills: {result_value}")
                
                if not dry_run:
                    # Atualiza no banco
                    update_bet_result(bet_id, result_value, status)
                    print(f"   [SALVO] Atualizado no banco")
                    self.stats['updated'] += 1
                else:
                    print(f"   [DRY RUN] Seria atualizado: {status} com {result_value}")
                
                self.stats['matched'] += 1
                
            except Exception as e:
                print(f"   [ERRO] Erro ao processar: {e}")
                self.stats['errors'] += 1
                continue
            
            print()
        
        return self.stats
    
    def print_stats(self):
        """Imprime estatísticas da atualização."""
        print("=" * 60)
        print("[ESTATISTICAS] Estatisticas da Atualizacao")
        print("=" * 60)
        print(f"   Apostas pendentes: {self.stats['pending_bets']}")
        print(f"   Matches encontrados: {self.stats['matched']}")
        print(f"   Resultados atualizados: {self.stats['updated']}")
        print(f"   Não encontrados: {self.stats['not_found']}")
        print(f"   Erros: {self.stats['errors']}")
        print("=" * 60)


def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Atualiza resultados das apostas comparando com histórico"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas mostra o que seria atualizado, sem salvar'
    )
    
    args = parser.parse_args()
    
    # Verifica se banco existe
    if not BETS_DB.exists():
        print("[ERRO] Banco de apostas nao encontrado!")
        print(f"   Execute primeiro: python collect_value_bets.py")
        return
    
    # Atualiza resultados
    updater = ResultsUpdater()
    stats = updater.update_all_results(dry_run=args.dry_run)
    
    updater.print_stats()
    
    # Mostra estatísticas atualizadas do banco
    if not args.dry_run:
        print("\n[ESTATISTICAS] Estatisticas Atualizadas do Banco:")
        db_stats = get_bet_stats()
        print(f"   Total de apostas: {db_stats['total']}")
        print(f"   Por status: {db_stats['by_status']}")
        
        if db_stats['roi']['total_resolved'] > 0:
            roi = db_stats['roi']
            print(f"\n[ROI] ROI:")
            print(f"   Resolvidas: {roi['total_resolved']}")
            print(f"   Vitórias: {roi['wins']} ({roi['win_rate']:.1f}%)")
            print(f"   Derrotas: {roi['losses']}")
            print(f"   Odd média (vitórias): {roi['avg_win_odd']:.2f}")
            print(f"   EV médio: {roi['avg_ev']:.2%}")


if __name__ == "__main__":
    main()
