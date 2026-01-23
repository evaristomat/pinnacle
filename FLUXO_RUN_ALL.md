# 🔄 Fluxo Completo do Pipeline - run_all.py

Documentação detalhada do funcionamento do script orquestrador `run_all.py`.

## 📋 Visão Geral

O `run_all.py` é o script principal que executa todo o pipeline do sistema de forma automatizada, orquestrando 5 etapas principais:

1. **Atualização de Dados Históricos** (`database_improved`)
2. **Coleta de Odds da Pinnacle** (`main.py`)
3. **Análise de Apostas com Valor** (`odds_analysis`) - Opcional
4. **Coleta de Apostas no Tracker** (`bets_tracker`)
5. **Atualização de Resultados** (`bets_tracker`)

---

## 🎯 Etapa 1: Atualização de Dados Históricos

### Comando Executado
```bash
python database_improved/main.py --skip-download
```

### O que faz
- Processa dados históricos de jogos de LoL
- Limpa e transforma dados brutos
- Gera mapeamento de ligas e times
- Atualiza banco `lol_history.db`

### Arquivos Envolvidos
- `database_improved/main.py` - Orquestrador
- `database_improved/clean_database.py` - Processamento
- `database_improved/ligas.py` - Mapeamento
- `database_improved/data_transformed.csv` - Dados processados
- `database_improved/lol_history.db` - Banco histórico

### Status
- ✅ **Sucesso**: Dados históricos atualizados
- ⚠️ **Aviso**: Falha não crítica (continua pipeline)

---

## 🎯 Etapa 2: Coleta de Odds da Pinnacle

### Comando Executado
```bash
python main.py
```

### O que faz
- Busca dados da API Pinnacle (odds e matchups)
- Processa e normaliza odds
- Salva no banco `pinnacle_data.db`
- Exporta para JSON (`league_of_legends_data.json`)

### Arquivos Envolvidos
- `main.py` - Script principal
- `database.py` - Gerenciamento do banco
- `pinnacle_data.db` - Banco de odds
- `pinnacle_markets.json` - Dados brutos de markets
- `pinnacle_matchups.json` - Dados brutos de matchups
- `league_of_legends_data.json` - Exportação completa

### Tipos de Markets Coletados
- Moneyline (vitória)
- Handicap Map
- Total Map
- Total Kills (Home/Away)
- Handicap Kills
- Total Kills (combinado)

### Status
- ✅ **Sucesso**: Odds coletadas
- ❌ **Erro**: Falha crítica (continua com dados existentes)

---

## 🎯 Etapa 3: Análise de Apostas com Valor (Opcional)

### Comando Executado
```bash
python odds_analysis/test_lckc.py
```

### O que faz
- Testa análise de valor com jogos LCK Cup
- Demonstra funcionamento do analisador
- **Não é crítico** - apenas para visualização

### Arquivos Envolvidos
- `odds_analysis/odds_analyzer.py` - Analisador principal
- `odds_analysis/normalizer.py` - Normalização de nomes
- `odds_analysis/metodos_analise.py` - Métodos de análise

### Métodos de Análise
1. **Método Empírico**: Probabilidades baseadas em histórico
2. **Método ML**: Combina empírico + modelo ML (apenas jogos finalizados)

### Status
- ✅ **Sucesso**: Análise executada
- ⚠️ **Aviso**: Não crítico (sempre continua)

---

## 🎯 Etapa 4: Coleta de Apostas no Tracker

### Comandos Executados
```bash
# Inicializa banco
python bets_tracker/main.py init

# Coleta apostas
python bets_tracker/main.py collect
```

### O que faz
1. **Inicialização**:
   - Cria banco `bets.db` se não existir
   - Configura schema de tabelas

2. **Coleta**:
   - Busca jogos futuros do `pinnacle_data.db`
   - Analisa cada jogo com `odds_analyzer`
   - Identifica apostas com valor (EV > threshold)
   - Busca jogos finalizados com draft (método ML)
   - Salva apostas no `bets.db`

### Fluxo de Coleta

#### Para Jogos Futuros:
```
1. Busca jogos futuros (status != 'final')
2. Para cada jogo:
   - Normaliza nomes (times e ligas)
   - Busca histórico dos times
   - Analisa markets de total_kills
   - Calcula Expected Value (EV)
   - Se EV > threshold → salva aposta
```

#### Para Jogos Finalizados:
```
1. Busca jogos no histórico com draft
2. Para cada jogo:
   - Verifica se está no histórico
   - Busca draft do jogo específico
   - Analisa com método empírico
   - Analisa com método ML
   - Se ambos convergirem → salva aposta (método ML)
```

### Arquivos Envolvidos
- `bets_tracker/main.py` - CLI do tracker
- `bets_tracker/collect_value_bets.py` - Coleta de apostas
- `bets_tracker/bets_database.py` - Gerenciamento do banco
- `bets_tracker/bets.db` - Banco de apostas

### Critérios para Salvar Aposta
- ✅ EV > threshold (padrão: 5%)
- ✅ Dados históricos suficientes (mínimo 5 jogos)
- ✅ Para método ML: convergência entre empírico e ML

### Status
- ✅ **Sucesso**: Apostas coletadas
- ⚠️ **Aviso**: Nenhuma aposta encontrada ou erro

