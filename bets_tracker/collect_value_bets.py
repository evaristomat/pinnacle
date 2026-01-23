"""
Coleta apostas com valor do odds_analyzer e salva no banco bets.db
"""
import sys
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import importlib.util

# IMPORTANTE: Importa módulos locais PRIMEIRO (antes de adicionar odds_analysis ao path)
from bets_database import init_database, save_bet, get_bet_stats
from config import PINNACLE_DB

# Agora adiciona odds_analysis ao path e importa
PROJECT_ROOT = Path(__file__).parent.parent
ODDS_ANALYSIS_PATH = PROJECT_ROOT / "odds_analysis"
CURRENT_DIR = Path(__file__).parent

# Remove diretório atual e pai do path temporariamente para evitar conflito
current_dir_str = str(CURRENT_DIR)
parent_dir_str = str(PROJECT_ROOT)
for path_to_remove in [current_dir_str, parent_dir_str]:
    if path_to_remove in sys.path:
        sys.path.remove(path_to_remove)

# Adiciona odds_analysis ao início do path
if str(ODDS_ANALYSIS_PATH) not in sys.path:
    sys.path.insert(0, str(ODDS_ANALYSIS_PATH))

# Carrega config do odds_analysis primeiro para evitar conflito
odds_config_path = ODDS_ANALYSIS_PATH / "config.py"
odds_config_spec = importlib.util.spec_from_file_location("odds_config", odds_config_path)
odds_config_module = importlib.util.module_from_spec(odds_config_spec)
odds_config_spec.loader.exec_module(odds_config_module)

# Salva referência ao config local do bets_tracker
bets_config_module = sys.modules.get('config')

# Temporariamente sobrescreve config para odds_analyzer
sys.modules['config'] = odds_config_module

# Agora importa odds_analyzer (que vai usar o config correto)
odds_analyzer_path = ODDS_ANALYSIS_PATH / "odds_analyzer.py"
spec = importlib.util.spec_from_file_location("odds_analyzer_module", odds_analyzer_path)
odds_analyzer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(odds_analyzer_module)
OddsAnalyzer = odds_analyzer_module.OddsAnalyzer

# RESTAURA o config do bets_tracker para outros módulos
if bets_config_module:
    sys.modules['config'] = bets_config_module
else:
    # Se não estava carregado, carrega agora
    bets_config_spec = importlib.util.spec_from_file_location("config", CURRENT_DIR / "config.py")
    bets_config_module = importlib.util.module_from_spec(bets_config_spec)
    bets_config_spec.loader.exec_module(bets_config_module)
    sys.modules['config'] = bets_config_module

# Restaura path original
for path_to_restore in [parent_dir_str, current_dir_str]:
    if path_to_restore not in sys.path:
        sys.path.append(path_to_restore)


