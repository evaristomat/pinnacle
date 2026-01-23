# Modelo UNDER/OVER Total Kills - Dados 2025

Modelo de machine learning para prever se uma partida de League of Legends terá `total_kills` acima ou abaixo da média da liga, baseado no draft do jogo.

## 📋 Estrutura

```
modelo_2025/
├── data_2025.csv              # Dados brutos (baixar do Google Drive)
├── data_preparation_2025.py   # Preparação de dados
├── train_2025.py              # Treinamento do modelo
├── predict_2025.py            # Predições
├── analise_modelo_2025.ipynb # Notebook de análise (a criar)
├── data/                      # Dados pré-processados (gerado)
│   ├── features.csv
│   ├── labels.npy
│   ├── league_stats.pkl
│   ├── champion_impacts.pkl
│   └── feature_columns.pkl
└── models/                    # Modelos treinados (gerado)
    ├── model.pkl
    ├── scaler.pkl
    ├── league_stats.pkl
    ├── champion_impacts.pkl
    ├── feature_columns.pkl
    └── metrics.pkl
```

## 🚀 Como Usar

### 1. Baixar os Dados

1. Acesse o link do Google Drive:
   https://drive.google.com/file/d/1v6LRphp2kYciU4SXp0PCjEMuev1bDejc/view?usp=drive_link

2. Baixe o arquivo CSV

3. Salve o arquivo como `data_2025.csv` na pasta `modelo_2025/`

### 2. Preparar os Dados

```bash
cd modelo_2025
python data_preparation_2025.py
```

Isso irá:
- Carregar o CSV de 2025
- Calcular estatísticas por liga
- Calcular impactos de campeões
- Criar features e labels
- Salvar tudo em `data/`

### 3. Treinar o Modelo

```bash
python train_2025.py
```

Isso irá:
- Carregar dados pré-processados
- Treinar modelo de Regressão Logística
- Avaliar performance
- Salvar modelo em `models/`

### 4. Fazer Predições

```bash
python predict_2025.py
```

Ou use no código:

```python
from predict_2025 import load_model, predict_over_league_mean, predict_for_betting_line

# Carrega modelo
model, scaler, champion_impacts, league_stats, feature_columns = load_model()

# Dados do jogo
game = {
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

# Predição para média da liga
pred = predict_over_league_mean(game, model, scaler, champion_impacts, league_stats, feature_columns)
print(f"Probabilidade OVER média: {pred['probability_over_mean']:.1%}")

# Predição para linha específica
betting_line = 28.5
pred_line = predict_for_betting_line(game, betting_line, model, scaler, 
                                     champion_impacts, league_stats, feature_columns)
print(f"Probabilidade OVER {betting_line}: {pred_line['probability_over_line']:.1%}")
```

## 📊 Features do Modelo

O modelo usa as seguintes features:

1. **Estatísticas da Liga** (2 features):
   - Média de `total_kills` da liga
   - Desvio padrão de `total_kills` da liga

2. **Impactos dos Times** (2 features):
   - Média dos impactos dos campeões do Time 1
   - Média dos impactos dos campeões do Time 2

3. **Diferença de Impactos** (1 feature):
   - Diferença entre impactos médios dos times

4. **Impactos Individuais** (10 features):
   - Impacto de cada campeão por posição (Top, Jungle, Mid, ADC, Support) para cada time

5. **Codificação de Liga** (one-hot):
   - Uma feature binária para cada liga presente nos dados

**Total:** ~17-30 features (dependendo do número de ligas)

## 🎯 Target

O modelo prevê se `total_kills > média_da_liga`:
- **Label = 1**: OVER (total_kills > média)
- **Label = 0**: UNDER (total_kills <= média)

## 📈 Métricas

O modelo é avaliado usando:
- **Accuracy**: Taxa de acerto geral
- **ROC-AUC**: Área sob a curva ROC
- **Precision**: Precisão por classe
- **Recall**: Recall por classe
- **F1-Score**: F1-score por classe
- **Confusion Matrix**: Matriz de confusão

## ⚙️ Requisitos

```bash
pip install pandas numpy scikit-learn matplotlib seaborn jupyter
```

Ou use o `requirements.txt` da pasta pai:
```bash
cd ..
pip install -r requirements.txt
```

## 📝 Notas

- O modelo usa dados de **2025** (ano completo)
- Mínimo de **3 jogos** por campeão para calcular impacto
- Modelo treinado com **80% train / 20% test**
- Usa **class_weight='balanced'** para lidar com classes desbalanceadas
- Normalização com **StandardScaler**

## 🔄 Atualização

Para atualizar o modelo com novos dados:
1. Adicione novos jogos ao `data_2025.csv`
2. Execute `data_preparation_2025.py` novamente
3. Execute `train_2025.py` para retreinar
