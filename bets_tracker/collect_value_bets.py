"""
Coleta apostas com valor do odds_analyzer e salva no banco bets.db
"""
import sys
import os
from pathlib import Path
from typing import List, Dict
from datetime import datetime
import importlib.util

# Mantemos volume no banco (default EV>=5%) e filtramos EV maior nos UIs/relatórios.
# Você pode ajustar sem mexer no código via env var.
# EV em decimal: 0.05 = 5%
EV_MIN_DEFAULT = float(os.getenv("PINNACLE_EV_MIN_STORE", "0.05"))

# Configura encoding UTF-8 para Windows
if sys.platform == 'win32':
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except:
            pass
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# IMPORTANTE: Importa módulos locais PRIMEIRO (antes de adicionar odds_analysis ao path)
from bets_database import init_database, save_bet, get_bet_stats, get_processed_matchup_ids
from config import PINNACLE_DB, MAX_BETS_PER_MAP
from telegram_notifier import notify_new_bets, is_enabled as telegram_enabled

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
    
    def __init__(self, ev_min: float = EV_MIN_DEFAULT):
        """Inicializa o coletor."""
        self.ev_min = float(ev_min)
        self.analyzer = OddsAnalyzer()
        self.stats = {
            'games_analyzed': 0,
            'bets_found': 0,
            'bets_saved': 0,
            'errors': 0,
            'empirical_found': 0,
            'ml_found': 0,
            'skipped': 0,
        }
        self.error_log = []  # Lista de erros detalhados
    
    def collect_all_value_bets(self, league_filter: str = None, include_finalized: bool = True) -> List[Dict]:
        """
        Coleta apostas com valor em duas passadas sequenciais. Sem fallbacks; apenas dados reais.

        1. PASSA 1 – Método empírico: análise estatística + EV com total_kills_values (histórico real).
           Termina a passada antes de prosseguir.

        2. PASSA 2 – Método ML: apenas jogos com draft; só considera valor se empírico + ML convergem.
           Usa sempre dados reais (empírico obrigatório).

        Args:
            league_filter: Filtro opcional de liga
            include_finalized: Se True, roda PASSA 2 para jogos finalizados com draft (ML)

        Returns:
            Lista de apostas com valor encontradas
        """
        all_value_bets = []
        
        # Busca TODOS os jogos do banco (futuros e passados)
        print("[BUSCANDO] Buscando TODOS os jogos do banco Pinnacle (futuros e passados)...")
        all_games = self.analyzer.get_all_games(league_filter=league_filter)
        
        if not all_games:
            print("[AVISO] Nenhum jogo encontrado no banco")
            return all_value_bets
        
        print(f"   [OK] {len(all_games)} jogos encontrados no banco")
        
        # Separa jogos futuros dos passados
        now = datetime.now()
        future_games = []
        past_games = []
        
        for g in all_games:
            start_time_str = g.get('start_time', '')
            if not start_time_str:
                # Se não tem data, trata como futuro (para segurança)
                future_games.append(g)
                continue
            
            try:
                # Tenta parsear ISO format: "2026-01-29T02:00:00" ou "2026-01-29T02:00:00Z"
                start_time_clean = start_time_str.strip()
                
                # Remove timezone se presente (Z ou +HH:MM)
                if start_time_clean.endswith('Z'):
                    start_time_clean = start_time_clean[:-1]
                elif '+' in start_time_clean:
                    start_time_clean = start_time_clean.split('+')[0]
                elif start_time_clean.count('-') >= 3 and ':' in start_time_clean:
                    # Pode ter timezone negativo, pega só a parte antes do último -
                    parts = start_time_clean.rsplit('-', 1)
                    if len(parts) == 2 and ':' in parts[1]:
                        start_time_clean = parts[0]
                
                # Parse ISO ou formato simples
                if 'T' in start_time_clean:
                    game_time = datetime.fromisoformat(start_time_clean)
                else:
                    # Formato sem T: "2026-01-29 02:00:00"
                    game_time = datetime.strptime(start_time_clean[:19], '%Y-%m-%d %H:%M:%S')
                
                # Remove timezone se ainda tiver
                if game_time.tzinfo:
                    game_time = game_time.replace(tzinfo=None)
                
                if game_time >= now:
                    future_games.append(g)
                else:
                    past_games.append(g)
            except Exception as e:
                # Se erro no parse, trata como futuro (para segurança)
                print(f"   [AVISO] Erro ao parsear data '{start_time_str}': {e} - tratando como futuro")
                future_games.append(g)
        
        print(f"   [INFO] Jogos futuros: {len(future_games)} | Jogos passados: {len(past_games)}")
        
        # Busca matchup_ids já processados (com apostas empíricas)
        print("[OTIMIZACAO] Verificando jogos ja processados...")
        processed_empirical = get_processed_matchup_ids(metodo='probabilidade_empirica')
        print(f"   [OK] {len(processed_empirical)} jogos ja tem apostas empiricas no banco")
        
        # Para jogos FUTUROS: sempre processa (odds podem ter sido adicionadas/atualizadas)
        # Para jogos PASSADOS: pula se já processados (otimização)
        future_to_process = future_games  # Todos os futuros
        past_to_process = [g for g in past_games if g['matchup_id'] not in processed_empirical]
        
        games_to_process = future_to_process + past_to_process
        skipped_count = len(past_games) - len(past_to_process)
        
        if skipped_count > 0:
            print(f"   [SKIP] {skipped_count} jogos passados ja processados serao pulados")
        if len(future_to_process) > 0:
            print(f"   [REPROCESS] {len(future_to_process)} jogos futuros serao reprocessados (odds podem ter mudado)")
        
        self.stats['skipped'] = skipped_count
        
        if not games_to_process:
            print("[INFO] Nenhum jogo para processar")
        else:
            print(f"   [OK] {len(games_to_process)} jogos para processar ({len(future_to_process)} futuros + {len(past_to_process)} passados novos)")
        
        # ========================================================================
        # PASSA 1: MÉTODO EMPÍRICO (jogos não processados)
        # ========================================================================
        print("\n" + "=" * 80)
        print(f"[PASSA 1] METODO EMPIRICO - Analisando {len(games_to_process)} jogos")
        print("=" * 80)
        
        for i, game in enumerate(games_to_process, 1):
            matchup_id = game['matchup_id']
            status = game.get('status', 'unknown')
            print(f"[JOGO {i}/{len(games_to_process)}] {game['home_team']} vs {game['away_team']} ({game['league_name']}) [{status}]")
            
            try:
                # Força uso do método empírico
                analysis = self.analyzer.analyze_game(matchup_id, force_method='probabilidade_empirica')
                
                if not analysis or 'error' in analysis:
                    error_msg = analysis.get('error', 'Sem dados historicos') if analysis else 'Analise retornou None'
                    print(f"   [AVISO] Erro ou sem dados historicos: {error_msg}")
                    self.stats['errors'] += 1
                    self.error_log.append({
                        'matchup_id': matchup_id,
                        'home_team': game['home_team'],
                        'away_team': game['away_team'],
                        'league': game['league_name'],
                        'status': status,
                        'error': error_msg,
                        'pass': 'PASSA 1 (Empirico)'
                    })
                    continue
                
                self.stats['games_analyzed'] += 1
                
                # Extrai apostas com valor (método empírico)
                value_bets = self._extract_value_bets(analysis, only_empirical=True)
                
                if value_bets:
                    n = len(value_bets)
                    print(f"   [OK] {n} apostas com valor encontradas (método empírico)")
                    all_value_bets.extend(value_bets)
                    self.stats['bets_found'] += n
                    self.stats['empirical_found'] += n
                else:
                    print(f"   [INFO] Nenhuma aposta com valor")
            
            except Exception as e:
                error_msg = str(e)
                print(f"   [ERRO] Erro ao analisar jogo: {error_msg}")
                self.stats['errors'] += 1
                self.error_log.append({
                    'matchup_id': matchup_id,
                    'home_team': game['home_team'],
                    'away_team': game['away_team'],
                    'league': game['league_name'],
                    'status': status,
                    'error': f'Excecao: {error_msg}',
                    'pass': 'PASSA 1 (Empirico)'
                })
                continue
        
        # ========================================================================
        # PASSA 2: MÉTODO MACHINELEARNING (jogos com draft no histórico)
        # ========================================================================
        if include_finalized:
            print("\n" + "=" * 80)
            print("[PASSA 2] METODO MACHINELEARNING - Jogos com draft no historico (lol_history)")
            print("=" * 80)
            print("[INFO] ML so para jogos que EXISTEM no historico (match liga+times+data +-1 dia).")
            print("[INFO] Status Pinnacle nao importa (API sempre 'scheduled'). Match por lol_history.db + compositions.\n")
            
            # Busca matchup_ids já processados (com apostas ML)
            processed_ml = get_processed_matchup_ids(metodo='ml')
            print(f"[OTIMIZACAO] {len(processed_ml)} jogos ja tem apostas ML no banco")
            
            # Para jogos FUTUROS: sempre processa (odds podem ter sido adicionadas/atualizadas)
            # Para jogos PASSADOS: pula se já processados (otimização)
            future_to_process_ml = future_games  # Todos os futuros
            past_to_process_ml = [g for g in past_games if g['matchup_id'] not in processed_ml]
            
            games_to_process_ml = future_to_process_ml + past_to_process_ml
            skipped_ml = len(past_games) - len(past_to_process_ml)
            
            if skipped_ml > 0:
                print(f"   [SKIP] {skipped_ml} jogos passados ja processados (ML) serao pulados")
            if len(future_to_process_ml) > 0:
                print(f"   [REPROCESS] {len(future_to_process_ml)} jogos futuros serao reprocessados (ML - odds podem ter mudado)")
            
            if not games_to_process_ml:
                print("[INFO] Nenhum jogo para processar (ML)")
            else:
                print(f"   [OK] {len(games_to_process_ml)} jogos para processar (ML: {len(future_to_process_ml)} futuros + {len(past_to_process_ml)} passados novos)")
            
            games_with_draft = 0
            ml_bets_this_pass = 0

            for i, game in enumerate(games_to_process_ml, 1):
                matchup_id = game['matchup_id']
                status = game.get('status', 'unknown')
                print(f"[JOGO {i}/{len(games_to_process_ml)}] {game['home_team']} vs {game['away_team']} ({game['league_name']}) [{status}]")
                
                try:
                    analysis = self.analyzer.analyze_game(matchup_id, force_method='machinelearning')
                    
                    if not analysis or 'error' in analysis:
                        error_msg = analysis.get('error', 'Sem dados historicos') if analysis else 'Analise retornou None'
                        print(f"   [AVISO] Erro ou sem dados historicos: {error_msg}")
                        self.stats['errors'] += 1
                        self.error_log.append({
                            'matchup_id': matchup_id,
                            'home_team': game['home_team'],
                            'away_team': game['away_team'],
                            'league': game['league_name'],
                            'status': status,
                            'error': error_msg,
                            'pass': 'PASSA 2 (ML)'
                        })
                        continue
                    
                    self.stats['games_analyzed'] += 1
                    if analysis.get('ml_available_for_game'):
                        games_with_draft += 1
                    
                    value_bets = self._extract_value_bets(analysis, only_ml=True)
                    
                    if value_bets:
                        n = len(value_bets)
                        ml_bets_this_pass += n
                        print(f"   [OK] {n} apostas ML (empírico + ML convergiram)")
                        all_value_bets.extend(value_bets)
                        self.stats['bets_found'] += n
                        self.stats['ml_found'] += n
                    else:
                        if analysis.get('ml_available_for_game'):
                            print(f"   [INFO] Draft OK, mas nenhuma aposta com convergencia ML (divergiu ou sem valor empirico)")
                        else:
                            print(f"   [INFO] Sem match no historico (liga+times+data +-1d) ou sem compositions")
                
                except Exception as e:
                    error_msg = str(e)
                    print(f"   [ERRO] Erro ao analisar jogo: {error_msg}")
                    self.stats['errors'] += 1
                    self.error_log.append({
                        'matchup_id': matchup_id,
                        'home_team': game['home_team'],
                        'away_team': game['away_team'],
                        'league': game['league_name'],
                        'status': status,
                        'error': f'Excecao: {error_msg}',
                        'pass': 'PASSA 2 (ML)'
                    })
                    continue

            print(f"\n[RESUMO ML] Jogos com draft: {games_with_draft}/{len(games_to_process_ml)} | Apostas ML encontradas: {ml_bets_this_pass}")
            if games_with_draft == 0:
                print("[INFO] Nenhum jogo com draft. Match Pinnacle<->historico: liga+times+data +-1 dia em lol_history.db + compositions.")
        
        return all_value_bets
    
    def _extract_value_bets(self, analysis: Dict, only_ml: bool = False, only_empirical: bool = False) -> List[Dict]:
        """
        Extrai apostas com valor. Ignora markets com error e exige empirical_prob (dados reais).

        Args:
            analysis: Resultado de analyze_game
            only_ml: Se True, só apostas com método ML (empírico + ML convergiram)
            only_empirical: Se True, só apostas com método empírico

        Returns:
            Lista de apostas formatadas para salvar
        """
        value_bets = []
        
        game = analysis['game']
        markets = analysis.get('markets', [])
        
        for market_data in markets:
            if 'error' in market_data:
                continue
            market = market_data['market']
            analysis_data = market_data['analysis']

            # Apenas apostas com dados reais (empirical_prob presente)
            if analysis_data.get('empirical_prob') is None:
                continue
            if not analysis_data.get('value', False):
                continue

            # Filtro por EV mínimo (estratégia atual: EV20+)
            ev = float(analysis_data.get('expected_value') or 0.0)  # EV vem em decimal (0.20 = 20%)
            if ev < self.ev_min:
                continue

            metodo = analysis_data.get('metodo', 'probabilidade_empirica')

            if only_ml:
                # Só processa apostas com método ML (que convergiram)
                if metodo != 'ml':  # METODO_ML = 'ml'
                    continue
                # Verifica se realmente convergiu (ML aponta para mesma direção)
                ml_converges = analysis_data.get('ml_converges')
                if ml_converges is not True:
                    continue
            elif only_empirical:
                # Só processa apostas com método empírico
                if metodo != 'probabilidade_empirica':
                    continue
            
            # Extrai o mapa do market
            mapa = market.get('mapa')
            market_type = market['market_type']
            
            # Para apostas de kills, filtra apenas mapa 1 e mapa 2
            kill_markets = ['total_kills', 'total_kill_home', 'total_kill_away']
            if market_type in kill_markets:
                if mapa is None or mapa not in [1, 2]:
                    continue  # Ignora apostas de kills que não são do mapa 1 ou 2
            
            # Prepara dados da aposta
            bet_data = {
                'matchup_id': game['matchup_id'],
                'game_date': game['start_time'],
                'league_name': game['league_name'],
                'home_team': game['home_team'],
                'away_team': game['away_team'],
                'market_type': market_type,
                'mapa': mapa,  # Inclui o mapa na aposta
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
                'historical_games': market_data.get('historical_stats', {}).get('games'),
                'status': 'pending',
                'metadata': {
                    'normalization': analysis.get('normalization', {}),
                    'alinhado_media': analysis_data.get('alinhado_media')
                }
            }
            
            value_bets.append(bet_data)
        
        return value_bets
    
    def _filter_best_per_map(self, bets: List[Dict], max_per_map: int = MAX_BETS_PER_MAP) -> List[Dict]:
        """
        Filtra apostas mantendo apenas as N melhores por (matchup_id, mapa) e método.
        
        Estratégia de seleção:
        - ML: top N por expected_value (maior EV = melhor edge teórica)
        - Empírico: top N por odd_decimal (maior odd = melhor payoff)
        
        Args:
            bets: Lista de apostas para filtrar
            max_per_map: Máximo de apostas por (matchup, mapa, método_categoria)
            
        Returns:
            Lista filtrada de apostas
        """
        if max_per_map <= 0:
            return bets  # Sem limite
        
        from collections import defaultdict
        
        # Agrupa por (matchup_id, mapa, metodo_categoria)
        groups = defaultdict(list)
        for bet in bets:
            matchup_id = bet['matchup_id']
            mapa = bet.get('mapa')
            metodo = bet.get('metodo', 'probabilidade_empirica')
            # Agrupa ml/machinelearning juntos
            metodo_cat = 'ml' if metodo in ('ml', 'machinelearning') else 'empirico'
            key = (matchup_id, mapa, metodo_cat)
            groups[key].append(bet)
        
        filtered = []
        total_removed = 0
        
        for (matchup_id, mapa, metodo_cat), group_bets in groups.items():
            if len(group_bets) <= max_per_map:
                filtered.extend(group_bets)
                continue
            
            # Seleciona top N conforme estratégia do método
            if metodo_cat == 'ml':
                # ML: ordena por EV decrescente (melhor edge teórica)
                sorted_bets = sorted(group_bets, key=lambda b: float(b.get('expected_value', 0)), reverse=True)
            else:
                # Empírico: ordena por odd decrescente (melhor payoff)
                sorted_bets = sorted(group_bets, key=lambda b: float(b.get('odd_decimal', 0)), reverse=True)
            
            selected = sorted_bets[:max_per_map]
            removed = len(group_bets) - len(selected)
            total_removed += removed
            filtered.extend(selected)
        
        if total_removed > 0:
            print(f"   [FILTRO] Estratégia {max_per_map}/mapa: {len(bets)} -> {len(filtered)} apostas ({total_removed} removidas)")
            print(f"   [FILTRO] ML: top {max_per_map} por EV | Empírico: top {max_per_map} por odd")
        
        return filtered
    
    def save_bets(self, bets: List[Dict], max_per_map: int = MAX_BETS_PER_MAP) -> int:
        """
        Filtra e salva apostas no banco de dados.
        Aplica estratégia de seleção por mapa antes de salvar.
        
        Args:
            bets: Lista de apostas para salvar
            max_per_map: Máximo de apostas por (matchup, mapa, método). 0 = sem limite.
            
        Returns:
            Número de apostas salvas
        """
        if not bets:
            return 0
        
        # Aplica filtro de seleção por mapa
        filtered_bets = self._filter_best_per_map(bets, max_per_map=max_per_map)
        
        n_emp = sum(1 for b in filtered_bets if b.get('metodo') == 'probabilidade_empirica')
        n_ml = sum(1 for b in filtered_bets if b.get('metodo') == 'ml')
        print(f"\n[SALVANDO] Salvando {len(filtered_bets)} apostas no banco ({n_emp} empirico | {n_ml} ML)...")
        
        saved = 0
        duplicates = 0
        saved_bets = []  # Bets realmente salvas (novas)
        for bet in filtered_bets:
            try:
                bet_id = save_bet(bet)
                if bet_id is None:
                    duplicates += 1
                else:
                    saved += 1
                    saved_bets.append(bet)
                    self.stats['bets_saved'] += 1
            except Exception as e:
                print(f"   [ERRO] Erro ao salvar aposta: {e}")
                self.stats['errors'] += 1
        
        print(f"   [OK] {saved} apostas salvas")
        if duplicates > 0:
            print(f"   [INFO] {duplicates} apostas ja existiam (duplicatas ignoradas)")
        
        # Notifica via Telegram apenas as bets novas (salvas com sucesso)
        if saved_bets and telegram_enabled():
            print(f"   [TELEGRAM] Enviando notificacao de {len(saved_bets)} novas apostas...")
            success = notify_new_bets(saved_bets, self.stats)
            if success:
                print(f"   [TELEGRAM] Notificacao enviada!")
            else:
                print(f"   [TELEGRAM] Falha ao enviar notificacao")
        
        return saved
    
    def print_stats(self):
        """Imprime estatísticas da coleta."""
        print("\n" + "=" * 60)
        print("[ESTATISTICAS] Estatisticas da Coleta")
        print("=" * 60)
        print(f"   Jogos analisados: {self.stats['games_analyzed']}")
        if self.stats['skipped'] > 0:
            print(f"   Jogos pulados (ja processados): {self.stats['skipped']}")
        print(f"   Apostas com valor encontradas: {self.stats['bets_found']} (empirico: {self.stats['empirical_found']} | ML: {self.stats['ml_found']})")
        print(f"   Apostas salvas: {self.stats['bets_saved']}")
        if self.stats['errors'] > 0:
            print(f"   Erros: {self.stats['errors']} (jogos sem dados historicos ou com erro na analise)")
        else:
            print(f"   Erros: {self.stats['errors']}")
        print("=" * 60)
        
        # Imprime log detalhado de erros
        if self.error_log:
            print("\n" + "=" * 80)
            print("[LOG DETALHADO] Jogos com Erro")
            print("=" * 80)
            for i, error_info in enumerate(self.error_log, 1):
                print(f"\n[{i}/{len(self.error_log)}] {error_info['pass']}")
                print(f"   Matchup ID: {error_info['matchup_id']}")
                print(f"   Jogo: {error_info['home_team']} vs {error_info['away_team']}")
                print(f"   Liga: {error_info['league']}")
                print(f"   Status: {error_info['status']}")
                print(f"   Erro: {error_info['error']}")
            print("\n" + "=" * 80)


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
    parser.add_argument(
        '--ev-min',
        type=float,
        default=EV_MIN_DEFAULT,
        help='EV mínimo para salvar apostas (ex: 0.20 = 20%%)',
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
    collector = ValueBetsCollector(ev_min=args.ev_min)
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
