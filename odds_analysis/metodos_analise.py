"""
Métodos de análise de apostas com valor

Este módulo define os métodos disponíveis para análise de apostas.
Cada método implementa uma estratégia diferente para identificar valor.
"""

# Constantes para nomes dos métodos
METODO_PROBABILIDADE_EMPIRICA = 'probabilidade_empirica'
METODO_ML = 'ml'  # Método que combina análise empírica com modelo de ML
METODO_2 = 'metodo_2'  # TODO: Implementar método 2
METODO_3 = 'metodo_3'  # TODO: Implementar método 3

# Lista de métodos disponíveis
METODOS_DISPONIVEIS = [
    METODO_PROBABILIDADE_EMPIRICA,
    METODO_ML,
    METODO_2,
    METODO_3
]

# Descrições dos métodos
DESCRICOES_METODOS = {
    METODO_PROBABILIDADE_EMPIRICA: 'Probabilidade Empírica - Calcula probabilidade real baseada em dados históricos. Usado para jogos futuros e ao vivo.',
    METODO_ML: 'ML - Combina análise empírica com modelo de Machine Learning. Disponível apenas para jogos finalizados (quando draft está disponível no histórico). Só considera aposta boa se ambos convergirem (empírico + ML apontam para mesma direção).',
    METODO_2: 'Método 2 - A ser implementado',
    METODO_3: 'Método 3 - A ser implementado'
}


def get_metodo_descricao(metodo: str) -> str:
    """
    Retorna descrição de um método.
    
    Args:
        metodo: Nome do método
        
    Returns:
        Descrição do método
    """
    return DESCRICOES_METODOS.get(metodo, f'Método desconhecido: {metodo}')


def is_metodo_valido(metodo: str) -> bool:
    """
    Verifica se um método é válido.
    
    Args:
        metodo: Nome do método
        
    Returns:
        True se válido, False caso contrário
    """
    return metodo in METODOS_DISPONIVEIS
