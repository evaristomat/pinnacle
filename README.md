# Pinnacle LoL - Sistema de Apostas com Valor

Sistema completo para coleta de odds, analise de valor (empirico + ML), rastreamento de apostas e notificacoes automaticas em League of Legends usando dados da Pinnacle.

---

## Pre-requisitos

| Requisito | Versao |
|---|---|
| Python | 3.10+ |
| pip | qualquer |

### 1. Instalar dependencias

```bash
cd pinnacle
pip install -r requirements.txt          # Pipeline (CI / uso geral)
pip install -r requirements-app.txt      # App Streamlit (opcional, uso local)
```

### 2. Configurar `.env`

Crie um arquivo `.env` na raiz do projeto com as credenciais:

```env
# Pinnacle API
PINNACLE_SIG=<seu_sig>
PINNACLE_APT=<seu_apt>
PINNACLE_PCTAG=<seu_pctag>
PINNACLE_API_KEY=<sua_api_key>
PINNACLE_DEVICE_UUID=<seu_device_uuid>
PINNACLE_DIRECTUS_TOKEN=<seu_directus_token>
PINNACLE_DPVXZ=<seu_dpvxz>

# Telegram (opcional - notificacoes)
TELEGRAM_BOT_TOKEN=<token_do_botfather>
TELEGRAM_CHAT_ID=<seu_chat_id>
```

> As credenciais Pinnacle sao obtidas inspecionando as requests do site (DevTools > Network).
> Para o Telegram, crie um bot via @BotFather e obtenha o chat_id via `/getUpdates`.

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

Se o Telegram estiver configurado, envia notificacoes automaticas de novas bets e resultados.

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

## GitHub Actions (automacao)

O pipeline roda automaticamente via GitHub Actions com dois workflows:

### Pinnacle Pipeline (`pipeline.yml`)

Pipeline completo que roda **3x ao dia**:

| Horario (UTC) | Modo |
|---|---|
| **10:00** | Etapas 2+3+4 (sem download historico, usa cache) |
| **13:00** | Etapas 1+2+3+4 (com download historico — CSV atualizado ~meio-dia) |
| **22:00** | Etapas 2+3+4 (sem download historico, usa cache) |

### Update Bet Results (`update-results.yml`)

Workflow leve que roda **4x ao dia** (00:00, 06:00, 12:00, 18:00 UTC):
- Executa apenas a etapa 4 (atualizacao de resultados)
- Usa dados em cache, nao baixa historico do Google Drive

### Execucao manual

Ambos os workflows podem ser disparados manualmente em **Actions > Run workflow**, com opcoes para pular etapas ou rodar etapa especifica.

### Secrets necessarios

Configurar em **Settings > Secrets and variables > Actions**:

| Secret | Descricao |
|---|---|
| `PINNACLE_SIG` | Cookie `_sig` |
| `PINNACLE_APT` | Cookie `_apt` |
| `PINNACLE_PCTAG` | Cookie `pctag` |
| `PINNACLE_API_KEY` | API key (header) |
| `PINNACLE_DEVICE_UUID` | Device UUID (header) |
| `PINNACLE_DIRECTUS_TOKEN` | Token Directus (x-app-data) |
| `PINNACLE_DPVXZ` | DPVXZ (x-app-data) |
| `TELEGRAM_BOT_TOKEN` | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | Chat ID para notificacoes |
| `PINNACLE_EV_MIN_STORE` | EV minimo para salvar (opcional, default 0.05) |
| `PINNACLE_EV_MIN_APP` | EV minimo para exibir (opcional, default 0.15) |

### Persistencia de dados

- **Cache**: Databases (`.db`) e CSVs persistem entre execucoes via `actions/cache`
- **Artifacts**: Databases sao salvas como artifacts (30 dias) para download/inspecao

### Timeline diaria completa (UTC)

```
00:00  Update Results         (etapa 4, cache)
06:00  Update Results         (etapa 4, cache)
10:00  Pipeline sem historico (etapas 2+3+4, cache)
12:00  Update Results         (etapa 4, cache)
13:00  Pipeline COMPLETO      (etapas 1+2+3+4, download CSV)
18:00  Update Results         (etapa 4, cache)
22:00  Pipeline sem historico (etapas 2+3+4, cache)
```

