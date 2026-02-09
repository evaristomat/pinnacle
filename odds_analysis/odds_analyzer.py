"""
Analisador de valor nas odds comparando com histórico
"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import statistics
import sys
import pickle
import numpy as np
import logging
from logging.handlers import RotatingFileHandler

from config import (
    PINNACLE_DB,
    HISTORY_CSV,
    HISTORY_DB,
    MIN_GAMES_FOR_ANALYSIS,
    VALUE_THRESHOLD,
    MATCH_DATE_TOLERANCE_DAYS,
    ML_CONFIDENCE_THRESHOLD,
)
from normalizer import get_normalizer
from metodos_analise import METODO_PROBABILIDADE_EMPIRICA, METODO_ML

# Caminho para o modelo ML
ML_MODELS_DIR_2026 = Path(__file__).parent.parent / "machine_learning" / "modelo_2026" / "models"

# Configuração de logging
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "errors.log"


def setup_logger():
    """Configura logger para erros de normalização."""
    logger = logging.getLogger('odds_analyzer')
    logger.setLevel(logging.WARNING)
    
    # Evita duplicar handlers
    if logger.handlers:
        return logger
    
    # Handler para arquivo com rotação
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.WARNING)
    
    # Formato do log
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    
    return logger


# Logger global
logger = setup_logger()


# Cores ANSI para terminal
class Colors:
    """Códigos de cores ANSI para terminal."""
    # Reset
    RESET = '\033[0m'
    
    # Cores básicas
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Cores brilhantes
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Estilos
    BOLD = '\033[1m'
    DIM = '\033[2m'
    UNDERLINE = '\033[4m'


class OddsAnalyzer:
    """Analisa valor nas odds comparando com histórico."""
    
    def __init__(self, use_ml_model: bool = True):
        """
        Inicializa o analisador.
        
        Args:
            use_ml_model: Se True, tenta carregar e usar modelo de ML quando disponível
        """
        self.normalizer = get_normalizer()
        self.history_df: Optional[pd.DataFrame] = None
        self._load_history()
        
        # Carrega modelo ML se solicitado
        self.ml_model = None
        self.ml_scaler = None
        self.ml_champion_impacts = None
        self.ml_league_stats = None
        self.ml_feature_columns = None
        self.ml_z_calibration = None  # z-score calibrado (v2)
        self.ml_available = False
        
        if use_ml_model:
            self._load_ml_model()
    
    def _load_history(self):
        """Carrega dados históricos."""
        # Tenta CSV primeiro (mais rápido)
        if HISTORY_CSV.exists():
            try:
                print(f"{Colors.BRIGHT_BLUE}Carregando historico de:{Colors.RESET} {Colors.CYAN}{HISTORY_CSV.name}{Colors.RESET}")
                self.history_df = pd.read_csv(HISTORY_CSV, low_memory=False)
                print(f"   {Colors.BRIGHT_GREEN}OK:{Colors.RESET} {Colors.BRIGHT_GREEN}{len(self.history_df):,}{Colors.RESET} jogos carregados")
            except Exception as e:
                print(f"   [ERRO] Erro ao carregar CSV: {e}")
        
        # Fallback para SQLite se CSV não existir
        elif HISTORY_DB.exists():
            try:
                print(f"{Colors.BRIGHT_BLUE}Carregando historico de:{Colors.RESET} {HISTORY_DB.name}")
                conn = sqlite3.connect(HISTORY_DB)
                self.history_df = pd.read_sql_query(
                    "SELECT * FROM matchups ORDER BY date DESC",
                    conn
                )
                conn.close()
                print(f"   {Colors.BRIGHT_GREEN}OK:{Colors.RESET} {len(self.history_df):,} jogos carregados")
            except Exception as e:
                print(f"   [ERRO] Erro ao carregar SQLite: {e}")
        else:
            print(f"{Colors.YELLOW}[AVISO] Nenhum arquivo de historico encontrado!{Colors.RESET}")
            print(f"   Procurando em: {HISTORY_CSV} ou {HISTORY_DB}")
    
    def _load_ml_model(self):
        """Carrega modelo de ML 2026."""
        if not ML_MODELS_DIR_2026.exists():
            print(f"{Colors.YELLOW}Pasta do modelo ML 2026 nao encontrada{Colors.RESET}")
            logger.warning("Pasta do modelo ML 2026 nao encontrada")
            return

        required = ["model.pkl", "scaler.pkl", "champion_impacts.pkl",
                    "league_stats.pkl", "feature_columns.pkl"]
        missing = [f for f in required if not (ML_MODELS_DIR_2026 / f).exists()]
        if missing:
            print(f"{Colors.YELLOW}Modelo ML 2026 incompleto (faltando: {missing}){Colors.RESET}")
            logger.warning(f"Modelo ML 2026 incompleto: {missing}")
            return

        models_dir = ML_MODELS_DIR_2026
        model_year = "2026"

        try:
            with open(models_dir / "model.pkl", "rb") as f:
                self.ml_model = pickle.load(f)
            with open(models_dir / "scaler.pkl", "rb") as f:
                self.ml_scaler = pickle.load(f)
            with open(models_dir / "champion_impacts.pkl", "rb") as f:
                self.ml_champion_impacts = pickle.load(f)
            with open(models_dir / "league_stats.pkl", "rb") as f:
                self.ml_league_stats = pickle.load(f)
            with open(models_dir / "feature_columns.pkl", "rb") as f:
                self.ml_feature_columns = pickle.load(f)

            # z-score calibrado (disponivel apenas no v2)
            z_cal_path = models_dir / "z_calibration.pkl"
            if z_cal_path.exists():
                with open(z_cal_path, "rb") as f:
                    self.ml_z_calibration = pickle.load(f)
                print(f"{Colors.BRIGHT_GREEN}Modelo ML {model_year} carregado (z-score calibrado: "
                      f"k={self.ml_z_calibration['sigmoid_k']}, "
                      f"s={self.ml_z_calibration['adjust_strength']}){Colors.RESET}")
            else:
                self.ml_z_calibration = None
                print(f"{Colors.BRIGHT_GREEN}Modelo ML {model_year} carregado com sucesso{Colors.RESET}")

            self.ml_available = True
        except Exception as e:
            print(f"{Colors.BRIGHT_RED}Erro ao carregar modelo ML {model_year}: {e}{Colors.RESET}")
            logger.error(f"Erro ao carregar modelo ML {model_year}: {e}", exc_info=True)
    
    def game_exists_in_history(self, team1: str, team2: str, league: str, start_time: Optional[str] = None) -> bool:
        """
        Verifica se um jogo existe no histórico. Match por liga + times + data ±N dias.
        "Finalizado" = existe no histórico (não usar status Pinnacle; API sempre scheduled).

        Args:
            team1: Time 1 (normalizado)
            team2: Time 2 (normalizado)
            league: Liga (normalizada)
            start_time: Data/hora do jogo (Pinnacle). Usada com ±MATCH_DATE_TOLERANCE_DAYS.

        Returns:
            True se existe matchup no histórico na janela de data
        """
        if not HISTORY_DB.exists():
            return False
        
        try:
            conn = sqlite3.connect(HISTORY_DB)
            cursor = conn.cursor()
            
            if start_time:
                try:
                    game_date = pd.to_datetime(start_time)
                    delta = timedelta(days=MATCH_DATE_TOLERANCE_DAYS)
                    date_min = (game_date - delta).strftime('%Y-%m-%d 00:00:00')
                    date_max = (game_date + delta).strftime('%Y-%m-%d 23:59:59')
                    cursor.execute("""
                        SELECT COUNT(*) FROM matchups
                        WHERE league = ?
                        AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
                        AND date >= ? AND date <= ?
                    """, (league, team1, team2, team2, team1, date_min, date_max))
                except Exception as e:
                    logger.warning(f"Erro ao processar data para match: {e}")
                    cursor.execute("""
                        SELECT COUNT(*) FROM matchups
                        WHERE league = ? AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
                    """, (league, team1, team2, team2, team1))
            else:
                cursor.execute("""
                    SELECT COUNT(*) FROM matchups
                    WHERE league = ? AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
                """, (league, team1, team2, team2, team1))
            
            count = cursor.fetchone()[0]
            conn.close()
            return count > 0
        except Exception as e:
            logger.warning(f"Erro ao verificar jogo no histórico: {e}")
            return False
    
    def get_draft_data(self, team1: str, team2: str, league: str, start_time: Optional[str] = None) -> Optional[Dict]:
        """
        Busca draft (compositions) do jogo no histórico. Match por liga + times + data ±N dias.
        Não usa ID (fontes diferentes); horários Pinnacle vs histórico podem diferir.

        Args:
            team1: Time 1 (normalizado)
            team2: Time 2 (normalizado)
            league: Liga (normalizada)
            start_time: Data/hora do jogo (Pinnacle). Obrigatório.

        Returns:
            Dict com draft ou None se não encontrado
        """
        if not HISTORY_DB.exists():
            return None
        if not start_time:
            logger.warning("get_draft_data chamado sem start_time")
            return None
        
        try:
            conn = sqlite3.connect(HISTORY_DB)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            game_date = pd.to_datetime(start_time)
            delta = timedelta(days=MATCH_DATE_TOLERANCE_DAYS)
            date_min = (game_date - delta).strftime('%Y-%m-%d 00:00:00')
            date_max = (game_date + delta).strftime('%Y-%m-%d 23:59:59')
            
            try:
                cursor.execute("""
                    SELECT gameid, date FROM matchups
                    WHERE league = ? AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
                    AND date >= ? AND date <= ?
                    ORDER BY ABS(JULIANDAY(date) - JULIANDAY(?)) ASC
                    LIMIT 1
                """, (league, team1, team2, team2, team1, date_min, date_max, start_time))
            except sqlite3.OperationalError:
                cursor.execute("""
                    SELECT gameid, date FROM matchups
                    WHERE league = ? AND ((t1 = ? AND t2 = ?) OR (t1 = ? AND t2 = ?))
                    AND date >= ? AND date <= ?
                    ORDER BY date DESC
                    LIMIT 1
                """, (league, team1, team2, team2, team1, date_min, date_max))
            
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Jogo não encontrado no histórico - Liga: {league}, Times: {team1} vs {team2}, Data: {start_time}")
                conn.close()
                return None
            
            gameid = row['gameid']
            
            # Busca composições dos times
            cursor.execute("""
                SELECT team, top, jung, mid, adc, sup
                FROM compositions
                WHERE gameid = ?
            """, (gameid,))
            
            compositions = {}
            for comp_row in cursor.fetchall():
                team = comp_row['team']
                compositions[team] = {
                    'top': comp_row['top'],
                    'jung': comp_row['jung'],
                    'mid': comp_row['mid'],
                    'adc': comp_row['adc'],
                    'sup': comp_row['sup']
                }
            
            conn.close()
            
            # Verifica se temos dados completos
            if 't1' in compositions and 't2' in compositions:
                return {
                    'league': league,
                    'top_t1': compositions['t1'].get('top'),
                    'jung_t1': compositions['t1'].get('jung'),
                    'mid_t1': compositions['t1'].get('mid'),
                    'adc_t1': compositions['t1'].get('adc'),
                    'sup_t1': compositions['t1'].get('sup'),
                    'top_t2': compositions['t2'].get('top'),
                    'jung_t2': compositions['t2'].get('jung'),
                    'mid_t2': compositions['t2'].get('mid'),
                    'adc_t2': compositions['t2'].get('adc'),
                    'sup_t2': compositions['t2'].get('sup')
                }
            
            return None
        except Exception as e:
            print(f"{Colors.YELLOW}Erro ao buscar draft: {e}{Colors.RESET}")
            return None
    
    def _create_ml_features(self, game_data: Dict) -> Optional[np.ndarray]:
        """
        Cria features para o modelo ML a partir dos dados do jogo.
        
        Args:
            game_data: Dict com dados do jogo (league, top_t1, jung_t1, etc.)
            
        Returns:
            Array numpy com features ou None se não conseguir criar
        """
        if not self.ml_available:
            return None
        
        league = game_data.get('league')
        if not league:
            return None
        
        # Verifica se liga existe no modelo
        if league not in self.ml_champion_impacts:
            logger.warning(f"Liga não encontrada no modelo ML: '{league}'")
            return None
        
        # Pega impactos dos campeões
        league_impacts = self.ml_champion_impacts.get(league, {})
        
        # Normaliza nomes dos campeões (case-insensitive, remove espaços extras)
        def normalize_champ(champ):
            if not champ:
                return ''
            # Converte para string, remove espaços extras, e normaliza case
            champ_str = str(champ).strip()
            # Remove múltiplos espaços
            champ_str = ' '.join(champ_str.split())
            return champ_str
        
        # Lista para coletar campeões não encontrados (para debug)
        missing_champions = []
        
        # Função para buscar impacto e logar se não encontrar
        def get_champion_impact(champ_name: str, role: str, team: str) -> float:
            champ_norm = normalize_champ(champ_name)
            if not champ_norm:
                return 0.0
            
            # Verifica se campeão está no dicionário (case-insensitive)
            champ_found = False
            champ_impact = 0.0
            
            # Primeiro tenta match exato
            if champ_norm in league_impacts:
                champ_found = True
                champ_impact = league_impacts.get(champ_norm, 0.0)
            else:
                # Tenta match case-insensitive
                champ_lower = champ_norm.lower()
                for champ_key, impact_val in league_impacts.items():
                    if champ_key.lower() == champ_lower:
                        champ_found = True
                        champ_impact = impact_val
                        # Loga que encontrou com case diferente
                        logger.info(f"Campeão encontrado com case diferente - Original: '{champ_norm}', Modelo: '{champ_key}'")
                        break
            
            if not champ_found:
                missing_champions.append({
                    'champion': champ_norm,
                    'role': role,
                    'team': team,
                    'league': league
                })
                logger.warning(f"Campeão não encontrado no modelo ML - Liga: '{league}', Campeão: '{champ_norm}', Role: {role}, Time: {team}")
            
            return champ_impact
        
        # Impactos do Time 1
        top_t1_impact = get_champion_impact(game_data.get('top_t1', ''), 'top', 't1')
        jung_t1_impact = get_champion_impact(game_data.get('jung_t1', ''), 'jung', 't1')
        mid_t1_impact = get_champion_impact(game_data.get('mid_t1', ''), 'mid', 't1')
        adc_t1_impact = get_champion_impact(game_data.get('adc_t1', ''), 'adc', 't1')
        sup_t1_impact = get_champion_impact(game_data.get('sup_t1', ''), 'sup', 't1')
        
        # Impactos do Time 2
        top_t2_impact = get_champion_impact(game_data.get('top_t2', ''), 'top', 't2')
        jung_t2_impact = get_champion_impact(game_data.get('jung_t2', ''), 'jung', 't2')
        mid_t2_impact = get_champion_impact(game_data.get('mid_t2', ''), 'mid', 't2')
        adc_t2_impact = get_champion_impact(game_data.get('adc_t2', ''), 'adc', 't2')
        sup_t2_impact = get_champion_impact(game_data.get('sup_t2', ''), 'sup', 't2')
        
        # Média dos impactos de cada time
        team1_avg_impact = np.mean([top_t1_impact, jung_t1_impact, mid_t1_impact, adc_t1_impact, sup_t1_impact])
        team2_avg_impact = np.mean([top_t2_impact, jung_t2_impact, mid_t2_impact, adc_t2_impact, sup_t2_impact])
        
        # Diferença entre impactos dos times
        impact_diff = team1_avg_impact - team2_avg_impact
        
        # Estatísticas da liga
        if league not in self.ml_league_stats:
            logger.warning(f"Liga não encontrada nas estatísticas do modelo ML: '{league}'")
            return None
        
        league_stats = self.ml_league_stats.get(league, {})
        league_mean = league_stats.get('mean', 0.0)
        league_std = league_stats.get('std', 0.0)
        
        # Monta feature vector
        feature_dict = {
            'league_mean': league_mean,
            'league_std': league_std,
            'team1_avg_impact': team1_avg_impact,
            'team2_avg_impact': team2_avg_impact,
            'impact_diff': impact_diff,
            'top_t1_impact': top_t1_impact,
            'jung_t1_impact': jung_t1_impact,
            'mid_t1_impact': mid_t1_impact,
            'adc_t1_impact': adc_t1_impact,
            'sup_t1_impact': sup_t1_impact,
            'top_t2_impact': top_t2_impact,
            'jung_t2_impact': jung_t2_impact,
            'mid_t2_impact': mid_t2_impact,
            'adc_t2_impact': adc_t2_impact,
            'sup_t2_impact': sup_t2_impact,
        }
        
        # Adiciona codificação de liga (one-hot)
        for col in self.ml_feature_columns:
            if col.startswith('league_') and col != 'league_mean' and col != 'league_std':
                liga_name = col.replace('league_', '')
                feature_dict[col] = 1.0 if liga_name == league else 0.0
        
        # Cria array na ordem exata das feature_columns
        features = np.array([feature_dict.get(col, 0.0) for col in self.ml_feature_columns])
        
        # Loga campeões não encontrados se houver
        if missing_champions:
            logger.warning(f"Total de {len(missing_champions)} campeão(ões) não encontrado(s) no modelo para liga '{league}': {missing_champions}")
        
        return features.reshape(1, -1)
    
    def _predict_ml(self, game_data: Dict, betting_line: float) -> Optional[Dict]:
        """
        Faz predição usando o modelo ML para uma linha específica.
        
        Args:
            game_data: Dict com dados do jogo (league, top_t1, etc.)
            betting_line: Linha da aposta (ex: 25.5)
            
        Returns:
            Dict com predição ML ou None se não conseguir fazer predição
        """
        if not self.ml_available:
            return None
        
        # Cria features
        X = self._create_ml_features(game_data)
        if X is None:
            return None
        
        try:
            # Normaliza features
            X_scaled = self.ml_scaler.transform(X)
            
            # Predição base (OVER/UNDER média da liga)
            prob_over_mean = self.ml_model.predict_proba(X_scaled)[0, 1]
            
            # Confidence threshold: só retorna predição se o modelo estiver confiante
            max_prob = max(prob_over_mean, 1 - prob_over_mean)
            if max_prob < ML_CONFIDENCE_THRESHOLD:
                return None  # Modelo não confiante o suficiente (prob entre ~0.35 e ~0.65)
            
            # Ajusta probabilidade para a linha específica
            league = game_data.get('league')
            league_mean = self.ml_league_stats.get(league, {}).get('mean', 0.0)
            league_std = self.ml_league_stats.get(league, {}).get('std', 1.0)
            
            # Usa parâmetros calibrados (v2) ou fallback heurístico (v1)
            if self.ml_z_calibration:
                sigmoid_k = self.ml_z_calibration.get('sigmoid_k', 0.5)
                adjust_strength = self.ml_z_calibration.get('adjust_strength', 0.3)
            else:
                sigmoid_k = 0.5
                adjust_strength = 0.3
            
            if league_std > 0:
                z_score = (betting_line - league_mean) / league_std
                adjustment = 1 / (1 + np.exp(-z_score * sigmoid_k))
                
                if betting_line > league_mean:
                    prob_over_line = prob_over_mean * (1 - adjustment * adjust_strength)
                else:
                    prob_over_line = prob_over_mean + (1 - prob_over_mean) * adjustment * adjust_strength
                
                prob_over_line = np.clip(prob_over_line, 0.0, 1.0)
            else:
                prob_over_line = prob_over_mean
            
            prob_under_line = 1 - prob_over_line
            
            # Decisão: OVER se prob > 0.5, UNDER se prob < 0.5
            ml_prediction = 'OVER' if prob_over_line >= 0.5 else 'UNDER'
            
            return {
                'prediction': ml_prediction,
                'probability_over': prob_over_line,
                'probability_under': prob_under_line,
                'confidence': 'High' if prob_over_line >= 0.70 or prob_over_line <= 0.30 else 'Medium'
            }
        except Exception as e:
            error_msg = f"Erro ao fazer predição ML: {e}"
            print(f"{Colors.YELLOW}{error_msg}{Colors.RESET}")
            logger.error(f"Erro ao fazer predição ML - Liga: {game_data.get('league')}, Linha: {betting_line}, Erro: {e}", exc_info=True)
            return None
    
    def get_upcoming_games(self, league_filter: Optional[str] = None, exact_match: bool = False) -> List[Dict]:
        """
        Busca jogos futuros do banco Pinnacle.
        
        Args:
            league_filter: Filtro opcional de liga
            exact_match: Se True, busca match exato (evita incluir LCK CL quando buscar LCK Cup)
            
        Returns:
            Lista de jogos futuros
        """
        if not PINNACLE_DB.exists():
            print(f"{Colors.BRIGHT_RED}Banco Pinnacle nao encontrado: {PINNACLE_DB}{Colors.RESET}")
            return []
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Busca jogos que não foram finalizados
        query = """
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE status != 'final' AND status != 'Final'
        """
        
        params = []
        if league_filter:
            if exact_match:
                # Match exato (case-insensitive)
                query += " AND LOWER(league_name) = LOWER(?)"
                params.append(league_filter)
            else:
                # Busca por substring, mas exclui variações indesejadas
                query += " AND (league_name LIKE ? OR league_name LIKE ?)"
                params.extend([f"%{league_filter}%", f"%{league_filter.lower()}%"])
                
                # Se buscar "LCK Cup", exclui "LCK CL"
                if "Cup" in league_filter:
                    query += " AND league_name NOT LIKE ?"
                    params.append("%LCK CL%")
                # Se buscar "LCK CL", exclui "LCK Cup"
                elif "CL" in league_filter and "Cup" not in league_filter:
                    query += " AND league_name NOT LIKE ?"
                    params.append("%LCK Cup%")
        
        query += " ORDER BY start_time ASC"
        
        cursor.execute(query, params)
        games = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        print(f"{Colors.BRIGHT_GREEN}Encontrados {len(games)} jogos futuros{Colors.RESET}")
        return games
    
    def get_all_games(self, league_filter: Optional[str] = None) -> List[Dict]:
        """
        Busca TODOS os jogos do banco Pinnacle (futuros e passados).
        
        Args:
            league_filter: Filtro opcional de liga
            
        Returns:
            Lista de jogos (futuros e passados)
        """
        if not PINNACLE_DB.exists():
            return []
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = """
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE 1=1
        """
        params = []
        
        if league_filter:
            query += " AND league_name LIKE ?"
            params.append(f"%{league_filter}%")
        
        query += " ORDER BY start_time ASC"
        
        cursor.execute(query, params)
        games = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return games
    
    def get_finalized_games_with_draft(self, league_filter: Optional[str] = None) -> List[Dict]:
        """
        Busca jogos do banco Pinnacle que já estão finalizados no histórico e têm draft disponível.
        Esses jogos podem ser analisados com método ML para análise retrospectiva.
        
        Args:
            league_filter: Filtro opcional de liga
            
        Returns:
            Lista de jogos finalizados que têm draft
        """
        if not PINNACLE_DB.exists():
            return []
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Busca TODOS os jogos do banco (incluindo antigos)
        query = """
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE 1=1
        """
        
        params = []
        if league_filter:
            query += " AND (league_name LIKE ? OR league_name LIKE ?)"
            params.extend([f"%{league_filter}%", f"%{league_filter.lower()}%"])
        
        query += " ORDER BY start_time DESC"
        
        cursor.execute(query, params)
        all_games = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        # Filtra jogos que estão no histórico e têm draft
        finalized_with_draft = []
        
        for game in all_games:
            # Normaliza nomes
            league_norm = self.normalizer.normalize_league_name(game['league_name'])
            team1_norm = self.normalizer.normalize_team_name(game['home_team'], league_norm)
            team2_norm = self.normalizer.normalize_team_name(game['away_team'], league_norm)
            
            if not all([league_norm, team1_norm, team2_norm]):
                continue
            
            # Verifica se jogo existe no histórico
            exists = self.game_exists_in_history(team1_norm, team2_norm, league_norm, game['start_time'])
            
            if exists:
                # Verifica se tem draft
                draft_data = self.get_draft_data(team1_norm, team2_norm, league_norm, game['start_time'])
                
                if draft_data:
                    finalized_with_draft.append(game)
        
        print(f"{Colors.BRIGHT_GREEN}Encontrados {len(finalized_with_draft)} jogos finalizados com draft{Colors.RESET}")
        return finalized_with_draft
    
    def get_total_kills_markets(self, matchup_id: int) -> List[Dict]:
        """
        Busca markets de total_kills para um jogo.
        
        Args:
            matchup_id: ID do matchup
            
        Returns:
            Lista de markets de total_kills
        """
        if not PINNACLE_DB.exists():
            return []
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT market_type, mapa, line_value, side, odd_decimal, is_alternate
            FROM markets
            WHERE matchup_id = ? AND market_type = 'total_kills'
            ORDER BY mapa, line_value, side
        """, (matchup_id,))
        
        markets = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return markets
    
    def get_historical_stats(
        self,
        team1: str,
        team2: str,
        league: str
    ) -> Optional[Dict]:
        """
        Busca estatísticas históricas de total_kills dos últimos N mapas de cada time.
        Cada mapa é considerado um jogo separado.
        Não usa confronto direto, apenas estatísticas individuais dos times.
        
        Args:
            team1: Nome do time 1 (normalizado)
            team2: Nome do time 2 (normalizado)
            league: Nome da liga (normalizado)
            
        Returns:
            Dicionário com estatísticas ou None
        """
        if self.history_df is None or self.history_df.empty:
            return None
        
        # Filtra por liga
        league_df = self.history_df[self.history_df['league'] == league].copy()
        
        if league_df.empty:
            return None
        
        # Busca TODOS os mapas onde cada time participou (cada linha = 1 mapa)
        # Time 1: mapas onde jogou como t1 ou t2
        team1_matches = league_df[
            (league_df['t1'] == team1) | (league_df['t2'] == team1)
        ].copy()
        
        # Time 2: mapas onde jogou como t1 ou t2
        team2_matches = league_df[
            (league_df['t1'] == team2) | (league_df['t2'] == team2)
        ].copy()
        
        # Combina todos os mapas (cada linha é um mapa)
        all_matches = pd.concat([team1_matches, team2_matches]).drop_duplicates()
        
        if all_matches.empty:
            return None
        
        # Ordena por data (mais recentes primeiro) para pegar últimos N mapas
        if 'date' in all_matches.columns:
            try:
                all_matches['date'] = pd.to_datetime(all_matches['date'], errors='coerce')
                all_matches = all_matches.sort_values('date', ascending=False)
            except:
                pass  # Se não conseguir ordenar por data, continua
        
        # Remove valores NaN de total_kills
        total_kills = all_matches['total_kills'].dropna()
        
        if total_kills.empty:
            return None
        
        # Lista de total_kills para probabilidade empírica
        total_kills_values = total_kills.astype(int).tolist()
        
        # Calcula estatísticas (usa todos os mapas disponíveis, mesmo se < 5)
        stats = {
            'games': len(total_kills),
            'match_type': 'individual_maps',  # Cada mapa é um jogo
            'team1_games': len(team1_matches),
            'team2_games': len(team2_matches),
            'mean': float(total_kills.mean()),
            'median': float(total_kills.median()),
            'std': float(total_kills.std()) if len(total_kills) > 1 else 0.0,
            'min': int(total_kills.min()),
            'max': int(total_kills.max()),
            'q25': float(total_kills.quantile(0.25)) if len(total_kills) > 1 else float(total_kills.iloc[0]),
            'q75': float(total_kills.quantile(0.75)) if len(total_kills) > 1 else float(total_kills.iloc[0]),
            'meets_minimum': len(total_kills) >= MIN_GAMES_FOR_ANALYSIS,
            'total_kills_values': total_kills_values
        }
        
        return stats
    
    def calculate_implied_probability(self, odd_decimal: float) -> float:
        """
        Calcula probabilidade implícita de uma odd.
        
        Args:
            odd_decimal: Odd em formato decimal
            
        Returns:
            Probabilidade (0-1)
        """
        if odd_decimal <= 0:
            return 0.0
        return 1.0 / odd_decimal
    
    def calculate_expected_value(
        self,
        line_value: float,
        side: str,
        odd_decimal: float,
        historical_mean: float,
        historical_std: float
    ) -> Dict:
        """
        Calcula valor esperado (EV) de uma aposta.
        
        Args:
            line_value: Valor da linha (ex: 25.5)
            side: Lado da aposta ('over' ou 'under')
            odd_decimal: Odd em formato decimal
            historical_mean: Média histórica de total_kills
            historical_std: Desvio padrão histórico
            
        Returns:
            Dicionário com análise de valor
        """
        # Probabilidade implícita da odd
        implied_prob = self.calculate_implied_probability(odd_decimal)
        
        # Estima probabilidade real baseada no histórico (assumindo distribuição normal)
        # Para simplificar, usamos a média histórica
        if side.lower() == 'over':
            # Probabilidade de ser over baseada na média histórica
            # Se média > linha, probabilidade > 50%
            if historical_mean > line_value:
                # Estima probabilidade usando z-score aproximado
                z_score = (historical_mean - line_value) / max(historical_std, 1.0)
                # Aproximação simples: quanto maior o z-score, maior a probabilidade
                real_prob = min(0.95, max(0.05, 0.5 + (z_score * 0.15)))
            else:
                z_score = (line_value - historical_mean) / max(historical_std, 1.0)
                real_prob = min(0.95, max(0.05, 0.5 - (z_score * 0.15)))
        else:  # under
            if historical_mean < line_value:
                z_score = (line_value - historical_mean) / max(historical_std, 1.0)
                real_prob = min(0.95, max(0.05, 0.5 + (z_score * 0.15)))
            else:
                z_score = (historical_mean - line_value) / max(historical_std, 1.0)
                real_prob = min(0.95, max(0.05, 0.5 - (z_score * 0.15)))
        
        # Expected Value = (Probabilidade Real * Odd) - 1
        ev = (real_prob * odd_decimal) - 1.0
        
        return {
            'implied_probability': implied_prob,
            'estimated_real_probability': real_prob,
            'expected_value': ev,
            'value': ev >= VALUE_THRESHOLD,
            'edge': ev * 100  # Edge em porcentagem
        }
    
    def analyze_game(self, matchup_id: int, force_method: Optional[str] = None) -> Optional[Dict]:
        """
        Analisa um jogo buscando valor nas odds. Apenas dados reais; sem fallbacks nem aproximações.

        Independência dos métodos (sem relação funcional um com o outro):
        - Empírico (force_method='probabilidade_empirica'): usa APENAS Pinnacle + data_transformed.
          Não acessa lol_history, compositions, nem modelo ML. Probabilidade e EV só com
          total_kills_values. Sem total_kills_values → error.
        - ML (force_method='machinelearning'): usa Pinnacle + data_transformed + lol_history
          (match + draft) + modelo ML. Valor só se empírico e ML convergem. Exige draft.

        Orquestração (collect_value_bets): PASSA 1 só empírico; PASSA 2 só ML. Chamadas
        separadas, sem estado compartilhado entre passes.

        Args:
            matchup_id: ID do matchup
            force_method: 'probabilidade_empirica' | 'machinelearning' | None (automático)

        Returns:
            Dicionário com análise completa ou None
        """
        if not PINNACLE_DB.exists():
            return None
        
        conn = sqlite3.connect(PINNACLE_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Busca informações do jogo
        cursor.execute("""
            SELECT matchup_id, league_name, home_team, away_team, start_time, status
            FROM games
            WHERE matchup_id = ?
        """, (matchup_id,))
        
        game_row = cursor.fetchone()
        if not game_row:
            conn.close()
            return None
        
        game = dict(game_row)
        conn.close()
        
        # Normaliza nomes
        league_norm = self.normalizer.normalize_league_name(game['league_name'])
        team1_norm = self.normalizer.normalize_team_name(game['home_team'], league_norm)
        team2_norm = self.normalizer.normalize_team_name(game['away_team'], league_norm)
        
        # Loga erros de normalização
        if not league_norm:
            logger.warning(f"Liga não encontrada na normalização - Pinnacle: '{game['league_name']}'")
        
        if not team1_norm:
            logger.warning(f"Time não encontrado na normalização - Pinnacle: '{game['home_team']}', Liga: '{game['league_name']}'")
        
        if not team2_norm:
            logger.warning(f"Time não encontrado na normalização - Pinnacle: '{game['away_team']}', Liga: '{game['league_name']}'")
        
        if not all([league_norm, team1_norm, team2_norm]):
            return {
                'game': game,
                'normalization': {
                    'league': {'pinnacle': game['league_name'], 'normalized': league_norm},
                    'team1': {'pinnacle': game['home_team'], 'normalized': team1_norm},
                    'team2': {'pinnacle': game['away_team'], 'normalized': team2_norm},
                },
                'error': 'Não foi possível normalizar todos os nomes',
                'markets': []
            }
        
        # Busca markets de total_kills
        markets = self.get_total_kills_markets(matchup_id)
        
        # Busca histórico
        historical_stats = self.get_historical_stats(team1_norm, team2_norm, league_norm)
        
        # Método empírico: NUNCA acessa histórico/draft (lol_history). Totalmente independente do ML.
        # Método ML: usa game_exists_in_history + get_draft_data (match liga+times+data +-1d).
        game_exists_in_history = False
        draft_data = None
        ml_available_for_game = False
        
        force_ml = force_method in (METODO_ML, 'machinelearning')
        if force_method != METODO_PROBABILIDADE_EMPIRICA and self.ml_available:
            game_exists_in_history = self.game_exists_in_history(team1_norm, team2_norm, league_norm, game['start_time'])
            if not game_exists_in_history:
                if not force_ml:
                    print(f"{Colors.CYAN}[INFO]{Colors.RESET} Jogo nao encontrado no historico (match liga+times+data +-{MATCH_DATE_TOLERANCE_DAYS}d). ML so para jogos que existem no historico com draft.{Colors.RESET}")
            else:
                draft_data = self.get_draft_data(team1_norm, team2_norm, league_norm, game['start_time'])
                if draft_data:
                    ml_available_for_game = True
                    if not force_ml:
                        print(f"{Colors.BRIGHT_GREEN}[ML ATIVO]{Colors.RESET} Jogo encontrado no historico (match +-{MATCH_DATE_TOLERANCE_DAYS}d) - draft OK. ML + empirico.{Colors.RESET}")
                elif not force_ml:
                    print(f"{Colors.YELLOW}[INFO]{Colors.RESET} Jogo no historico mas sem draft (compositions) - usando apenas empirico.{Colors.RESET}")
        
        # Analisa cada market
        analyzed_markets = []
        for market in markets:
            if not historical_stats:
                analyzed_markets.append({
                    'market': market,
                    'error': 'Dados históricos insuficientes'
                })
                continue
            
            # Método empírico: apenas dados reais (total_kills_values). Sem fallbacks.
            vals = historical_stats.get('total_kills_values', [])
            line_val = market['line_value']
            mean_val = historical_stats['mean']
            empirical_prob = None

            if not vals or len(vals) == 0:
                analyzed_markets.append({
                    'market': market,
                    'historical_stats': historical_stats,
                    'error': 'Dados reais insuficientes (total_kills_values vazio)'
                })
                continue

            n = len(vals)
            if market['side'].lower() == 'over':
                empirical_prob = sum(1 for x in vals if x > line_val) / n
                alinhado = line_val < mean_val  # OVER em linha abaixo da média = a favor
            else:
                empirical_prob = sum(1 for x in vals if x < line_val) / n
                alinhado = line_val > mean_val  # UNDER em linha acima da média = a favor
            empirical_prob = round(empirical_prob, 4)

            # EV e valor apenas com probabilidade empírica real (sem aproximações)
            if empirical_prob is not None:
                # MÉTODO 1: Probabilidade Empírica
                # Usa probabilidade empírica real calculada dos dados históricos
                implied_prob = self.calculate_implied_probability(market['odd_decimal'])
                ev = (empirical_prob * market['odd_decimal']) - 1.0
                
                # Valor existe se: prob_histórica > prob_implícita (1/odd)
                # Isso é equivalente a: prob_histórica × odd > 1, ou seja, EV > 0
                # Verifica se há valor: prob histórica maior que prob implícita E EV acima do threshold
                has_value_empirical = (empirical_prob > implied_prob) and (ev >= VALUE_THRESHOLD)
                
                # Inicializa variáveis ML
                ml_prediction = None
                ml_probability = None
                ml_confidence = None
                ml_converges = None
                has_value_ml = False
                metodo_nome = METODO_PROBABILIDADE_EMPIRICA
                
                # LÓGICA BASEADA EM force_method
                if force_method == METODO_PROBABILIDADE_EMPIRICA:
                    # Força método empírico: usa apenas valor empírico (ignora ML completamente)
                    has_value = has_value_empirical
                    metodo_nome = METODO_PROBABILIDADE_EMPIRICA
                elif force_ml:
                    # Força método ML: só considera valor se ML convergiu
                    # Primeiro precisa fazer predição ML
                    if ml_available_for_game and draft_data:
                        ml_result = self._predict_ml(draft_data, line_val)
                        if ml_result:
                            ml_prediction = ml_result['prediction']
                            ml_probability = ml_result['probability_over'] if market['side'].lower() == 'over' else ml_result['probability_under']
                            ml_confidence = ml_result['confidence']
                            
                            # Verifica convergência: empírico indica valor E ML aponta para mesmo lado
                            empirical_side = market['side'].upper()
                            ml_converges = (ml_prediction == empirical_side)
                    
                    # Só considera valor se ML convergiu E empírico tem valor
                    if ml_available_for_game and ml_converges is True and has_value_empirical:
                        has_value = True
                        metodo_nome = METODO_ML
                    else:
                        has_value = False
                        metodo_nome = METODO_ML  # Mesmo sem valor, marca como ML
                else:
                    # Lógica automática (comportamento padrão - igual ao commit original)
                    # MÉTODO ML: Verifica se modelo ML também aponta para mesma direção
                    # Só usa ML se draft estiver disponível (jogo ao vivo ou finalizado)
                    
                    # Se temos modelo ML e draft disponível, faz predição
                    if ml_available_for_game and draft_data:
                        ml_result = self._predict_ml(draft_data, line_val)
                        if ml_result:
                            ml_prediction = ml_result['prediction']
                            ml_probability = ml_result['probability_over'] if market['side'].lower() == 'over' else ml_result['probability_under']
                            ml_confidence = ml_result['confidence']
                            
                            # Verifica convergência: empírico indica valor E ML aponta para mesmo lado
                            empirical_side = market['side'].upper()
                            ml_converges = (ml_prediction == empirical_side)
                            
                            # Só considera aposta boa se ambos convergirem
                            if has_value_empirical and ml_converges:
                                metodo_nome = METODO_ML
                                has_value_ml = True
                            elif has_value_empirical and not ml_converges:
                                # Empírico indica valor mas ML diverge - não considera como aposta boa
                                has_value_ml = False
                    
                    # Se não tem ML disponível para este jogo, usa apenas método empírico
                    if not ml_available_for_game or not draft_data:
                        has_value_ml = has_value_empirical
                    
                    # Decide qual valor usar
                    # Para jogos futuros: sempre usa apenas empírico
                    # Para jogos ao vivo/finalizados: usa ML se disponível, senão empírico
                    has_value = has_value_ml if ml_available_for_game else has_value_empirical
                
                analysis = {
                    'metodo': metodo_nome,
                    'implied_probability': implied_prob,
                    'estimated_real_probability': empirical_prob,
                    'expected_value': ev,
                    'value': has_value,
                    'edge': ev * 100,
                    'empirical_prob': empirical_prob,
                    'alinhado_media': alinhado,
                    'ml_prediction': ml_prediction,
                    'ml_probability': ml_probability,
                    'ml_confidence': ml_confidence,
                    'ml_converges': ml_prediction == market['side'].upper() if ml_prediction else None
                }
            # Sem fallback: análise apenas com dados reais (total_kills_values)

            analyzed_markets.append({
                'market': market,
                'historical_stats': historical_stats,
                'analysis': analysis
            })
        
        return {
            'game': game,
            'normalization': {
                'league': {'pinnacle': game['league_name'], 'normalized': league_norm},
                'team1': {'pinnacle': game['home_team'], 'normalized': team1_norm},
                'team2': {'pinnacle': game['away_team'], 'normalized': team2_norm},
            },
            'historical_stats': historical_stats,
            'markets': analyzed_markets,
            'game_exists_in_history': game_exists_in_history,  # Indica se jogo já aconteceu
            'ml_available_for_game': ml_available_for_game  # Indica se ML está disponível para este jogo
        }


def print_analysis(analysis: Dict):
    """Imprime análise formatada com cores."""
    game = analysis['game']
    norm = analysis['normalization']
    
    # Cabeçalho
    # Verifica se jogo existe no histórico (já aconteceu)
    game_exists = analysis.get('game_exists_in_history', False)
    ml_available = analysis.get('ml_available_for_game', False)
    
    status_text = "FUTURO" if not game_exists else "AO VIVO/FINALIZADO"
    status_color = Colors.YELLOW if not game_exists else Colors.BRIGHT_GREEN
    
    ml_status_text = "Apenas metodo empirico" if not game_exists else ("ML + Empirico" if ml_available else "ML disponivel se draft encontrado")
    
    print(f"\n{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BRIGHT_WHITE}JOGO: {Colors.BRIGHT_CYAN}{game['home_team']}{Colors.RESET} {Colors.WHITE}vs{Colors.RESET} {Colors.BRIGHT_CYAN}{game['away_team']}{Colors.RESET}")
    print(f"{Colors.BRIGHT_BLUE}Liga:{Colors.RESET} {game['league_name']} {Colors.YELLOW}->{Colors.RESET} {Colors.BRIGHT_GREEN}{norm['league']['normalized']}{Colors.RESET}")
    print(f"{Colors.BRIGHT_BLUE}Data:{Colors.RESET} {game['start_time']}")
    print(f"{Colors.BRIGHT_BLUE}Status:{Colors.RESET} {status_color}{status_text}{Colors.RESET} {Colors.CYAN}({ml_status_text}){Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'=' * 80}{Colors.RESET}")
    
    # Normalização
    print(f"\n{Colors.BRIGHT_BLUE}Normalizacao:{Colors.RESET}")
    print(f"   {Colors.CYAN}Time 1:{Colors.RESET} {game['home_team']} {Colors.YELLOW}->{Colors.RESET} {Colors.BRIGHT_GREEN}{norm['team1']['normalized']}{Colors.RESET}")
    print(f"   {Colors.CYAN}Time 2:{Colors.RESET} {game['away_team']} {Colors.YELLOW}->{Colors.RESET} {Colors.BRIGHT_GREEN}{norm['team2']['normalized']}{Colors.RESET}")
    
    if 'error' in analysis:
        print(f"\n{Colors.BRIGHT_RED}ERRO: {analysis['error']}{Colors.RESET}")
        return
    
    if analysis['historical_stats']:
        stats = analysis['historical_stats']
        print(f"\n{Colors.BRIGHT_BLUE}Estatisticas Historicas{Colors.RESET} {Colors.BRIGHT_CYAN}({stats['games']} mapas analisados){Colors.RESET}:")
        print(f"   {Colors.CYAN}Time 1:{Colors.RESET} {stats.get('team1_games', 0)} mapas {Colors.WHITE}|{Colors.RESET} {Colors.CYAN}Time 2:{Colors.RESET} {stats.get('team2_games', 0)} mapas")
        
        if not stats.get('meets_minimum', False):
            print(f"   {Colors.BRIGHT_YELLOW}[AVISO]{Colors.RESET} {Colors.YELLOW}Nao atingiu minimo de {MIN_GAMES_FOR_ANALYSIS} jogos (apenas {stats['games']} mapas){Colors.RESET}")
        
        print(f"   {Colors.CYAN}Media:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['mean']:.2f}{Colors.RESET} kills")
        print(f"   {Colors.CYAN}Mediana:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['median']:.2f}{Colors.RESET} kills")
        print(f"   {Colors.CYAN}Desvio Padrao:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['std']:.2f}{Colors.RESET}")
        print(f"   {Colors.CYAN}Range:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['min']}{Colors.RESET} - {Colors.BRIGHT_GREEN}{stats['max']}{Colors.RESET} kills")
        if stats['games'] > 1:
            print(f"   {Colors.CYAN}Q25:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['q25']:.2f}{Colors.RESET} {Colors.WHITE}|{Colors.RESET} {Colors.CYAN}Q75:{Colors.RESET} {Colors.BRIGHT_GREEN}{stats['q75']:.2f}{Colors.RESET}")
    else:
        print(f"\n{Colors.BRIGHT_YELLOW}[AVISO]{Colors.RESET} {Colors.YELLOW}Dados historicos insuficientes{Colors.RESET}")
        return
    
    print(f"\n{Colors.BOLD}{Colors.BRIGHT_BLUE}Analise de Markets:{Colors.RESET}")
    print(f"{Colors.BRIGHT_CYAN}{'-' * 80}{Colors.RESET}")
    
    # Conta apostas com valor
    value_count = sum(1 for item in analysis['markets'] 
                     if 'analysis' in item and item['analysis'].get('value', False))
    
    if value_count > 0:
        print(f"{Colors.BRIGHT_GREEN}[OK] {value_count} aposta(s) com valor identificada(s){Colors.RESET}\n")
    
    for item in analysis['markets']:
        if 'error' in item:
            print(f"   {Colors.BRIGHT_YELLOW}[AVISO]{Colors.RESET} {Colors.YELLOW}{item['error']}{Colors.RESET}")
            continue
        
        market = item['market']
        analysis_data = item['analysis']
        
        side_str = market['side'].upper()
        line = market['line_value']
        odd = market['odd_decimal']
        ev = analysis_data['expected_value']
        edge = analysis_data['edge']
        has_value = analysis_data['value']
        
        # Cores baseadas no valor
        if has_value:
            value_color = Colors.BRIGHT_GREEN
            value_indicator = f"{Colors.BRIGHT_GREEN}[VALOR]{Colors.RESET}"
            ev_color = Colors.BRIGHT_GREEN
        elif ev < -0.10:  # EV muito negativo
            value_color = Colors.BRIGHT_RED
            value_indicator = f"{Colors.BRIGHT_RED}[Sem valor]{Colors.RESET}"
            ev_color = Colors.BRIGHT_RED
        else:  # EV próximo de zero ou ligeiramente negativo
            value_color = Colors.YELLOW
            value_indicator = f"{Colors.YELLOW}[Sem valor]{Colors.RESET}"
            ev_color = Colors.YELLOW
        
        # Linha principal do market
        print(f"\n   {value_indicator} {Colors.WHITE}|{Colors.RESET} {Colors.BRIGHT_CYAN}{side_str} {line:.1f}{Colors.RESET} {Colors.WHITE}|{Colors.RESET} Odd: {Colors.BRIGHT_WHITE}{odd:.2f}{Colors.RESET}")
        
        # Detalhes
        implied_prob = analysis_data['implied_probability'] * 100
        real_prob = analysis_data['estimated_real_probability'] * 100
        
        # Cor da probabilidade estimada (verde se maior que implícita, vermelho se menor)
        if real_prob > implied_prob + 2:
            prob_color = Colors.BRIGHT_GREEN
        elif real_prob < implied_prob - 2:
            prob_color = Colors.BRIGHT_RED
        else:
            prob_color = Colors.YELLOW
        
        print(f"      {Colors.CYAN}Prob. Implicita:{Colors.RESET} {Colors.WHITE}{implied_prob:.1f}%{Colors.RESET}")
        print(f"      {Colors.CYAN}Prob. Estimada:{Colors.RESET} {prob_color}{real_prob:.1f}%{Colors.RESET}")
        print(f"      {Colors.CYAN}Expected Value:{Colors.RESET} {ev_color}{ev*100:+.2f}%{Colors.RESET}")
        print(f"      {Colors.CYAN}Edge:{Colors.RESET} {ev_color}{edge:+.2f}%{Colors.RESET}")
        
        # Informações do modelo ML (se disponível)
        ml_prediction = analysis_data.get('ml_prediction')
        ml_probability = analysis_data.get('ml_probability')
        ml_confidence = analysis_data.get('ml_confidence')
        ml_converges = analysis_data.get('ml_converges')
        metodo = analysis_data.get('metodo', METODO_PROBABILIDADE_EMPIRICA)
        
        if ml_prediction is not None:
            ml_color = Colors.BRIGHT_GREEN if ml_converges else Colors.BRIGHT_RED
            converge_str = "Converge" if ml_converges else "Diverge"
            print(f"      {Colors.CYAN}Modelo ML:{Colors.RESET} {ml_color}{ml_prediction}{Colors.RESET} "
                  f"({ml_probability*100:.1f}%) {Colors.YELLOW}|{Colors.RESET} {ml_color}{converge_str}{Colors.RESET}")
            if metodo == METODO_ML:
                print(f"      {Colors.BRIGHT_GREEN}[METODO ML]{Colors.RESET} {Colors.BRIGHT_GREEN}Empirico + ML convergem{Colors.RESET}")
        elif metodo == METODO_ML:
            print(f"      {Colors.BRIGHT_GREEN}[METODO ML]{Colors.RESET} {Colors.BRIGHT_GREEN}Empirico + ML convergem{Colors.RESET}")
    
    # Resumo final apenas com apostas com valor (sem duplicatas)
    value_bets = []
    seen = set()
    
    for item in analysis['markets']:
        if 'analysis' in item and item['analysis'].get('value', False):
            market = item['market']
            analysis_data = item['analysis']
            
            # Cria chave única para evitar duplicatas
            key = (market['side'].upper(), market['line_value'], market['odd_decimal'])
            if key not in seen:
                seen.add(key)
                value_bets.append({
                    'side': market['side'].upper(),
                    'line': market['line_value'],
                    'odd': market['odd_decimal'],
                    'ev': analysis_data['expected_value'],
                    'edge': analysis_data['edge'],
                    'empirical_prob': analysis_data.get('empirical_prob'),
                    'alinhado_media': analysis_data.get('alinhado_media'),
                    'metodo': analysis_data.get('metodo', METODO_PROBABILIDADE_EMPIRICA),
                    'ml_prediction': analysis_data.get('ml_prediction'),
                    'ml_converges': analysis_data.get('ml_converges'),
                })
    
    if value_bets:
        stats = analysis.get('historical_stats') or {}
        mean_k = stats.get('mean')
        
        has_over = any(b['side'] == 'OVER' for b in value_bets)
        has_under = any(b['side'] == 'UNDER' for b in value_bets)
        conflito = has_over and has_under
        
        # Direção sugerida pela média
        if mean_k is not None:
            if mean_k >= 30:
                direcao = "OVER"
                motivo = "tendencia de jogos altos"
            elif mean_k <= 26:
                direcao = "UNDER"
                motivo = "tendencia de jogos baixos"
            else:
                direcao = "Neutro"
                motivo = "jogos intermediarios"
        else:
            direcao = None
            motivo = ""
        
        print(f"\n{Colors.BOLD}{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
        print(f"{Colors.BOLD}{Colors.BRIGHT_GREEN}RESUMO: Apostas com Valor ({len(value_bets)} encontradas){Colors.RESET}")
        print(f"{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}")
        print(f"   {Colors.BRIGHT_CYAN}Jogo:{Colors.RESET} {Colors.BRIGHT_WHITE}{game['home_team']}{Colors.RESET} {Colors.WHITE}vs{Colors.RESET} {Colors.BRIGHT_WHITE}{game['away_team']}{Colors.RESET} {Colors.YELLOW}({game['league_name']}){Colors.RESET}")
        
        if mean_k is not None:
            print(f"   {Colors.BRIGHT_CYAN}Media historica:{Colors.RESET} {Colors.BRIGHT_WHITE}{mean_k:.1f}{Colors.RESET} kills  {Colors.CYAN}|{Colors.RESET}  {Colors.BRIGHT_CYAN}Direcao sugerida:{Colors.RESET} {Colors.BRIGHT_WHITE}{direcao}{Colors.RESET} ({motivo})")
        
        if conflito:
            print(f"   {Colors.BRIGHT_YELLOW}[ATENCAO]{Colors.RESET} {Colors.YELLOW}Ha apostas OVER e UNDER com valor. Sao excludentes - defina uma direcao antes de apostar.{Colors.RESET}")
        
        if direcao and direcao != "Neutro" and conflito:
            print(f"   {Colors.BRIGHT_GREEN}Recomendacao:{Colors.RESET} Priorize {Colors.BRIGHT_GREEN}{direcao}{Colors.RESET} (alinhado com a media historica).")
        
        print()
        
        # Ordena: primeiro alinhadas com a média, depois por EV (maior primeiro)
        def _ordem(b):
            al = 0 if b.get('alinhado_media') is True else 1
            return (-al, -b['ev'])
        value_bets.sort(key=_ordem)
        
        for i, bet in enumerate(value_bets, 1):
            ev_pct = bet['ev'] * 100
            edge_pct = bet['edge']
            
            if ev_pct > 20:
                highlight = Colors.BOLD
            else:
                highlight = ""
            
            # Prob. histórica e alinhamento
            emp = bet.get('empirical_prob')
            emp_str = f" | Prob. hist. {emp*100:.1f}%" if emp is not None else ""
            al = bet.get('alinhado_media')
            if al is True:
                al_str = f" {Colors.BRIGHT_GREEN}| A favor da media{Colors.RESET}"
            elif al is False:
                al_str = f" {Colors.YELLOW}| Contra a media{Colors.RESET}"
            else:
                al_str = ""
            
            # Método usado
            metodo = bet.get('metodo', METODO_PROBABILIDADE_EMPIRICA)
            if metodo == METODO_ML:
                metodo_str = f" {Colors.BRIGHT_GREEN}| [ML]{Colors.RESET}"
            else:
                metodo_str = ""
            
            # Convergência ML
            ml_converges = bet.get('ml_converges')
            if ml_converges is not None:
                ml_str = f" {Colors.BRIGHT_GREEN}| ML: OK{Colors.RESET}" if ml_converges else f" {Colors.YELLOW}| ML: X{Colors.RESET}"
            else:
                ml_str = ""
            
            print(f"   {Colors.CYAN}{i}.{Colors.RESET} {Colors.BRIGHT_GREEN}[VALOR]{Colors.RESET} "
                  f"{Colors.BRIGHT_CYAN}{bet['side']} {bet['line']:.1f}{Colors.RESET} "
                  f"{Colors.WHITE}@ {Colors.BRIGHT_WHITE}{bet['odd']:.2f}{Colors.RESET} "
                  f"{highlight}{Colors.BRIGHT_GREEN}(EV: {ev_pct:+.2f}% | Edge: {edge_pct:+.2f}%){Colors.RESET}"
                  f"{emp_str}{al_str}{metodo_str}{ml_str}")
        
        print(f"{Colors.BRIGHT_GREEN}{'=' * 80}{Colors.RESET}\n")
