# Pinnacle LoL - Sistema de Apostas com Valor

Sistema completo para coleta de odds, analise de valor (empirico + ML) e rastreamento de apostas em League of Legends usando dados da Pinnacle.

---

## Pre-requisitos

| Requisito | Versao |
|---|---|
| Python | 3.10+ |
| pip | qualquer |

### 1. Instalar dependencias

```bash
cd pinnacle
pip install requests pandas tqdm scikit-learn numpy python-dotenv streamlit
```

> Isso cobre **todas** as dependencias do projeto (pipeline + app).

### 2. Configurar `.env`

Crie um arquivo `.env` na raiz do projeto com as credenciais da Pinnacle:

```env
PINNACLE_SIG=<seu_sig>
PINNACLE_APT=<seu_apt>
PINNACLE_PCTAG=<seu_pctag>
PINNACLE_API_KEY=<sua_api_key>
PINNACLE_DEVICE_UUID=<seu_device_uuid>
PINNACLE_DIRECTUS_TOKEN=<seu_directus_token>
PINNACLE_DPVXZ=<seu_dpvxz>
```

> As credenciais sao obtidas inspecionando as requests do site da Pinnacle (DevTools > Network).

---

## Como rodar

### Pipeline completo (coleta + apostas + resultados)

```bash
python run_all.py
```

O pipeline executa **4 etapas** em sequencia:

| Etapa | O que faz |
|---|---|
| **1** | Atualiza dados historicos (`database_improved`) — download + limpeza de partidas |
| **2** | Coleta odds ao vivo da API Pinnacle — salva em `pinnacle_data.db` |
| **3** | Analisa odds vs historico, identifica apostas com valor (empirico + ML) — salva em `bets_tracker/bets.db` |
| **4** | Atualiza resultados das apostas pendentes — cruza com historico de jogos |

No final, imprime estatisticas completas: total de apostas, ROI, win rate, lucro.

### Opcoes do pipeline

```bash
python run_all.py --skip-history     # Pula etapa 1 (dados historicos)
python run_all.py --skip-collect     # Pula etapa 3 (coleta de apostas)
python run_all.py --skip-update      # Pula etapa 4 (atualizacao de resultados)
python run_all.py --only 2           # Roda APENAS etapa 2
python run_all.py --ev-min 0.10      # EV minimo de 10% para coleta
python run_all.py --dry-run          # Modo seco (nao salva nada)
```

**Uso tipico diario:**

```bash
# Rodar tudo (mais comum)
python run_all.py

# Ja rodou historico hoje? Pule a etapa 1 (mais rapido)
python run_all.py --skip-history

# Apenas atualizar resultados de apostas feitas
python run_all.py --only 4
```

---

### App Streamlit (dashboard visual)

```bash
streamlit run app.py
```

> Abre em `http://localhost:8501`. Se a porta estiver ocupada: `streamlit run app.py --server.port 8502`

**Abas disponiveis:**

| Aba | Funcao |
|---|---|
| **Apostas do Dia** | Apostas com valor para hoje/amanha; botao para marcar "ja apostei" |
| **Draft + ML** | Seleciona jogo, informa 10 campeoes do draft, roda modelo ML + empirico |
| **Resultados** | Historico completo de apostas, ROI, curva P/L |
| **Estatisticas** | Metricas detalhadas por metodo, liga, tipo de aposta |

---

## Estrutura do projeto

