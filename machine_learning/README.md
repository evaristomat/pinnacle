# 🎯 Modelo de ML para UNDER/OVER Total Kills - League of Legends

Modelo de Machine Learning para prever se o **total de kills** em uma partida de League of Legends ficará **UNDER** (abaixo) ou **OVER** (acima) da **média da liga**.

## 📋 Características

- **1 modelo único** (ao invés de 8 modelos separados)
- **Target adaptativo**: Média da liga (muda automaticamente por liga)
- **Algoritmo:** Regressão Logística
- **Normalização:** StandardScaler
- **Validação:** Train/Test Split (80/20)
- **Features:** 28 features baseadas em impacto de campeões por liga

## 🚀 Instalação

```bash
pip install -r requirements.txt
```

## 📊 Como Funciona

### 1. Cálculo de Impacto de Campeões

O modelo calcula o **"impacto"** de cada campeão por liga:

```
Impacto do Campeão = Média de kills com o campeão - Média geral da liga
```

- Valores positivos: campeão tende a aumentar kills
- Valores negativos: campeão tende a diminuir kills
- Campeões com < 3 jogos na liga têm impacto = 0

### 2. Target: Média da Liga

O modelo prediz se `total_kills > média_da_liga` (OVER) ou `total_kills <= média_da_liga` (UNDER).

**Vantagem**: Adapta automaticamente para cada liga, já que médias variam muito (24-38 kills).

### 3. Features Utilizadas (28 total)

1. **Estatísticas da Liga** (2):
   - Média de total_kills da liga
   - Desvio padrão de total_kills da liga

2. **Impactos dos Times** (2):
   - Média dos impactos do Time 1
   - Média dos impactos do Time 2

3. **Diferença de Impactos** (1):
   - Diferença entre impactos dos times

4. **Impactos Individuais Time 1** (5):
   - Impacto de Top, Jungle, Mid, ADC, Support

5. **Impactos Individuais Time 2** (5):
   - Impacto de Top, Jungle, Mid, ADC, Support

6. **Codificação de Liga** (13):
   - One-hot encoding da liga

## 📁 Estrutura

```
machine_learning/
├── data_preparation.py    # Preparação de dados e cálculo de impactos
├── train.py              # Treinamento do modelo único
├── predict.py            # Predições para novos jogos
├── analise_modelo.ipynb  # Notebook Jupyter com análises completas
├── requirements.txt      # Dependências
├── README.md            # Esta documentação
├── data/                # Dados pré-processados (gerado)
│   ├── features.csv
│   ├── labels.npy
│   ├── league_stats.pkl
│   ├── champion_impacts.pkl
│   └── feature_columns.pkl
└── models/              # Modelos treinados (gerado)
    ├── model.pkl
    ├── scaler.pkl
    ├── league_stats.pkl
    ├── champion_impacts.pkl
    ├── feature_columns.pkl
    └── metrics.pkl
```

## 🔄 Pipeline Completo

### 1. Preparação de Dados

```bash
python data_preparation.py
```

Este script:
- Carrega `data_transformed.csv` do diretório `database_improved`
- Calcula estatísticas por liga (média e desvio padrão)
- Calcula impacto de cada campeão por liga
- Cria 28 features para cada partida
- Cria labels usando média da liga (OVER = 1, UNDER = 0)
- Salva tudo em `data/`

### 2. Treinamento

```bash
python train.py
```

Este script:
- Carrega dados pré-processados
- Treina 1 modelo único
- Usa Regressão Logística com StandardScaler
- Split 80/20 para train/test
- Salva modelo em `models/`
- Mostra métricas (ROC-AUC, Accuracy, Precision, Recall, F1)

### 3. Análise Completa (Notebook)

```bash
jupyter notebook analise_modelo.ipynb
```

