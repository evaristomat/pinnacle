# 🎯 Sistema de Rastreamento de Apostas com Valor

Sistema completo para coletar apostas com valor identificadas pelo `odds_analysis` e rastrear seus resultados comparando com dados históricos.

## 🎯 Objetivo

1. **Coletar apostas com valor** identificadas pelo `odds_analyzer`
2. **Armazenar no banco `bets.db`** para rastreamento
3. **Atualizar resultados** comparando com `database_improved` quando jogos forem finalizados
4. **Calcular ROI** e estatísticas de performance

## 📁 Estrutura

```
bets_tracker/
├── config.py              # Configurações
├── bets_database.py       # Schema e funções do banco
├── collect_value_bets.py  # Coleta apostas com valor
├── update_results.py      # Atualiza resultados
├── result_matcher.py      # Matching de jogos
├── normalizer.py          # Normalização para matching
├── main.py                # Orquestrador principal
└── bets.db                # Banco de dados (gerado)
```

## 🚀 Uso Rápido

### 1. Inicializar Banco

```bash
cd bets_tracker
python main.py init
```

### 2. Coletar Apostas com Valor

```bash
# Coleta todas as apostas com valor
python main.py collect

# Coleta apenas de uma liga específica
python main.py collect --league LCK

# Inicializa banco e coleta
python main.py collect --init-db
```

### 3. Atualizar Resultados

```bash
# Atualiza resultados comparando com histórico
python main.py update

# Simula atualização (não salva)
python main.py update --dry-run
```

### 4. Ver Estatísticas

```bash
python main.py stats
```

## 🔄 Fluxo Completo

```
1. Coletar Apostas
   python main.py collect
   ↓
   Identifica apostas com valor do odds_analyzer
   ↓
   Salva em bets.db

2. Atualizar Histórico (database_improved)
   cd ../database_improved
   python main.py
   ↓
   Atualiza data_transformed.csv com jogos mais recentes

3. Atualizar Resultados
   cd ../bets_tracker
   python main.py update
   ↓
   Compara apostas pendentes com histórico
   ↓
   Atualiza status (won/lost/void) e resultado
```

## 📊 Estrutura do Banco `bets.db`

### Tabela `bets`

Armazena todas as apostas com valor:

- **Identificação**: `matchup_id`, `game_date`, `league_name`, `home_team`, `away_team`
- **Aposta**: `market_type`, `line_value`, `side`, `odd_decimal`
- **Análise**: `expected_value`, `edge`, `empirical_prob`, `implied_prob`, `historical_mean`, `historical_std`
- **Status**: `status` (pending/won/lost/void), `result_value`, `result_date`
- **Metadados**: `created_at`, `updated_at`, `metadata` (JSON)

### Tabela `name_corrections`

Armazena correções de nomes para melhorar matching:

- `source`: 'pinnacle' ou 'history'
- `type`: 'team' ou 'league'
- `original_name`: Nome original
- `corrected_name`: Nome corrigido
- `confidence`: Confiança na correção (0.0 a 1.0)

## 🔍 Sistema de Matching

O sistema faz matching de jogos entre Pinnacle e histórico considerando:

1. **Normalização de nomes**: Times e ligas são normalizados
2. **Tolerância de data**: ±24 horas por padrão (configurável)
3. **Score de confiança**: Mínimo 70% por padrão
4. **Ordem de matching**:
   - Liga → Times → Data (com tolerância)

### Exemplo de Matching

```
Pinnacle:          Histórico:
LCK Cup            LCK
T1 vs Gen.G        T1 vs Gen.G
2026-01-20 10:00   2026-01-20 11:30  ✅ Match (dentro da tolerância)
```

## ⚙️ Configuração

Edite `config.py` para ajustar:

```python
DATE_TOLERANCE_HOURS = 24      # Tolerância para matching de datas
MIN_CONFIDENCE_SCORE = 0.7     # Score mínimo para match válido
```

## 📈 Estatísticas e ROI

O sistema calcula automaticamente:

- **Total de apostas** por status
- **Taxa de acerto** (win rate)
- **ROI** baseado em odds e resultados
- **EV médio** das apostas

### Exemplo de Output

```
📊 Estatísticas do Banco de Apostas
============================================================
   Total de apostas: 45
   Por status: {'pending': 12, 'won': 20, 'lost': 13}

💰 ROI:
   Resolvidas: 33
   Vitórias: 20 (60.6%)
   Derrotas: 13
   Odd média (vitórias): 1.45
   EV médio: +8.2%
```

## 🔧 Resolução de Problemas

### Apostas não encontram match

1. **Verifique normalização**: Nomes podem estar diferentes
2. **Ajuste tolerância de data**: Pode ser necessário aumentar `DATE_TOLERANCE_HOURS`
3. **Adicione correções**: Use `name_corrections` para mapear nomes específicos

### Resultados incorretos

1. **Verifique matching**: Use `--dry-run` para ver matches antes de salvar
2. **Confiança baixa**: Ajuste `MIN_CONFIDENCE_SCORE` se necessário
3. **Dados históricos**: Certifique-se que `database_improved` está atualizado

## 🔗 Integração

### Com `odds_analysis`

O sistema importa diretamente do `odds_analyzer`:
- Usa `analyze_game()` para identificar valor
- Extrai apenas apostas com `value = True`
- Preserva toda análise (EV, probabilidades, etc.)

### Com `database_improved`

O sistema compara com histórico:
- Lê `data_transformed.csv` ou `lol_history.db`
- Usa `total_kills` para determinar resultado
- Considera diferenças de fuso horário

## 📝 Notas

- **Apostas são únicas**: Não duplica apostas já salvas (baseado em matchup_id + market)
- **Matching inteligente**: Tenta várias combinações de nomes e datas
- **Correções persistentes**: Aprende com correções manuais e reutiliza
- **Status automático**: Determina won/lost/void baseado em line_value e resultado real

## 🚀 Próximos Passos

1. **Dashboard web** para visualização
2. **Alertas** quando apostas são resolvidas
3. **Análise de performance** por liga/time
4. **Exportação** para planilhas

---

**Última atualização**: 2026-01-22
