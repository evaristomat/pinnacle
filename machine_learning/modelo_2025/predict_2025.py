"""
Predição usando o modelo treinado - DADOS 2025.
Usa MÉDIA DA LIGA como referência.
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from typing import Dict, List, Optional

# Caminhos - modelo 2025
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"


def load_model():
    """Carrega todos os componentes do modelo."""
    print("Carregando modelo 2025...")
    
    with open(MODELS_DIR / "model.pkl", "rb") as f:
        model = pickle.load(f)
    
    with open(MODELS_DIR / "scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    
    with open(MODELS_DIR / "champion_impacts.pkl", "rb") as f:
        champion_impacts = pickle.load(f)
    
    with open(MODELS_DIR / "league_stats.pkl", "rb") as f:
        league_stats = pickle.load(f)
    
    with open(MODELS_DIR / "feature_columns.pkl", "rb") as f:
        feature_columns = pickle.load(f)
    
    print("Modelo carregado com sucesso!")
    return model, scaler, champion_impacts, league_stats, feature_columns


def create_features_from_game(game_data: Dict, league_stats: Dict, 
                              champion_impacts: Dict, feature_columns: List[str]) -> np.ndarray:
    """
    Cria features a partir dos dados de um jogo.
    
    Args:
        game_data: Dict com 'league', 'top_t1', 'jung_t1', etc.
        league_stats: Estatísticas por liga
        champion_impacts: Impactos de campeões por liga
        feature_columns: Lista de nomes das features (na ordem correta)
    
    Returns:
        Array numpy com features
    """
    league = game_data['league']
    
    # Pega impactos dos campeões
    league_impacts = champion_impacts.get(league, {})
    
    # Normaliza nomes dos campeões
    def normalize_champ(champ):
        if not champ:
            return ''
        return str(champ).strip()
    
    # Impactos do Time 1
    top_t1_impact = league_impacts.get(normalize_champ(game_data.get('top_t1', '')), 0.0)
    jung_t1_impact = league_impacts.get(normalize_champ(game_data.get('jung_t1', '')), 0.0)
    mid_t1_impact = league_impacts.get(normalize_champ(game_data.get('mid_t1', '')), 0.0)
    adc_t1_impact = league_impacts.get(normalize_champ(game_data.get('adc_t1', '')), 0.0)
    sup_t1_impact = league_impacts.get(normalize_champ(game_data.get('sup_t1', '')), 0.0)
    
    # Impactos do Time 2
    top_t2_impact = league_impacts.get(normalize_champ(game_data.get('top_t2', '')), 0.0)
    jung_t2_impact = league_impacts.get(normalize_champ(game_data.get('jung_t2', '')), 0.0)
    mid_t2_impact = league_impacts.get(normalize_champ(game_data.get('mid_t2', '')), 0.0)
    adc_t2_impact = league_impacts.get(normalize_champ(game_data.get('adc_t2', '')), 0.0)
    sup_t2_impact = league_impacts.get(normalize_champ(game_data.get('sup_t2', '')), 0.0)
    
    # Média dos impactos de cada time
    team1_avg_impact = np.mean([top_t1_impact, jung_t1_impact, mid_t1_impact, adc_t1_impact, sup_t1_impact])
    team2_avg_impact = np.mean([top_t2_impact, jung_t2_impact, mid_t2_impact, adc_t2_impact, sup_t2_impact])
    
    # Diferença entre impactos dos times
    impact_diff = team1_avg_impact - team2_avg_impact
    
    # Estatísticas da liga
    league_mean = league_stats.get(league, {}).get('mean', 0.0)
    league_std = league_stats.get(league, {}).get('std', 0.0)
    
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
    
    # Adiciona codificação de liga (one-hot) - precisa pegar todas as ligas possíveis
    # das feature_columns
    for col in feature_columns:
        if col.startswith('league_') and col != 'league_mean' and col != 'league_std':
            # Extrai nome da liga do nome da coluna (ex: 'league_LCK' -> 'LCK')
            liga_name = col.replace('league_', '')
            feature_dict[col] = 1.0 if liga_name == league else 0.0
    
    # Cria array na ordem exata das feature_columns
    features = np.array([feature_dict.get(col, 0.0) for col in feature_columns])
    
    return features.reshape(1, -1)


def predict_over_league_mean(game_data: Dict, model, scaler, 
                            champion_impacts: Dict, league_stats: Dict, 
                            feature_columns: List[str]) -> Dict:
    """
    Prediz se total_kills será OVER da média da liga.
    
    Returns:
        Dict com probabilidades e decisão
    """
    # Cria features
    X = create_features_from_game(game_data, league_stats, champion_impacts, feature_columns)
    
    # Normaliza features
    X_scaled = scaler.transform(X)
    
    # Predição
    prob_over_mean = model.predict_proba(X_scaled)[0, 1]  # Probabilidade de OVER da média
    prob_under_mean = 1 - prob_over_mean
    
    # Nível de confiança
    if prob_over_mean >= 0.70 or prob_over_mean <= 0.30:
        confidence = 'High'
    else:
        confidence = 'Medium'
    
    return {
        'probability_over_mean': prob_over_mean,
        'probability_under_mean': prob_under_mean,
        'prediction': 'OVER' if prob_over_mean >= 0.5 else 'UNDER',
        'confidence': confidence,
        'league_mean': league_stats.get(game_data['league'], {}).get('mean', 0.0)
    }


def predict_for_betting_line(game_data: Dict, betting_line: float, model, scaler,
                             champion_impacts: Dict, league_stats: Dict,
                             feature_columns: List[str]) -> Dict:
    """
    Prediz para uma linha específica da casa de apostas.
    Ajusta probabilidade baseado na diferença entre linha e média da liga.
    
    Args:
        game_data: Dados do jogo
        betting_line: Linha oferecida pela casa (ex: 28.5)
    
    Returns:
        Dict com probabilidades ajustadas para a linha
    """
    league = game_data['league']
    league_mean = league_stats.get(league, {}).get('mean', 0.0)
    league_std = league_stats.get(league, {}).get('std', 1.0)
    
    # Prediz probabilidade de ser OVER da média
    pred_mean = predict_over_league_mean(game_data, model, scaler, 
                                        champion_impacts, league_stats, feature_columns)
    prob_over_mean = pred_mean['probability_over_mean']
    
    # Ajusta probabilidade para a linha específica usando distribuição normal
    # Se linha > média: probabilidade de OVER linha é menor que OVER média
    # Se linha < média: probabilidade de OVER linha é maior que OVER média
    
    if league_std > 0:
        # Calcula z-score da diferença entre linha e média
        z_score = (betting_line - league_mean) / league_std
        
        # Ajusta probabilidade usando função sigmoid
        # Quanto maior a diferença, maior o ajuste
        adjustment = 1 / (1 + np.exp(-z_score * 0.5))  # Fator de ajuste
        
        # Ajusta probabilidade
        if betting_line > league_mean:
            # Linha acima da média: reduz probabilidade de OVER
            prob_over_line = prob_over_mean * (1 - adjustment * 0.3)
        else:
            # Linha abaixo da média: aumenta probabilidade de OVER
            prob_over_line = prob_over_mean + (1 - prob_over_mean) * adjustment * 0.3
        
        # Garante que está entre 0 e 1
        prob_over_line = np.clip(prob_over_line, 0.0, 1.0)
    else:
        # Se std = 0, usa probabilidade da média
        prob_over_line = prob_over_mean
    
    prob_under_line = 1 - prob_over_line
    
    # Decisão baseada em threshold
    threshold = 0.55
    bet_over = prob_over_line >= threshold
    bet_under = prob_under_line >= threshold
    
    # Nível de confiança
    if prob_over_line >= 0.70 or prob_over_line <= 0.30:
        confidence = 'High'
    else:
        confidence = 'Medium'
    
    return {
        'betting_line': betting_line,
        'league_mean': league_mean,
        'difference': betting_line - league_mean,
        'probability_over_line': prob_over_line,
        'probability_under_line': prob_under_line,
        'bet_over': bet_over,
        'bet_under': bet_under,
        'confidence': confidence,
        'probability_over_mean': prob_over_mean  # Para referência
    }


def main():
    """Exemplo de uso."""
    # Carrega modelo
    model, scaler, champion_impacts, league_stats, feature_columns = load_model()
    
    # Exemplo de jogo
    game_example = {
        'league': 'LCK',
        'top_t1': 'Aatrox',
        'jung_t1': 'Graves',
        'mid_t1': 'Azir',
        'adc_t1': 'Jinx',
        'sup_t1': 'Thresh',
        'top_t2': 'Gnar',
        'jung_t2': 'Sejuani',
        'mid_t2': 'Orianna',
        'adc_t2': 'Aphelios',
        'sup_t2': 'Braum'
    }
    
    print("\n" + "=" * 60)
    print("EXEMPLO DE PREDICAO - MODELO 2025")
    print("=" * 60)
    print(f"\nJogo: {game_example['league']}")
    print(f"Time 1: {game_example['top_t1']}, {game_example['jung_t1']}, "
          f"{game_example['mid_t1']}, {game_example['adc_t1']}, {game_example['sup_t1']}")
    print(f"Time 2: {game_example['top_t2']}, {game_example['jung_t2']}, "
          f"{game_example['mid_t2']}, {game_example['adc_t2']}, {game_example['sup_t2']}")
    
    # Predição para média da liga
    pred_mean = predict_over_league_mean(game_example, model, scaler, champion_impacts,
                                        league_stats, feature_columns)
    
    print(f"\n{'='*60}")
    print(f"PREDICAO: OVER/UNDER MEDIA DA LIGA")
    print(f"{'='*60}")
    print(f"Media da liga {game_example['league']}: {pred_mean['league_mean']:.2f} kills")
    print(f"Probabilidade OVER media: {pred_mean['probability_over_mean']:.1%}")
    print(f"Probabilidade UNDER media: {pred_mean['probability_under_mean']:.1%}")
    print(f"Predicao: {pred_mean['prediction']} (Confianca: {pred_mean['confidence']})")
    
    # Predição para linha específica da casa
    betting_line = 28.5
    pred_line = predict_for_betting_line(game_example, betting_line, model, scaler,
                                        champion_impacts, league_stats, feature_columns)
    
    print(f"\n{'='*60}")
    print(f"PREDICAO: OVER/UNDER LINHA DA CASA ({betting_line})")
    print(f"{'='*60}")
    print(f"Linha da casa: {betting_line} kills")
    print(f"Media da liga: {pred_line['league_mean']:.2f} kills")
    print(f"Diferenca: {pred_line['difference']:+.2f} kills")
    print(f"Probabilidade OVER {betting_line}: {pred_line['probability_over_line']:.1%}")
    print(f"Probabilidade UNDER {betting_line}: {pred_line['probability_under_line']:.1%}")
    
    if pred_line['bet_over']:
        print(f"\n[OK] RECOMENDACAO: APOSTAR OVER {betting_line}")
        print(f"   Probabilidade: {pred_line['probability_over_line']:.1%} (Confianca: {pred_line['confidence']})")
    elif pred_line['bet_under']:
        print(f"\n[OK] RECOMENDACAO: APOSTAR UNDER {betting_line}")
        print(f"   Probabilidade: {pred_line['probability_under_line']:.1%} (Confianca: {pred_line['confidence']})")
    else:
        print(f"\n[AVISO] Nenhuma aposta recomendada (probabilidade muito proxima de 50%)")


if __name__ == "__main__":
    main()