O notebook contém:
- Análise exploratória dos dados
- Treinamento do modelo
- **Curva ROC**
- **Precision-Recall Curve**
- **F1-Score por Threshold**
- **Confusion Matrix**
- Distribuição de probabilidades
- Análise por liga
- Testes de predição

### 4. Predição

```bash
python predict.py
```

Este script:
- Carrega modelo treinado
- Faz predição de exemplo
- Mostra recomendações de apostas

## 💻 Uso Programático

### Carregar Modelo

```python
from predict import load_model

model, scaler, champion_impacts, league_stats, feature_columns = load_model()
```

### Fazer Predição para Média da Liga

```python
from predict import predict_over_league_mean

game_data = {
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

prediction = predict_over_league_mean(
    game_data, model, scaler, champion_impacts,
    league_stats, feature_columns
)

print(f"Probabilidade OVER média: {prediction['probability_over_mean']:.1%}")
print(f"Predição: {prediction['prediction']}")
```

### Fazer Predição para Linha da Casa

```python
from predict import predict_for_betting_line

betting_line = 28.5  # Linha oferecida pela casa

prediction = predict_for_betting_line(
    game_data, betting_line, model, scaler,
    champion_impacts, league_stats, feature_columns
)

if prediction['bet_over']:
    print(f"Recomendação: APOSTAR OVER {betting_line}")
    print(f"Probabilidade: {prediction['probability_over_line']:.1%}")
```

## 📊 Formato de Entrada

### Dados do Jogo

```python
game_data = {
    'league': 'NOME_DA_LIGA',      # String: Liga do jogo (OBRIGATÓRIO)
    'top_t1': 'CAMPEAO_TOP_T1',    # String: Campeão Top do Time 1
    'jung_t1': 'CAMPEAO_JUNG_T1',  # String: Campeão Jungle do Time 1
    'mid_t1': 'CAMPEAO_MID_T1',    # String: Campeão Mid do Time 1
    'adc_t1': 'CAMPEAO_ADC_T1',    # String: Campeão ADC do Time 1
    'sup_t1': 'CAMPEAO_SUP_T1',    # String: Campeão Support do Time 1
    'top_t2': 'CAMPEAO_TOP_T2',    # String: Campeão Top do Time 2
    'jung_t2': 'CAMPEAO_JUNG_T2',  # String: Campeão Jungle do Time 2
    'mid_t2': 'CAMPEAO_MID_T2',    # String: Campeão Mid do Time 2
    'adc_t2': 'CAMPEAO_ADC_T2',    # String: Campeão ADC do Time 2
    'sup_t2': 'CAMPEAO_SUP_T2'     # String: Campeão Support do Time 2
}
```

**Importante**: O campo `league` é **obrigatório** e é usado para:
- Calcular a média da liga como referência
- Buscar impactos de campeões específicos da liga
- Codificar a liga nas features

## ⚠️ Limitações

1. **Campeões Novos:** Campeões não presentes no dataset terão impacto = 0
2. **Ligas Novas:** Ligas não treinadas usarão média geral
3. **Meta Changes:** Patches do jogo podem afetar a performance
4. **Sample Size:** Campeões com < 3 jogos na liga têm impacto = 0

## 🔧 Manutenção

1. **Retreinar Regularmente:** Atualizar com novos dados mensalmente
2. **Monitorar Performance:** Acompanhar ROC-AUC e accuracy no notebook
3. **Backup Regular:** Salvar versões do modelo
4. **Log de Predições:** Registrar todas as predições para análise

## 📚 Referências

- Baseado no guia: [https://github.com/evaristomat/lol_draft_ml](https://github.com/evaristomat/lol_draft_ml)
- Adaptado para usar média da liga como target (melhor para dataset pequeno)

## 📝 Notas

- O modelo usa **média da liga** como target (não linhas fixas)
- **1 modelo único** (mais dados por modelo)
- **Adaptativo por liga** (médias variam de 24-38 kills)
- Liga é **input obrigatório** para predição

---

**Última atualização:** 2026-01-23
