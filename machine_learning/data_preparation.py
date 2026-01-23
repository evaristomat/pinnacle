"""
Preparação de dados para o modelo de ML de total_kills UNDER/OVER.
Usa MÉDIA DA LIGA como target (ao invés de linhas fixas).
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from typing import Dict, Tuple, List
from collections import defaultdict

# Caminhos
DATA_DIR = Path(__file__).parent.parent / "database_improved"
CSV_PATH = DATA_DIR / "data_transformed.csv"
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_data() -> pd.DataFrame:
    """Carrega os dados transformados."""
    print(f"Carregando dados de {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    print(f"Dados carregados: {len(df)} partidas")
    return df


def calculate_league_stats(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    Calcula estatísticas por liga: média e desvio padrão de total_kills.
    
    Returns:
        Dict com {league: {'mean': float, 'std': float}}
    """
    league_stats = {}
    for league in df['league'].unique():
        league_data = df[df['league'] == league]['total_kills'].dropna()
        mean_val = league_data.mean()
        std_val = league_data.std()
        
        # Se std for NaN (apenas 1 amostra), usa 0 ou um valor padrão
        if pd.isna(std_val) or std_val == 0:
            std_val = 1.0  # Valor padrão para evitar NaN
        
        league_stats[league] = {
            'mean': mean_val if not pd.isna(mean_val) else 0.0,
            'std': std_val
        }
    
    print("\nEstatísticas por liga:")
    for league, stats in sorted(league_stats.items()):
        print(f"  {league}: média={stats['mean']:.2f}, std={stats['std']:.2f}")
    
    return league_stats