class ValueBetsCollector:
    """Coleta apostas com valor e salva no banco."""
    
    def __init__(self):
        """Inicializa o coletor."""
        self.analyzer = OddsAnalyzer()
        self.stats = {
            'games_analyzed': 0,
            'bets_found': 0,
            'bets_saved': 0,
            'errors': 0
        }
    
    def collect_all_value_bets(self, league_filter: str = None, include_finalized: bool = True) -> List[Dict]:
        """
        Coleta todas as apostas com valor dos jogos futuros e finalizados.
        
        Args:
            league_filter: Filtro opcional de liga
            include_finalized: Se True, também busca jogos finalizados com draft (para análise retrospectiva)
            
        Returns:
            Lista de apostas com valor encontradas
        """
        all_value_bets = []
        
        # 1. Busca jogos futuros
        print("[BUSCANDO] Buscando jogos futuros...")
        future_games = self.analyzer.get_upcoming_games(league_filter=league_filter)
        
        if future_games:
            print(f"   [OK] {len(future_games)} jogos futuros encontrados")
            print("\n[ANALISANDO] Analisando jogos futuros para encontrar apostas com valor...\n")
            
            for i, game in enumerate(future_games, 1):
                matchup_id = game['matchup_id']
                print(f"[FUTURO {i}/{len(future_games)}] Analisando: {game['home_team']} vs {game['away_team']} ({game['league_name']})")
                
                try:
                    analysis = self.analyzer.analyze_game(matchup_id)
                    
                    if not analysis or 'error' in analysis:
                        print(f"   [AVISO] Erro ou sem dados históricos")
                        self.stats['errors'] += 1
                        continue
                    
                    self.stats['games_analyzed'] += 1
                    
                    # Extrai apostas com valor
                    value_bets = self._extract_value_bets(analysis)
                    
                    if value_bets:
                        print(f"   [OK] {len(value_bets)} apostas com valor encontradas")
                        all_value_bets.extend(value_bets)
                        self.stats['bets_found'] += len(value_bets)
                    else:
                        print(f"   [INFO] Nenhuma aposta com valor")
                
                except Exception as e:
                    print(f"   [ERRO] Erro ao analisar jogo: {e}")
                    self.stats['errors'] += 1
                    continue
        else:
            print("[AVISO] Nenhum jogo futuro encontrado")
        
        # 2. Busca jogos finalizados com draft (para análise retrospectiva)
        if include_finalized:
            print("\n[BUSCANDO] Buscando jogos finalizados com draft disponível...")
            finalized_games = self.analyzer.get_finalized_games_with_draft(league_filter=league_filter)
            
            if finalized_games:
                print(f"   [OK] {len(finalized_games)} jogos finalizados com draft encontrados")
                print("\n[ANALISANDO] Analisando jogos finalizados (método ML + empírico)...\n")
                
                for i, game in enumerate(finalized_games, 1):
                    matchup_id = game['matchup_id']
                    print(f"[FINALIZADO {i}/{len(finalized_games)}] Analisando: {game['home_team']} vs {game['away_team']} ({game['league_name']})")
                    
                    try:
                        analysis = self.analyzer.analyze_game(matchup_id)
                        
                        if not analysis or 'error' in analysis:
                            print(f"   [AVISO] Erro ou sem dados históricos")
                            self.stats['errors'] += 1
                            continue
                        
                        self.stats['games_analyzed'] += 1
                        
                        # Extrai apenas apostas com método ML (que convergiram)
                        value_bets = self._extract_value_bets(analysis, only_ml=True)
                        
                        if value_bets:
                            print(f"   [OK] {len(value_bets)} apostas com método ML encontradas (empírico + ML convergiram)")
                            all_value_bets.extend(value_bets)
                            self.stats['bets_found'] += len(value_bets)
                        else:
                            print(f"   [INFO] Nenhuma aposta com convergência ML (empírico e ML divergiram ou sem valor)")
                    
                    except Exception as e:
                        print(f"   [ERRO] Erro ao analisar jogo: {e}")
                        self.stats['errors'] += 1
                        continue
            else:
                print("[AVISO] Nenhum jogo finalizado com draft encontrado")
        
        return all_value_bets
    
    def _extract_value_bets(self, analysis: Dict, only_ml: bool = False) -> List[Dict]:
        """
        Extrai apostas com valor de uma análise.
        
        Args:
            analysis: Resultado de analyze_game
            only_ml: Se True, só retorna apostas com método ML (que convergiram)
            
        Returns:
            Lista de apostas com valor formatadas para salvar
        """
        value_bets = []
        
        game = analysis['game']
        markets = analysis.get('markets', [])
        
        for market_data in markets:
            market = market_data['market']
            analysis_data = market_data['analysis']
            
            # Só processa se tiver valor
            if not analysis_data.get('value', False):
                continue
            
            # Se only_ml=True, só processa apostas com método ML (que convergiram)
            if only_ml:
                metodo = analysis_data.get('metodo', '')
                if metodo != 'ml':  # METODO_ML = 'ml'
                    continue
                # Verifica se realmente convergiu (ML aponta para mesma direção)
                ml_converges = analysis_data.get('ml_converges')
                if ml_converges is not True:
                    continue
            
            # Prepara dados da aposta
            bet_data = {
                'matchup_id': game['matchup_id'],
                'game_date': game['start_time'],
                'league_name': game['league_name'],
                'home_team': game['home_team'],
                'away_team': game['away_team'],
                'market_type': market['market_type'],
                'line_value': market.get('line_value'),
                'side': market['side'],
                'odd_decimal': market['odd_decimal'],
                'metodo': analysis_data.get('metodo', 'probabilidade_empirica'),  # Método usado na análise
                'expected_value': analysis_data['expected_value'],
                'edge': analysis_data['edge'],
                'empirical_prob': analysis_data.get('empirical_prob'),
                'implied_prob': analysis_data.get('implied_probability'),
                'historical_mean': market_data.get('historical_stats', {}).get('mean'),
                'historical_std': market_data.get('historical_stats', {}).get('std'),
                'historical_games': market_data.get('historical_stats', {}).get('n'),
                'status': 'pending',
                'metadata': {
                    'normalization': analysis.get('normalization', {}),
                    'alinhado_media': analysis_data.get('alinhado_media')
                }
            }
            
            value_bets.append(bet_data)
        
        return value_bets
    
    def save_bets(self, bets: List[Dict]) -> int:
        """
        Salva apostas no banco de dados.
        
        Args:
            bets: Lista de apostas para salvar
            
        Returns:
            Número de apostas salvas
        """
        if not bets:
            return 0
        
        print(f"\n[SALVANDO] Salvando {len(bets)} apostas no banco...")
        
        saved = 0
        duplicates = 0
        for bet in bets:
            try:
                bet_id = save_bet(bet)
                if bet_id is None:
                    duplicates += 1
                else:
                    saved += 1
                    self.stats['bets_saved'] += 1
            except Exception as e:
                print(f"   [ERRO] Erro ao salvar aposta: {e}")
                self.stats['errors'] += 1
        
        print(f"   [OK] {saved} apostas salvas")
        if duplicates > 0:
            print(f"   [INFO] {duplicates} apostas já existiam (duplicatas ignoradas)")
        return saved
    
    def print_stats(self):
        """Imprime estatísticas da coleta."""
        print("\n" + "=" * 60)
        print("[ESTATISTICAS] Estatísticas da Coleta")
        print("=" * 60)
        print(f"   Jogos analisados: {self.stats['games_analyzed']}")
        print(f"   Apostas com valor encontradas: {self.stats['bets_found']}")
        print(f"   Apostas salvas: {self.stats['bets_saved']}")
        print(f"   Erros: {self.stats['errors']}")
        print("=" * 60)