```
pinnacle/
├── run_all.py                    # Orquestrador do pipeline (4 etapas)
├── main.py                       # Coleta odds da API Pinnacle
├── database.py                   # CRUD do banco pinnacle_data.db
├── app.py                        # Dashboard Streamlit
├── results_analysis.py           # Analise detalhada de resultados
├── stats_resolved.py             # Funcoes de estatisticas (usado pelo app)
├── lolesports_live_draft.py      # Integracao com API LoL Esports (draft)
├── .env                          # Credenciais Pinnacle (nao commitado)
│
├── database_improved/            # Pipeline de dados historicos
│   ├── main.py                   #   Orquestrador (download > clean > transform)
│   ├── download.py               #   Download de dados brutos
│   ├── clean_database.py         #   Limpeza e transformacao
│   ├── ligas.py                  #   Mapeamento de ligas/times
│   ├── database_schema.py        #   Schema do banco
│   └── config.py                 #   Configuracoes
│
├── odds_analysis/                # Engine de analise de valor
│   ├── odds_analyzer.py          #   Analisador principal (empirico + ML)
│   ├── metodos_analise.py        #   Definicao dos metodos de analise
│   ├── normalizer.py             #   Normalizacao de nomes (times/ligas)
│   └── config.py                 #   Configuracoes (threshold ML = 0.65)
│
├── bets_tracker/                 # Rastreamento de apostas
│   ├── main.py                   #   CLI (init / collect / update / stats)
│   ├── collect_value_bets.py     #   Coleta apostas com valor
│   ├── bets_database.py          #   CRUD do banco bets.db
│   ├── update_results.py         #   Atualizacao de resultados
│   ├── result_matcher.py         #   Match aposta <> resultado
│   ├── analyze_results.py        #   Analise de resultados
│   ├── analyze_by_odds.py        #   Analise por faixa de odds
│   ├── analyze_ev_ranges.py      #   Analise por faixa de EV
│   ├── export_pending_bets.py    #   Exporta apostas pendentes (CSV)
│   ├── normalizer.py             #   Normalizacao de nomes
│   └── config.py                 #   Configuracoes (max 3 bets/map)
│
└── machine_learning/             # Modelo de ML
    └── modelo_2026/              #   Modelo ativo (v2)
        ├── data_preparation_v2.py    # Preparacao de features
        ├── train_v2.py               # Treino (split temporal + z-score calibrado)
        ├── predict_v2.py             # Predicao (threshold 0.65)
        ├── data/                     # Features, labels, champion impacts
        └── models/                   # model.pkl, scaler.pkl, z_calibration.pkl
```

### Bancos de dados

| Banco | Localizacao | Conteudo |
|---|---|---|
| `pinnacle_data.db` | raiz | Odds coletadas da Pinnacle |
| `lol_history.db` | `database_improved/` | Historico de partidas (kills, draft, etc) |
| `bets.db` | `bets_tracker/` | Apostas com valor identificadas + resultados |

---

## Como funciona a analise

### Metodo Empirico (`probabilidade_empirica`)
- Compara a odd da Pinnacle com a probabilidade historica real
- Calcula Expected Value: `EV = (prob_real * odd) - 1`
- Se EV > threshold (5% default), identifica como aposta com valor

### Metodo ML (`ml`)
- Modelo de Logistic Regression treinado em dados de 2026
- Features: estatisticas da liga (media/std de kills), impacto dos campeoes (min 5 jogos)
- Split temporal (80% treino / 20% teste) para avaliacao realista
- Z-score calibrado (Brier score otimizado) para ajustar probabilidades a linhas de aposta
- **Threshold de confianca: 0.65** — so aposta se o modelo tem >= 65% de confianca
- Necessita draft completo (10 campeoes) para funcionar

### Estrategia de apostas
- **Max 3 apostas por mapa** por partida
- Empirico: seleciona as 3 com **maior odd** (maior retorno potencial)
- ML: seleciona as 3 com **maior EV** (maior valor esperado)

---

## Retreinar o modelo ML

Se o dataset cresceu e voce quer retreinar:

```bash
cd machine_learning/modelo_2026

# 1. Preparar features (usa database_improved/data_transformed.csv)
python data_preparation_v2.py

# 2. Treinar modelo (split temporal + calibracao z-score)
python train_v2.py

# 3. (Opcional) Testar predicao
python predict_v2.py
```

Os arquivos `.pkl` em `models/` serao atualizados automaticamente.

---

## Variaveis de ambiente opcionais

Alem das credenciais Pinnacle no `.env`, existem variaveis opcionais:

```env
PINNACLE_EV_MIN_STORE=0.05        # EV minimo para salvar aposta (default: 5%)
PINNACLE_EV_MIN_APP=0.15          # EV minimo para exibir no app (default: 15%)
PINNACLE_ANALYSIS_EV_MIN=0.15     # EV minimo para analysis (default: 15%)
PINNACLE_ANALYSIS_POLICY=all      # Politica de analise (default: all)
```