def calculate_champion_impacts(df: pd.DataFrame, league_stats: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """
    Calcula impacto de cada campeão por liga.
    Impacto = Média de kills com o campeão - Média geral da liga
    
    Returns:
        Dict com {league: {champion: impact}}
    """
    champion_impacts = defaultdict(lambda: defaultdict(list))
    
    champion_cols = [
        'top_t1', 'jung_t1', 'mid_t1', 'adc_t1', 'sup_t1',
        'top_t2', 'jung_t2', 'mid_t2', 'adc_t2', 'sup_t2'
    ]
    
    # Coleta total_kills para cada campeão em cada liga
    for idx, row in df.iterrows():
        if pd.isna(row['total_kills']) or pd.isna(row['league']):
            continue
        
        league = row['league']
        total_kills = row['total_kills']
        
        for col in champion_cols:
            champ = row[col]
            if pd.notna(champ) and str(champ).strip() != '':
                # Normaliza nome do campeão (remove espaços extras, etc)
                champ_normalized = str(champ).strip()
                champion_impacts[league][champ_normalized].append(total_kills)
    
    # Calcula impacto médio de cada campeão por liga
    champion_impacts_final = {}
    for league in champion_impacts:
        league_mean = league_stats[league]['mean']
        champion_impacts_final[league] = {}
        
        for champ, kills_list in champion_impacts[league].items():
            if len(kills_list) >= 3:  # Mínimo 3 jogos para calcular impacto
                champ_mean = np.mean(kills_list)
                impact = champ_mean - league_mean
                champion_impacts_final[league][champ] = impact
            else:
                # Campeões com < 3 jogos têm impacto = 0
                champion_impacts_final[league][champ] = 0.0
    
    print(f"\nImpactos calculados para {len(champion_impacts_final)} ligas")
    total_champions = sum(len(champs) for champs in champion_impacts_final.values())
    print(f"Total de campeões com impacto calculado: {total_champions}")
    
    return champion_impacts_final


def create_features(df: pd.DataFrame, league_stats: Dict[str, Dict[str, float]], 
                   champion_impacts: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """
    Cria as features conforme o guia:
    1. Liga (codificação one-hot)
    2. Estatísticas da Liga (média e desvio padrão)
    3. Impactos dos Times (média dos impactos de cada time)
    4. Impactos Individuais (impacto de cada posição)
    5. Diferenças (diferença entre impactos dos times)
    """
    features_list = []
    valid_indices = []
    
    # Primeiro, cria codificação de liga para todas as ligas
    leagues = sorted(df['league'].dropna().unique())
    
    for idx, row in df.iterrows():
        if pd.isna(row['total_kills']) or pd.isna(row['league']):
            continue
        
        league = row['league']
        
        # Pega impactos dos campeões
        league_impacts = champion_impacts.get(league, {})
        
        # Normaliza nomes dos campeões
        def normalize_champ(champ):
            if pd.isna(champ):
                return ''
            return str(champ).strip()
        
        # Impactos do Time 1
        top_t1_impact = league_impacts.get(normalize_champ(row.get('top_t1', '')), 0.0)
        jung_t1_impact = league_impacts.get(normalize_champ(row.get('jung_t1', '')), 0.0)
        mid_t1_impact = league_impacts.get(normalize_champ(row.get('mid_t1', '')), 0.0)
        adc_t1_impact = league_impacts.get(normalize_champ(row.get('adc_t1', '')), 0.0)
        sup_t1_impact = league_impacts.get(normalize_champ(row.get('sup_t1', '')), 0.0)
        
        # Impactos do Time 2
        top_t2_impact = league_impacts.get(normalize_champ(row.get('top_t2', '')), 0.0)
        jung_t2_impact = league_impacts.get(normalize_champ(row.get('jung_t2', '')), 0.0)
        mid_t2_impact = league_impacts.get(normalize_champ(row.get('mid_t2', '')), 0.0)
        adc_t2_impact = league_impacts.get(normalize_champ(row.get('adc_t2', '')), 0.0)
        sup_t2_impact = league_impacts.get(normalize_champ(row.get('sup_t2', '')), 0.0)
        
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
            # Estatísticas da liga (2 features)
            'league_mean': league_mean,
            'league_std': league_std,
            
            # Impactos médios dos times (2 features)
            'team1_avg_impact': team1_avg_impact,
            'team2_avg_impact': team2_avg_impact,
            
            # Diferença de impactos (1 feature)
            'impact_diff': impact_diff,
            
            # Impactos individuais Time 1 (5 features)
            'top_t1_impact': top_t1_impact,
            'jung_t1_impact': jung_t1_impact,
            'mid_t1_impact': mid_t1_impact,
            'adc_t1_impact': adc_t1_impact,
            'sup_t1_impact': sup_t1_impact,
            
            # Impactos individuais Time 2 (5 features)
            'top_t2_impact': top_t2_impact,
            'jung_t2_impact': jung_t2_impact,
            'mid_t2_impact': mid_t2_impact,
            'adc_t2_impact': adc_t2_impact,
            'sup_t2_impact': sup_t2_impact,
        }
        
        # Adiciona codificação de liga (one-hot)
        for liga in leagues:
            feature_dict[f'league_{liga}'] = 1.0 if liga == league else 0.0
        
        features_list.append(feature_dict)
        valid_indices.append(idx)
    
    features_df = pd.DataFrame(features_list)
    features_df.index = valid_indices  # Mantém índices originais para alinhar com labels
    
    # Remove qualquer NaN restante (substitui por 0)
    features_df = features_df.fillna(0.0)
    
    print(f"\nFeatures criadas:")
    print(f"  Total de features: {len(features_df.columns)}")
    print(f"  Partidas válidas: {len(features_df)}")
    print(f"  Features numéricas: {len([c for c in features_df.columns if not c.startswith('league_')])}")
    print(f"  Features de liga (one-hot): {len([c for c in features_df.columns if c.startswith('league_')])}")
    print(f"  Valores NaN encontrados: {features_df.isna().sum().sum()}")
    
    return features_df


def create_labels(df: pd.DataFrame, features_df: pd.DataFrame, league_stats: Dict[str, Dict[str, float]]) -> np.ndarray:
    """
    Cria labels usando média da liga como target.
    Label = 1 se total_kills > média da liga (OVER), 0 caso contrário (UNDER)
    """
    # Alinha índices - usa os índices das features
    valid_indices = features_df.index
    df_aligned = df.loc[valid_indices]
    
    y = []
    for idx, row in df_aligned.iterrows():
        league = row['league']
        total_kills = row['total_kills']
        league_mean = league_stats.get(league, {}).get('mean', 0.0)
        
        # Label = 1 se total_kills > média da liga (OVER), 0 caso contrário (UNDER)
        label = 1 if total_kills > league_mean else 0
        y.append(label)
    
    y = np.array(y)
    
    print(f"\nLabels criados (usando média da liga):")
    print(f"  Total de amostras: {len(y)}")
    print(f"  UNDER (total_kills <= média): {np.sum(y == 0)} ({np.sum(y == 0)/len(y)*100:.1f}%)")
    print(f"  OVER (total_kills > média): {np.sum(y == 1)} ({np.sum(y == 1)/len(y)*100:.1f}%)")
    
    return y


def save_preprocessed_data(features_df: pd.DataFrame, labels: np.ndarray,
                          league_stats: Dict[str, Dict[str, float]],
                          champion_impacts: Dict[str, Dict[str, float]]):
    """Salva os dados pré-processados."""
    print(f"\nSalvando dados pré-processados em {OUTPUT_DIR}...")
    
    # Salva features
    features_df.to_csv(OUTPUT_DIR / "features.csv", index=False)
    
    # Salva labels
    np.save(OUTPUT_DIR / "labels.npy", labels)
    
    # Salva estatísticas e impactos
    with open(OUTPUT_DIR / "league_stats.pkl", "wb") as f:
        pickle.dump(league_stats, f)
    
    with open(OUTPUT_DIR / "champion_impacts.pkl", "wb") as f:
        pickle.dump(champion_impacts, f)
    
    # Salva lista de features (colunas)
    with open(OUTPUT_DIR / "feature_columns.pkl", "wb") as f:
        pickle.dump(list(features_df.columns), f)
    
    print("Dados salvos com sucesso!")


def main():
    """Pipeline completo de preparação de dados."""
    print("=" * 60)
    print("PREPARAÇÃO DE DADOS PARA MODELO UNDER/OVER TOTAL_KILLS")
    print("Usando MÉDIA DA LIGA como target")
    print("=" * 60)
    
    # Carrega dados
    df = load_data()
    
    # Calcula estatísticas por liga
    league_stats = calculate_league_stats(df)
    
    # Calcula impactos de campeões
    champion_impacts = calculate_champion_impacts(df, league_stats)
    
    # Cria features
    features_df = create_features(df, league_stats, champion_impacts)
    
    # Cria labels usando média da liga
    labels = create_labels(df, features_df, league_stats)
    
    # Salva tudo
    save_preprocessed_data(features_df, labels, league_stats, champion_impacts)
    
    print("\n" + "=" * 60)
    print("PREPARAÇÃO CONCLUÍDA!")
    print("=" * 60)


if __name__ == "__main__":
    main()