def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Coleta apostas com valor e salva no banco bets.db"
    )
    parser.add_argument(
        '--league',
        type=str,
        help='Filtrar por liga específica (ex: LCK, LEC)'
    )
    parser.add_argument(
        '--init-db',
        action='store_true',
        help='Inicializar banco de dados antes de coletar'
    )
    
    args = parser.parse_args()
    
    # Inicializa banco se necessário
    if args.init_db:
        print("[INIT] Inicializando banco de dados...")
        init_database()
        print()
    
    # Verifica se banco existe
    from config import BETS_DB
    if not BETS_DB.exists():
        print("[AVISO] Banco de dados não encontrado. Inicializando...")
        init_database()
        print()
    
    # Coleta apostas
    collector = ValueBetsCollector()
    value_bets = collector.collect_all_value_bets(league_filter=args.league)
    
    if value_bets:
        collector.save_bets(value_bets)
        collector.print_stats()
        
        # Mostra estatísticas do banco
        stats = get_bet_stats()
        print(f"\n[ESTATISTICAS] Estatísticas do Banco:")
        print(f"   Total de apostas: {stats['total']}")
        print(f"   Por status: {stats['by_status']}")
    else:
        print("\n[AVISO] Nenhuma aposta com valor encontrada")


if __name__ == "__main__":
    main()