---

## Notificacoes Telegram

O sistema envia notificacoes automaticas via Telegram em dois momentos:

### Novas value bets encontradas (etapa 3)

```
🎯 JOGO — T1 vs Gen.G
📅 10/02 às 08:00
🏆 LCK
────────────────────────────────

MAP 1
🔬 Método: Empírico (48 jogos)
✅ OVER KILLS 27.5
💰 Odds: 1.85 → Fair: 1.54
📊 EV: +18.3%

MAP 2
🔬 Método: ML (48 jogos)
✅ UNDER KILLS 26.5
💰 Odds: 2.05 → Fair: 1.72
📊 EV: +12.1%
```

### Resultados atualizados (etapa 4)

```
📊 RESULTADOS ATUALIZADOS (2)
────────────────────────────────
✅ Wins: 1 | ❌ Losses: 1

✅ WON
🎯 T1 vs Gen.G — Map 1
🏆 LCK | 🔬 Empírico
✅ OVER KILLS 27.5 @ 1.85
💰 +0.85u (Real: 31)

❌ LOST
🎯 T1 vs Gen.G — Map 2
🏆 LCK | 🔬 ML
❌ UNDER KILLS 26.5 @ 2.05
💸 -1.00u (Real: 29)

────────────────────────────────
📈 ROI GERAL
📋 156 resolvidas | 89 wins (57.1%)
💰 Return: +8.3% | Lucro: +12.95u
```

### Configuracao do Telegram

1. Crie um bot via **@BotFather** no Telegram
2. Copie o token fornecido
3. Envie qualquer mensagem ao bot
4. Acesse `https://api.telegram.org/bot<TOKEN>/getUpdates` para obter o `chat_id`
5. Configure no `.env` e/ou GitHub Secrets

---

### App Streamlit (dashboard visual)

```bash
pip install -r requirements-app.txt
streamlit run app.py
```

> Abre em `http://localhost:8501`. Se a porta estiver ocupada: `streamlit run app.py --server.port 8502`

**Abas disponiveis:**

| Aba | Funcao |
|---|---|
| **Dashboard** | KPIs, curva P/L, estatisticas gerais |
| **Apostas do Dia** | Apostas com valor para hoje/amanha; botao para marcar "ja apostei" |
| **Draft + ML** | Seleciona jogo, informa 10 campeoes do draft, roda modelo ML + empirico |
| **Minhas Apostas** | Historico de apostas feitas pelo usuario |
| **Performance** | Metricas detalhadas por metodo, liga, tipo de aposta |

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
├── requirements.txt              # Dependencias do pipeline (CI)
├── requirements-app.txt          # Dependencias do Streamlit (local)
├── .env                          # Credenciais (nao commitado)
│
├── .github/workflows/            # GitHub Actions
│   ├── pipeline.yml              #   Pipeline completo (3x/dia)
│   └── update-results.yml        #   Atualizacao de resultados (4x/dia)
│
├── database_improved/            # Pipeline de dados historicos
│   ├── main.py                   #   Orquestrador (download > clean > transform)
│   ├── download.py               #   Download de dados brutos (Google Drive)
│   ├── clean_database.py         #   Limpeza e transformacao
│   ├── ligas.py                  #   Mapeamento de ligas/times
│   ├── database_schema.py        #   Schema do banco SQLite
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
│   ├── telegram_notifier.py      #   Notificacoes Telegram
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
| `user_bets.db` | `bets_tracker/` | Apostas feitas pelo usuario (via Streamlit) |

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

Alem das credenciais no `.env`, existem variaveis opcionais:

```env
PINNACLE_EV_MIN_STORE=0.05        # EV minimo para salvar aposta (default: 5%)
PINNACLE_EV_MIN_APP=0.15          # EV minimo para exibir no app (default: 15%)
PINNACLE_ANALYSIS_EV_MIN=0.15     # EV minimo para analysis (default: 15%)
PINNACLE_ANALYSIS_POLICY=all      # Politica de analise (default: all)
```
