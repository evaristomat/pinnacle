"""
Normalizador específico para matching de resultados
Reutiliza lógica do odds_analysis mas com foco em matching
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import re

from config import LIGAS_TIMES_JSON
from bets_database import get_name_corrections


class ResultNormalizer:
    """Normaliza nomes para matching de resultados."""
    
    def __init__(self):
        """Inicializa o normalizador."""
        self.ligas_times_path = LIGAS_TIMES_JSON
        self.ligas_times: Dict[str, List[str]] = {}
        self.team_mapping: Dict[str, str] = {}
        self.league_mapping: Dict[str, str] = {}
        self.corrections = get_name_corrections()
        
        self._load_ligas_times()
        self._build_mappings()
        self._build_league_mapping()
        self._load_corrections()
    
    def _load_ligas_times(self):
        """Carrega mapeamento de ligas e times."""
        if not self.ligas_times_path.exists():
            return
        
        try:
            with open(self.ligas_times_path, 'r', encoding='utf-8') as f:
                self.ligas_times = json.load(f)
        except Exception as e:
            print(f"Erro ao carregar ligas_times.json: {e}")
    
    def _load_corrections(self):
        """Carrega correções salvas no banco."""
        # Correções de times
        for key, corrections in self.corrections.items():
            if 'team' in key:
                for corr in corrections:
                    normalized = self._normalize_string(corr['original'])
                    if normalized:
                        self.team_mapping[normalized] = corr['corrected']
        
        # Correções de ligas
        for key, corrections in self.corrections.items():
            if 'league' in key:
                for corr in corrections:
                    normalized = self._normalize_string(corr['original'])
                    if normalized:
                        self.league_mapping[normalized] = corr['corrected']
    
    def _normalize_string(self, text: str) -> str:
        """Normaliza string para comparação."""
        if not text:
            return ""
        
        text = re.sub(r'\s+', ' ', text.strip().lower())
        text = text.replace('.', '').replace(',', '').replace('-', '')
        text = text.replace("'", "").replace('"', '')
        
        return text
    
    def _build_mappings(self):
        """Constrói mapeamento de variações de nomes."""
        for liga, times in self.ligas_times.items():
            for time in times:
                nome_canonico = time
                normalized = self._normalize_string(time)
                if normalized:
                    self.team_mapping[normalized] = nome_canonico
                
                # Variações comuns
                variations = [
                    time.replace(' Esports', ''),
                    time.replace(' Gaming', ''),
                    time.replace(' Team', ''),
                    time.replace(' Esport', ''),
                ]
                
                for variation in variations:
                    if variation != time:
                        var_normalized = self._normalize_string(variation)
                        if var_normalized and var_normalized not in self.team_mapping:
                            self.team_mapping[var_normalized] = nome_canonico
    
    def _build_league_mapping(self):
        """Constrói mapeamento de nomes de ligas."""
        league_mappings = {
            'LCK': 'LCK',
            'LCK Cup': 'LCK',
            'LCK Challengers': 'LCKC',
            'LCK CL': 'LCKC',
            'LEC': 'LEC',
            'LPL': 'LPL',
            'LCS': 'LCS',
            'LCS NA': 'LCS',
            'LCS Lock In': 'LCS',
            'LFL': 'LFL',
            'LFL2': 'LFL2',
            'CBLOL': 'CD',
            'CBLOL Academy': 'CD',
            'VCS': 'VCS',
            'PCS': 'PCS',
            'TCL': 'TCL',
        }
        
        for pinnacle_name, history_name in league_mappings.items():
            normalized = self._normalize_string(pinnacle_name)
            if normalized:
                self.league_mapping[normalized] = history_name
        
        # Adiciona ligas do histórico diretamente
        for liga in self.ligas_times.keys():
            normalized = self._normalize_string(liga)
            if normalized:
                self.league_mapping[normalized] = liga
    
    def normalize_team_name(self, team_name: str, league: Optional[str] = None) -> Optional[str]:
        """Normaliza nome de time."""
        if not team_name:
            return None
        
        normalized_input = self._normalize_string(team_name)
        if not normalized_input:
            return None
        
        # Busca direta no mapeamento
        if normalized_input in self.team_mapping:
            mapped = self.team_mapping[normalized_input]
            if self._normalize_string(mapped) != normalized_input:
                return mapped
        
        # Busca por substring
        best_match = None
        best_score = 0
        
        search_ligas = [league] if league and league in self.ligas_times else list(self.ligas_times.keys())
        
        for liga_search in search_ligas:
            for time in self.ligas_times.get(liga_search, []):
                normalized_time = self._normalize_string(time)
                
                if normalized_input == normalized_time:
                    return time
                
                if normalized_input in normalized_time or normalized_time in normalized_input:
                    if normalized_input in normalized_time:
                        if normalized_time.startswith(normalized_input):
                            score = 0.95
                        else:
                            score = 0.85
                    else:
                        if normalized_input.startswith(normalized_time):
                            score = 0.95
                        else:
                            score = 0.85
                    
                    if score > best_score:
                        best_score = score
                        best_match = time
        
        if best_match and best_score > 0.7:
            return best_match
        
        return None
    
    def normalize_league_name(self, league_name: str) -> Optional[str]:
        """Normaliza nome de liga."""
        if not league_name:
            return None
        
        normalized_input = self._normalize_string(league_name)
        if not normalized_input:
            return None
        
        # Busca direta no mapeamento
        if normalized_input in self.league_mapping:
            return self.league_mapping[normalized_input]
        
        # Busca por substring
        for liga in self.ligas_times.keys():
            normalized_liga = self._normalize_string(liga)
            if normalized_input in normalized_liga or normalized_liga in normalized_input:
                return liga
        
        return None