---

## 🎯 Etapa 5: Atualização de Resultados

### Comando Executado
```bash
python bets_tracker/main.py update
```

### O que faz
- Busca apostas pendentes no `bets.db`
- Verifica se jogos já finalizaram
- Compara resultado real com aposta
- Atualiza status (won/lost/void)
- Salva resultado real (ex: total_kills)

### Arquivos Envolvidos
- `bets_tracker/main.py` - CLI do tracker
- `bets_tracker/bets_database.py` - Atualização de resultados
- `bets_tracker/bets.db` - Banco de apostas
- `database_improved/lol_history.db` - Resultados reais

### Lógica de Atualização
```
Para cada aposta pendente:
  1. Busca jogo no histórico usando:
     - Times normalizados
     - Liga normalizada
     - Data do jogo (±2 horas)
  
  2. Se jogo encontrado:
     - Compara resultado real com linha da aposta
     - Se OVER e real > linha → won
     - Se UNDER e real < linha → won
     - Caso contrário → lost
  
  3. Atualiza status e resultado no banco
```

### Status
- ✅ **Sucesso**: Resultados atualizados
- ⚠️ **Aviso**: Nenhum resultado atualizado

---

## 📊 Resumo Final

Após todas as etapas, o script exibe:

### Estatísticas do Pipeline
- Status de cada etapa (OK/Aviso)
- Nome de cada etapa executada

### Estatísticas do Bets Tracker
- Total de apostas
- Por status (pending/won/lost)
- Por método (empírico/ML)
- ROI e win rate

---

## 🔄 Fluxo Visual

```
┌─────────────────────────────────────────────────────────┐
│                    run_all.py                            │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  ETAPA 1: Dados Históricos      │
        │  database_improved/main.py      │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  ETAPA 2: Coleta Odds           │
        │  main.py                        │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  ETAPA 3: Análise (Opcional)    │
        │  odds_analysis/test_lckc.py     │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  ETAPA 4: Coleta Apostas        │
        │  bets_tracker/main.py collect   │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  ETAPA 5: Atualiza Resultados   │
        │  bets_tracker/main.py update    │
        └─────────────────────────────────┘
                          │
                          ▼
        ┌─────────────────────────────────┐
        │  Resumo e Estatísticas          │
        └─────────────────────────────────┘
```

---

## ⚙️ Configurações

### Diretórios
O script assume a seguinte estrutura:
```
pinnacle/
├── run_all.py
├── main.py
├── database_improved/
├── odds_analysis/
└── bets_tracker/
```

### Encoding
- Configura encoding UTF-8 para Windows
- Trata erros de encoding graciosamente

### Tratamento de Erros
- Erros não críticos: continua pipeline
- Erros críticos: continua com dados existentes
- Interrupção manual: exibe mensagem e sai

---

## 📝 Exemplo de Execução

```bash
$ python run_all.py

======================================================================
PIPELINE COMPLETO - Sistema Pinnacle LoL
======================================================================
Iniciado em: 2026-01-23 14:30:00

[ETAPA 1/5] Atualizando dados históricos (database_improved)
   Executando: Processando dados históricos
   [OK] Dados históricos atualizados

[ETAPA 2/5] Coletando odds da Pinnacle
   Executando: Buscando dados da API Pinnacle
   [OK] Odds da Pinnacle coletadas

[ETAPA 3/5] Analisando apostas com valor (odds_analysis) - OPCIONAL
   [INFO] Esta etapa é opcional - apenas para visualização
   [OK] Análise de valor executada

[ETAPA 4/5] Coletando apostas com valor (bets_tracker)
   Inicializando banco de apostas...
   Coletando apostas com valor de todos os jogos...
   [OK] 135 apostas no banco

[ETAPA 5/5] Atualizando resultados das apostas
   Executando: Atualizando resultados
   [OK] Resultados atualizados

======================================================================
RESUMO DO PIPELINE
======================================================================
   [OK] Database Improved
   [OK] Pinnacle Collect
   [OK] Odds Analysis
   [OK] Bets Collect
   [OK] Bets Update

Estatísticas do Bets Tracker:
   Total de apostas: 70
   Por status: {'pending': 50, 'won': 15, 'lost': 5}

Pipeline concluído!
Finalizado em: 2026-01-23 14:35:00
```

---

## 🔍 Detalhes Técnicos

### Dependências entre Etapas
- **Etapa 1 → Etapa 2**: Dados históricos usados na análise
- **Etapa 2 → Etapa 4**: Odds coletadas necessárias para análise
- **Etapa 4 → Etapa 5**: Apostas coletadas precisam ser atualizadas

### Tratamento de Falhas
- Etapas não críticas: pipeline continua
- Etapas críticas: usa dados existentes
- Logs de erro: exibidos mas não interrompem

### Performance
- Execução sequencial (não paralela)
- Tempo estimado: 2-5 minutos
- Depende de:
  - Velocidade da API Pinnacle
  - Quantidade de jogos
  - Tamanho do histórico

---

## 📚 Referências

- `README.md` - Visão geral do projeto
- `database_improved/README.md` - Processamento de dados
- `odds_analysis/README.md` - Análise de valor
- `bets_tracker/README.md` - Rastreamento de apostas
