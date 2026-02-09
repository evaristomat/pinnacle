"""
Sistema de matching de jogos entre Pinnacle e histórico para atualizar resultados
"""
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json

# Importa config local do bets_tracker (não do odds_analysis)
import sys
from pathlib import Path
CURRENT_DIR = Path(__file__).parent
# Garante que estamos usando o config local
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from config import (
    PINNACLE_DB,
    HISTORY_CSV,
    HISTORY_DB,
    DATE_TOLERANCE_HOURS,
    MIN_CONFIDENCE_SCORE,
    LIGAS_TIMES_JSON
)
from bets_database import get_name_corrections, save_name_correction

# Importa normalizer local do bets_tracker (não do odds_analysis)
import importlib.util
normalizer_path = CURRENT_DIR / "normalizer.py"
normalizer_spec = importlib.util.spec_from_file_location("bets_normalizer", normalizer_path)
bets_normalizer_module = importlib.util.module_from_spec(normalizer_spec)
normalizer_spec.loader.exec_module(bets_normalizer_module)
ResultNormalizer = bets_normalizer_module.ResultNormalizer


class ResultMatcher:
    """Faz matching de jogos entre Pinnacle e histórico para atualizar resultados."""
    
    def __init__(self):
        """Inicializa o matcher."""
        self.normalizer = ResultNormalizer()
        self.history_df: Optional[pd.DataFrame] = None
        self.corrections = get_name_corrections()
        self._load_history()
    
    def _load_history(self):
        """
        Carrega dados históricos para matching.
        SQLite (lol_history.db) é a fonte canônica quando existe: o pipeline do database_improved
        importa o CSV para o DB, então o DB tende a ter todos os jogos (incluindo os mais recentes).
        O CSV é usado apenas como fallback quando o DB não existir.
        """
        if HISTORY_DB.exists():
            self._load_history_from_db()
            if self.history_df is not None:
                return
            if HISTORY_CSV.exists():
                print(f"   [AVISO] Fallback para CSV apos falha ao carregar SQLite")
        if HISTORY_CSV.exists():
            try:
                print(f"[CARREGANDO] Carregando historico de: {HISTORY_CSV.name}" + (" (fallback)" if HISTORY_DB.exists() else ""))
                self.history_df = pd.read_csv(HISTORY_CSV, low_memory=False)
                if 'date' in self.history_df.columns:
                    self.history_df['date'] = pd.to_datetime(self.history_df['date'], errors='coerce')
                print(f"   [OK] {len(self.history_df):,} jogos carregados")
            except Exception as e:
                print(f"   [ERRO] Erro ao carregar CSV: {e}")
        else:
            print(f"[AVISO] Nenhum arquivo de historico encontrado!")
            print(f"   Esperados: {HISTORY_CSV} ou {HISTORY_DB}")
    
    def _load_history_from_db(self):
        """Carrega histórico a partir do SQLite (lol_history.db)."""
        if not HISTORY_DB.exists():
            return
        try:
            print(f"[CARREGANDO] Carregando historico de: {HISTORY_DB.name}")
            conn = sqlite3.connect(HISTORY_DB)
            self.history_df = pd.read_sql_query(
                "SELECT * FROM matchups ORDER BY date DESC",
                conn
            )
            conn.close()
            if 'date' in self.history_df.columns:
                self.history_df['date'] = pd.to_datetime(self.history_df['date'], errors='coerce')
            print(f"   [OK] {len(self.history_df):,} jogos carregados")
        except Exception as e:
            print(f"   [ERRO] Erro ao carregar SQLite: {e}")
    
    def match_game(self, bet: Dict) -> Optional[Dict]:
        """
        Tenta fazer match de uma aposta com um jogo do histórico.
        
        Args:
            bet: Dicionário com dados da aposta
            
        Returns:
            Dicionário com resultado do jogo ou None se não encontrado
        """
        if self.history_df is None or len(self.history_df) == 0:
            return None
        
        # Normaliza nomes
        league_norm = self.normalizer.normalize_league_name(bet['league_name'])
        team1_norm = self.normalizer.normalize_team_name(bet['home_team'], league_norm)
        team2_norm = self.normalizer.normalize_team_name(bet['away_team'], league_norm)
        
        if not all([league_norm, team1_norm, team2_norm]):
            return None
        
        # Converte data da aposta
        try:
            bet_date = pd.to_datetime(bet['game_date'])
        except:
            return None
        
        # Filtra por liga (defensivo: trim + casefold)
        league_col = self.history_df['league'].fillna('').astype(str).str.strip().str.upper()
        league_matches = self.history_df[league_col == league_norm.strip().upper()].copy()
        
        if len(league_matches) == 0:
            return None
        
        # Filtra por times (considera ambas as ordens: t1 vs t2 e t2 vs t1)
        t1_col = league_matches['t1'].fillna('').astype(str).str.strip().str.upper()
        t2_col = league_matches['t2'].fillna('').astype(str).str.strip().str.upper()
        a = team1_norm.strip().upper()
        b = team2_norm.strip().upper()
        team_matches = league_matches[
            ((t1_col == a) & (t2_col == b)) | ((t1_col == b) & (t2_col == a))
        ].copy()
        
        if len(team_matches) == 0:
            return None
        
        # Filtra por mapa se a aposta tiver mapa definido
        # No histórico, a coluna 'game' representa o mapa
        bet_map = bet.get('mapa')
        if bet_map is not None:
            # Verifica se a coluna 'game' existe no histórico
            if 'game' in team_matches.columns:
                # Filtra apenas mapas que correspondem ao mapa da aposta
                # (defensivo: histórico pode ter game como str/float)
                try:
                    bet_map_num = int(bet_map)
                except Exception:
                    bet_map_num = None

                if bet_map_num is not None:
                    game_num = pd.to_numeric(team_matches['game'], errors='coerce')
                    filtered = team_matches[game_num == bet_map_num].copy()
                else:
                    filtered = team_matches.iloc[0:0].copy()

                # Fallback: compara como string (para casos como "1" vs 1)
                if len(filtered) == 0:
                    filtered = team_matches[
                        team_matches['game'].fillna('').astype(str).str.strip() == str(bet_map).strip()
                    ].copy()

                team_matches = filtered
                
                if len(team_matches) == 0:
                    # Se não encontrou com o mapa específico, retorna None
                    # Isso garante que só encontramos resultados do mapa correto
                    return None
            else:
                # Se a coluna 'game' não existe, não podemos filtrar por mapa
                # Mantém comportamento antigo (aceita qualquer mapa)
                pass
        
        # Filtra por data (com tolerância)
        tolerance = timedelta(hours=DATE_TOLERANCE_HOURS)
        date_matches = team_matches[
            (team_matches['date'] >= bet_date - tolerance) &
            (team_matches['date'] <= bet_date + tolerance)
        ].copy()
        
        if len(date_matches) == 0:
            # Sem match dentro da tolerância: evita falso-positivo com jogo antigo/errado
            return None
        
        # Ordena por proximidade da data
        date_matches['date_diff'] = abs(date_matches['date'] - bet_date)
        date_matches = date_matches.sort_values('date_diff')
        
        # Pega o match mais próximo
        best_match = date_matches.iloc[0].to_dict()
        
        # Calcula score de confiança
        confidence = self._calculate_confidence(
            bet, best_match, team1_norm, team2_norm, league_norm
        )
        
        if confidence < MIN_CONFIDENCE_SCORE:
            return None
        
        # Retorna resultado
        return {
            'total_kills': best_match.get('total_kills'),
            'date': best_match.get('date'),
            'confidence': confidence,
            'match_info': {
                'league': best_match.get('league'),
                't1': best_match.get('t1'),
                't2': best_match.get('t2'),
                'date': best_match.get('date'),
                'game': best_match.get('game')  # Mapa do histórico
            }
        }
    
    def _calculate_confidence(
        self, 
        bet: Dict, 
        match: Dict, 
        team1_norm: str, 
        team2_norm: str, 
        league_norm: str
    ) -> float:
        """
        Calcula score de confiança no match.
        
        Returns:
            Score de 0.0 a 1.0
        """
        score = 1.0
        
        # Penaliza diferença de data
        try:
            bet_date = pd.to_datetime(bet['game_date'])
            match_date = pd.to_datetime(match.get('date'))
            if pd.notna(match_date):
                diff_hours = abs((bet_date - match_date).total_seconds() / 3600)
                if diff_hours > DATE_TOLERANCE_HOURS:
                    # Penaliza proporcionalmente
                    score *= max(0.5, 1.0 - (diff_hours - DATE_TOLERANCE_HOURS) / (DATE_TOLERANCE_HOURS * 2))
        except:
            score *= 0.8
        
        # Verifica nomes dos times
        match_t1 = str(match.get('t1', '')).upper()
        match_t2 = str(match.get('t2', '')).upper()
        
        if team1_norm.upper() not in [match_t1, match_t2]:
            score *= 0.7
        if team2_norm.upper() not in [match_t1, match_t2]:
            score *= 0.7
        
        # Verifica liga
        match_league = str(match.get('league', '')).upper()
        if league_norm.upper() != match_league:
            score *= 0.8
        
        return score
    
    def determine_bet_result(self, bet: Dict, game_result: Dict) -> Tuple[str, float]:
        """
        Determina se a aposta ganhou ou perdeu baseado no resultado do jogo.
        
        Args:
            bet: Dados da aposta
            game_result: Resultado do jogo (com total_kills)
            
        Returns:
            Tupla (status, result_value)
            status: 'won', 'lost', ou 'void'
            result_value: Valor real (total_kills)
        """
        total_kills = game_result.get('total_kills')
        
        if total_kills is None or pd.isna(total_kills):
            return ('void', None)
        
        try:
            total_kills = float(total_kills)
        except:
            return ('void', None)
        
        line_value = bet.get('line_value')
        side = bet.get('side', '').upper()
        
        if line_value is None:
            return ('void', total_kills)
        
        # Determina resultado
        if side == 'OVER':
            if total_kills > line_value:
                return ('won', total_kills)
            elif total_kills < line_value:
                return ('lost', total_kills)
            else:
                # Empate (push) - considera void
                return ('void', total_kills)
        
        elif side == 'UNDER':
            if total_kills < line_value:
                return ('won', total_kills)
            elif total_kills > line_value:
                return ('lost', total_kills)
            else:
                # Empate (push) - considera void
                return ('void', total_kills)
        
        else:
            return ('void', total_kills)
