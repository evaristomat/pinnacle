"""
Módulo para normalizar nomes de times e ligas entre diferentes fontes
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from config import LIGAS_TIMES_JSON


class NameNormalizer:
    """Normaliza nomes de times e ligas entre diferentes fontes."""
    
    def __init__(self, ligas_times_path: Path = LIGAS_TIMES_JSON):
        """
        Inicializa o normalizador.
        
        Args:
            ligas_times_path: Caminho para o arquivo ligas_times.json
        """
        self.ligas_times_path = ligas_times_path
        self.ligas_times: Dict[str, List[str]] = {}
        self.team_mapping: Dict[str, str] = {}  # nome_variante -> nome_canonico
        self.league_mapping: Dict[str, str] = {}  # nome_pinnacle -> nome_historico
        
        self._load_ligas_times()
        self._build_mappings()
        self._build_league_mapping()
    
    def _load_ligas_times(self):
        """Carrega mapeamento de ligas e times do histórico."""
        if not self.ligas_times_path.exists():
            print(f"[AVISO] Arquivo nao encontrado: {self.ligas_times_path}")
            return
        
        try:
            with open(self.ligas_times_path, 'r', encoding='utf-8') as f:
                self.ligas_times = json.load(f)
            # Não adiciona cores aqui para não quebrar outros scripts
            print(f"Carregado: {len(self.ligas_times)} ligas, {sum(len(times) for times in self.ligas_times.values())} times")
        except Exception as e:
            print(f"Erro ao carregar ligas_times.json: {e}")
    
    def _normalize_string(self, text: str) -> str:
        """
        Normaliza string para comparação (remove acentos, espaços, etc).
        
        Args:
            text: Texto a normalizar
            
        Returns:
            Texto normalizado
        """
        if not text:
            return ""
        
        # Remove espaços extras e converte para minúsculas
        text = re.sub(r'\s+', ' ', text.strip().lower())
        
        # Remove caracteres especiais comuns
        text = text.replace('.', '').replace(',', '').replace('-', '')
        text = text.replace("'", "").replace('"', '')
        
        return text
    
    def _build_mappings(self):
        """Constrói mapeamento de variações de nomes para nomes canônicos."""
        for liga, times in self.ligas_times.items():
            for time in times:
                # Nome canônico (primeiro da lista)
                nome_canonico = time
                
                # Adiciona mapeamento direto
                normalized = self._normalize_string(time)
                if normalized:
                    self.team_mapping[normalized] = nome_canonico
                
                # Adiciona variações comuns
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
        # Mapeamentos conhecidos
        league_mappings = {
            # Pinnacle -> Histórico
            'LCK': 'LCK',
            'LCK Cup': 'LCK',  # LCK Cup = LCK
            'LCK Challengers': 'LCKC',
            'LCK CL': 'LCKC',  # LCK CL = LCKC
            'LEC': 'LEC',
            'LPL': 'LPL',
            'LCS': 'LTA N',  # Pode variar
            'LCS NA': 'LTA N',
            'LFL': 'LFL',
            'LFL2': 'LFL2',
            'CBLOL': 'CD',
            'CBLOL Academy': 'CD',
            'VCS': 'VCS',
            'PCS': 'PCS',
            'TCL': 'TCL',
        }
        
        # Normaliza e adiciona
        for pinnacle_name, history_name in league_mappings.items():
            normalized = self._normalize_string(pinnacle_name)
            if normalized:
                self.league_mapping[normalized] = history_name
        
        # Também adiciona ligas do histórico diretamente
        for liga in self.ligas_times.keys():
            normalized = self._normalize_string(liga)
            if normalized:
                self.league_mapping[normalized] = liga
    
    def normalize_team_name(self, team_name: str, league: Optional[str] = None) -> Optional[str]:
        """
        Normaliza nome de time para o formato do histórico.
        
        Args:
            team_name: Nome do time da Pinnacle
            league: Nome da liga (opcional, ajuda na busca)
            
        Returns:
            Nome normalizado ou None se não encontrado
        """
        if not team_name:
            return None
        
        normalized_input = self._normalize_string(team_name)
        if not normalized_input:
            return None
        
        # Busca direta no mapeamento (mas só se não for o próprio nome)
        if normalized_input in self.team_mapping:
            mapped = self.team_mapping[normalized_input]
            # Se o mapeamento retornar algo diferente do input, usa
            if self._normalize_string(mapped) != normalized_input:
                return mapped
            # Se retornar o mesmo, continua a busca para encontrar melhor match
        
        # Busca por substring (mais flexível)
        best_match = None
        best_score = 0
        
        # Se temos liga, busca apenas nessa liga
        search_ligas = [league] if league and league in self.ligas_times else list(self.ligas_times.keys())
        
        for liga_search in search_ligas:
            for time in self.ligas_times.get(liga_search, []):
                normalized_time = self._normalize_string(time)
                
                # Match exato
                if normalized_input == normalized_time:
                    return time
                
                # Calcula similaridade simples
                if normalized_input in normalized_time or normalized_time in normalized_input:
                    # Se um é substring do outro, dá score alto
                    if normalized_input in normalized_time:
                        # Input está dentro do time (ex: "ktrolster" em "ktrolsterchallengers")
                        # Se o input começa o nome do time, é um bom match
                        if normalized_time.startswith(normalized_input):
                            score = 0.95  # Score muito alto para substring match no início
                        else:
                            # Input está no meio ou fim, score menor mas ainda bom
                            score = 0.85
                    elif normalized_time in normalized_input:
                        # Time está dentro do input (menos comum)
                        if normalized_input.startswith(normalized_time):
                            score = 0.95
                        else:
                            score = 0.85
                    else:
                        # Score baseado no tamanho da match
                        score = min(len(normalized_input), len(normalized_time)) / max(len(normalized_input), len(normalized_time))
                    
                    if score > best_score:
                        best_score = score
                        best_match = time
        
        # Retorna se score > 0.7 (70% de similaridade) ou se é substring match
        if best_match and best_score > 0.7:
            return best_match
        
        # Se não encontrou, tenta buscar matches usando find_team_matches
        matches = self.find_team_matches(team_name, league)
        if matches:
            # Retorna o primeiro match encontrado
            return matches[0][1]
        
        # Se ainda não encontrou, retorna None (não retorna o input original)
        return None
    
    def normalize_league_name(self, league_name: str) -> Optional[str]:
        """
        Normaliza nome de liga para o formato do histórico.
        
        Args:
            league_name: Nome da liga da Pinnacle
            
        Returns:
            Nome normalizado ou None se não encontrado
        """
        if not league_name:
            return None
        
        normalized_input = self._normalize_string(league_name)
        if not normalized_input:
            return None
        
        # Busca direta no mapeamento
        if normalized_input in self.league_mapping:
            return self.league_mapping[normalized_input]
        
        # Busca por substring nas ligas do histórico
        for liga in self.ligas_times.keys():
            normalized_liga = self._normalize_string(liga)
            if normalized_input in normalized_liga or normalized_liga in normalized_input:
                return liga
        
        return None
    
    def find_team_matches(self, team_name: str, league: Optional[str] = None) -> List[Tuple[str, str]]:
        """
        Encontra todas as possíveis correspondências de um time.
        
        Args:
            team_name: Nome do time
            league: Liga (opcional)
            
        Returns:
            Lista de tuplas (liga, time_normalizado)
        """
        matches = []
        normalized_input = self._normalize_string(team_name)
        
        if not normalized_input:
            return matches
        
        search_ligas = [league] if league and league in self.ligas_times else list(self.ligas_times.keys())
        
        for liga_search in search_ligas:
            for time in self.ligas_times.get(liga_search, []):
                normalized_time = self._normalize_string(time)
                if normalized_input in normalized_time or normalized_time in normalized_input:
                    matches.append((liga_search, time))
        
        return matches


# Instância global
_normalizer = None

def get_normalizer() -> NameNormalizer:
    """Retorna instância singleton do normalizador."""
    global _normalizer
    if _normalizer is None:
        _normalizer = NameNormalizer()
    return _normalizer
