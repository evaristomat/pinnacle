# Sistema Pinnacle - League of Legends

Sistema completo para coleta, análise e rastreamento de apostas em League of Legends usando dados da Pinnacle.

## 🚀 Início Rápido

### Executar Pipeline Completo

```bash
python run_all.py
```

Este comando executa todo o pipeline automaticamente:
1. Atualiza dados históricos
2. Coleta odds da Pinnacle
3. Analisa apostas com valor
4. Coleta e salva apostas no tracker
5. Atualiza resultados das apostas

Para mais detalhes sobre o fluxo, veja [FLUXO_RUN_ALL.md](FLUXO_RUN_ALL.md).

## 📁 Estrutura do Projeto

```
pinnacle/
├── run_all.py                 # Script orquestrador principal
├── main.py                    # Coleta odds da API Pinnacle
├── database.py                # Gerenciamento do banco SQLite
│
├── database_improved/         # Processamento de dados históricos
│   ├── main.py               # Pipeline de processamento
│   ├── download.py           # Download de dados
│   ├── clean_database.py      # Limpeza e transformação
│   └── lol_history.db        # Banco histórico de jogos
│
├── odds_analysis/             # Análise de valor nas odds
│   ├── odds_analyzer.py      # Analisador principal
│   ├── normalizer.py         # Normalização de nomes
│   ├── metodos_analise.py    # Métodos de análise (empírico, ML)
│   └── config.py             # Configurações
│
├── bets_tracker/              # Rastreamento de apostas
│   ├── main.py               # CLI do tracker
│   ├── collect_value_bets.py # Coleta apostas com valor
│   ├── bets_database.py      # Gerenciamento do banco
│   └── bets.db               # Banco de apostas
│
├── machine_learning/          # Modelos de ML
│   ├── train.py              # Treinamento de modelos
│   ├── data_preparation.py   # Preparação de dados
│   └── modelo_2025/          # Modelo 2025
│
└── pinnacle_data.db          # Banco principal de odds
```

## 🎯 Funcionalidades

### 1. Coleta de Odds (main.py)
- Busca dados da API Pinnacle
- Processa e normaliza odds
- Armazena em banco SQLite (`pinnacle_data.db`)

### 2. Análise de Valor (odds_analysis/)
- Compara odds com histórico
- Calcula Expected Value (EV)
- Identifica apostas com valor
- Suporta método empírico e ML

### 3. Rastreamento de Apostas (bets_tracker/)
- Coleta apostas identificadas como valor
- Rastreia resultados
- Calcula estatísticas de performance

### 4. Machine Learning (machine_learning/)
- Modelo preditivo baseado em draft
- Integração com análise de valor
- Requer convergência entre métodos

## 📊 Métodos de Análise

### Método Empírico
- Baseado em probabilidades históricas
- Usado para jogos futuros
- Calcula EV comparando odds com histórico

### Método ML
- Combina análise empírica com modelo de ML
- Disponível apenas para jogos finalizados (com draft)
- Só considera aposta boa se ambos convergirem

## ⚙️ Configuração

### Requisitos
```bash
pip install -r requirements.txt
```

### Bancos de Dados
- `pinnacle_data.db` - Odds da Pinnacle
- `database_improved/lol_history.db` - Histórico de jogos
- `bets_tracker/bets.db` - Apostas rastreadas

## 📝 Uso Detalhado

### Coletar Odds
```bash
python main.py
```

### Analisar Apostas
```bash
cd odds_analysis
python test_lckc.py
```

### Coletar Apostas com Valor
```bash
cd bets_tracker
python main.py collect
```

### Ver Estatísticas
```bash
cd bets_tracker
python main.py stats
```

## 🔄 Fluxo Completo

Veja [FLUXO_RUN_ALL.md](FLUXO_RUN_ALL.md) para documentação detalhada do pipeline completo.

## 📚 Documentação Adicional

- [FLUXO_RUN_ALL.md](FLUXO_RUN_ALL.md) - Fluxo detalhado do `run_all.py`
- `database_improved/README.md` - Processamento de dados históricos
- `odds_analysis/README.md` - Análise de valor
- `bets_tracker/README.md` - Rastreamento de apostas
- `machine_learning/README.md` - Modelos de ML

## 📄 Licença

Uso pessoal/educacional.
