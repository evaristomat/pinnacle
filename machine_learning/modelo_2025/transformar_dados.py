"""
Transforma dados do formato Oracle's Elixir (por jogador) para formato por jogo.
"""

import pandas as pd
import numpy as np
from pathlib import Path

CSV_INPUT = Path("data_2025.csv")
CSV_OUTPUT = Path("data_2025_transformed.csv")

print("=" * 70)
print("TRANSFORMACAO DE DADOS - Oracle's Elixir para Formato por Jogo")
print("=" * 70)

print(f"\nCarregando dados de {CSV_INPUT}...")
df = pd.read_csv(CSV_INPUT, low_memory=False)
print(f"Dados carregados: {len(df)} linhas (por jogador)")

# Agrupa por jogo
print("\nAgrupando por jogo...")
games = []

for gameid in df['gameid'].unique():
    game_data = df[df['gameid'] == gameid].copy()
    
    if len(game_data) < 10:  # Precisa ter pelo menos 10 jogadores
        continue
    
    # Pega informações básicas do jogo (primeira linha)
    first_row = game_data.iloc[0]
    league = first_row['league']
    year = first_row['year']
    date = first_row['date']
    patch = first_row['patch']
    game = first_row['game']
    
    # Separa por time (Blue e Red)
    blue_team = game_data[game_data['side'] == 'Blue'].copy()
    red_team = game_data[game_data['side'] == 'Red'].copy()
    
    if len(blue_team) < 5 or len(red_team) < 5:
        continue
    
    # Pega nomes dos times
    t1_name = blue_team['teamname'].iloc[0] if len(blue_team) > 0 else 'Team1'
    t2_name = red_team['teamname'].iloc[0] if len(red_team) > 0 else 'Team2'
    
    # Resultado (1 se Blue ganhou, 0 se Red ganhou)
    result_t1 = 1 if blue_team['result'].iloc[0] == 1 else 0
    
    # Game length
    gamelength = first_row['gamelength']
    
    # Campeões por posição - Time 1 (Blue)
    top_t1 = blue_team[blue_team['position'] == 'top']['champion'].iloc[0] if len(blue_team[blue_team['position'] == 'top']) > 0 else ''
    jung_t1 = blue_team[blue_team['position'] == 'jungle']['champion'].iloc[0] if len(blue_team[blue_team['position'] == 'jungle']) > 0 else ''
    mid_t1 = blue_team[blue_team['position'] == 'mid']['champion'].iloc[0] if len(blue_team[blue_team['position'] == 'mid']) > 0 else ''
    adc_t1 = blue_team[blue_team['position'] == 'bot']['champion'].iloc[0] if len(blue_team[blue_team['position'] == 'bot']) > 0 else ''
    sup_t1 = blue_team[blue_team['position'] == 'support']['champion'].iloc[0] if len(blue_team[blue_team['position'] == 'support']) > 0 else ''
    
    # Campeões por posição - Time 2 (Red)
    top_t2 = red_team[red_team['position'] == 'top']['champion'].iloc[0] if len(red_team[red_team['position'] == 'top']) > 0 else ''
    jung_t2 = red_team[red_team['position'] == 'jungle']['champion'].iloc[0] if len(red_team[red_team['position'] == 'jungle']) > 0 else ''
    mid_t2 = red_team[red_team['position'] == 'mid']['champion'].iloc[0] if len(red_team[red_team['position'] == 'mid']) > 0 else ''
    adc_t2 = red_team[red_team['position'] == 'bot']['champion'].iloc[0] if len(red_team[red_team['position'] == 'bot']) > 0 else ''
    sup_t2 = red_team[red_team['position'] == 'support']['champion'].iloc[0] if len(red_team[red_team['position'] == 'support']) > 0 else ''
    
    # Kills por time
    kills_t1 = blue_team['teamkills'].iloc[0] if 'teamkills' in blue_team.columns and len(blue_team) > 0 else 0
    kills_t2 = red_team['teamkills'].iloc[0] if 'teamkills' in red_team.columns and len(red_team) > 0 else 0
    
    # Total kills (soma dos dois times)
    total_kills = kills_t1 + kills_t2
    
    # Objetivos - Time 1
    dragons_t1 = blue_team['dragons'].iloc[0] if 'dragons' in blue_team.columns and len(blue_team) > 0 else 0
    barons_t1 = blue_team['barons'].iloc[0] if 'barons' in blue_team.columns and len(blue_team) > 0 else 0
    towers_t1 = blue_team['towers'].iloc[0] if 'towers' in blue_team.columns and len(blue_team) > 0 else 0
    firstdragon_t1 = 1.0 if blue_team['firstdragon'].iloc[0] == 1 else 0.0 if 'firstdragon' in blue_team.columns and len(blue_team) > 0 else 0.0
    firstherald_t1 = 1.0 if blue_team['firstherald'].iloc[0] == 1 else 0.0 if 'firstherald' in blue_team.columns and len(blue_team) > 0 else 0.0
    firstbaron_t1 = 1.0 if blue_team['firstbaron'].iloc[0] == 1 else 0.0 if 'firstbaron' in blue_team.columns and len(blue_team) > 0 else 0.0
    firsttower_t1 = 1.0 if blue_team['firsttower'].iloc[0] == 1 else 0.0 if 'firsttower' in blue_team.columns and len(blue_team) > 0 else 0.0
    
    # Objetivos - Time 2
    dragons_t2 = red_team['dragons'].iloc[0] if 'dragons' in red_team.columns and len(red_team) > 0 else 0
    barons_t2 = red_team['barons'].iloc[0] if 'barons' in red_team.columns and len(red_team) > 0 else 0
    towers_t2 = red_team['towers'].iloc[0] if 'towers' in red_team.columns and len(red_team) > 0 else 0
    firstdragon_t2 = 1.0 if red_team['firstdragon'].iloc[0] == 1 else 0.0 if 'firstdragon' in red_team.columns and len(red_team) > 0 else 0.0
    firstherald_t2 = 1.0 if red_team['firstherald'].iloc[0] == 1 else 0.0 if 'firstherald' in red_team.columns and len(red_team) > 0 else 0.0
    firstbaron_t2 = 1.0 if red_team['firstbaron'].iloc[0] == 1 else 0.0 if 'firstbaron' in red_team.columns and len(red_team) > 0 else 0.0
    firsttower_t2 = 1.0 if red_team['firsttower'].iloc[0] == 1 else 0.0 if 'firsttower' in red_team.columns and len(red_team) > 0 else 0.0
    
    # Inhibitors
    inhibitors_t1 = blue_team['inhibitors'].iloc[0] if 'inhibitors' in blue_team.columns and len(blue_team) > 0 else 0
    inhibitors_t2 = red_team['inhibitors'].iloc[0] if 'inhibitors' in red_team.columns and len(red_team) > 0 else 0
    
    # Totais
    total_barons = barons_t1 + barons_t2
    total_towers = towers_t1 + towers_t2
    total_dragons = dragons_t1 + dragons_t2
    total_inhibitors = inhibitors_t1 + inhibitors_t2
    
    games.append({
        'league': league,
        'year': year,
        'date': date,
        'game': game,
        'patch': patch,
        'side': 'Blue',
        't1': t1_name,
        't2': t2_name,
        'result_t1': result_t1,
        'gamelength': gamelength,
        'top_t1': top_t1,
        'jung_t1': jung_t1,
        'mid_t1': mid_t1,
        'adc_t1': adc_t1,
        'sup_t1': sup_t1,
        'kills_t1': kills_t1,
        'firstdragon_t1': firstdragon_t1,
        'dragons_t1': dragons_t1,
        'barons_t1': barons_t1,
        'firstherald_t1': firstherald_t1,
        'firstbaron_t1': firstbaron_t1,
        'firsttower_t1': firsttower_t1,
        'towers_t1': towers_t1,
        'top_t2': top_t2,
        'jung_t2': jung_t2,
        'mid_t2': mid_t2,
        'adc_t2': adc_t2,
        'sup_t2': sup_t2,
        'kills_t2': kills_t2,
        'firstdragon_t2': firstdragon_t2,
        'dragons_t2': dragons_t2,
        'barons_t2': barons_t2,
        'firstherald_t2': firstherald_t2,
        'firstbaron_t2': firstbaron_t2,
        'firsttower_t2': firsttower_t2,
        'towers_t2': towers_t2,
        'inhibitors_t1': inhibitors_t1,
        'inhibitors_t2': inhibitors_t2,
        'total_kills': total_kills,
        'total_barons': total_barons,
        'total_towers': total_towers,
        'total_dragons': total_dragons,
        'total_inhibitors': total_inhibitors
    })

print(f"Jogos processados: {len(games)}")

# Cria DataFrame
df_transformed = pd.DataFrame(games)

# Filtra apenas 2025
if 'year' in df_transformed.columns:
    df_transformed = df_transformed[df_transformed['year'] == 2025]
    print(f"Jogos de 2025: {len(df_transformed)}")

# Remove jogos sem total_kills válido
df_transformed = df_transformed[df_transformed['total_kills'] > 0]
print(f"Jogos válidos (com total_kills > 0): {len(df_transformed)}")

# Salva
print(f"\nSalvando dados transformados em {CSV_OUTPUT}...")
df_transformed.to_csv(CSV_OUTPUT, index=False)
print(f"Dados salvos: {len(df_transformed)} jogos")

print("\n" + "=" * 70)
print("TRANSFORMACAO CONCLUIDA!")
print("=" * 70)
