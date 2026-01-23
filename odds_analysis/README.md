# 📊 Análise de Valor nas Odds

Sistema para analisar valor nas odds comparando com histórico de jogos.

## 🎯 Objetivo

Comparar odds de `total_kills` da Pinnacle com histórico real dos times para identificar apostas com valor.

## 📁 Estrutura

```
odds_analysis/
├── config.py          # Configurações
├── normalizer.py      # Normalização de nomes (times e ligas)
├── odds_analyzer.py   # Analisador principal
├── test_lckc.py      # Teste com LCK Cup
└── README.md         # Esta documentação
```

## 🚀 Uso

### Teste com LCK Cup

```bash
cd odds_analysis
python test_lckc.py
```

### Uso Programático

```python
from odds_analyzer import OddsAnalyzer, print_analysis

analyzer = OddsAnalyzer()

# Analisa um jogo específico
analysis = analyzer.analyze_game(matchup_id=12345)
print_analysis(analysis)

# Busca jogos futuros
games = analyzer.get_upcoming_games(league_filter="LCK")
```

## 🔄 Fluxo

1. **Busca jogos futuros** do banco Pinnacle
2. **Normaliza nomes** de times e ligas usando `ligas_times.json`
3. **Busca histórico** de jogos entre os times
4. **Compara odds** com estatísticas históricas
5. **Calcula Expected Value (EV)** para identificar valor

## 📊 Métricas

- **Expected Value (EV)**: Valor esperado da aposta
- **Edge**: Vantagem percentual
- **Probabilidade Implícita**: Probabilidade da odd
- **Probabilidade Estimada**: Probabilidade baseada no histórico

## ⚙️ Configuração

Edite `config.py` para ajustar:
- Caminhos dos bancos de dados
- Mínimo de jogos para análise válida
- Threshold de valor mínimo

## 🔍 Normalização

O sistema trata diferenças de nomes:
- **Times**: "G2 Esports" → "G2 Esports" (normaliza variações)
- **Ligas**: "LCK Cup" → "LCKC" (mapeia para formato do histórico)

## 📝 Exemplo de Saída

```
🎮 JOGO: T1 vs Gen.G
📅 Liga: LCK → LCK
⏰ Data: 2026-01-20 10:00:00

📊 Normalização:
   Time 1: T1 → T1
   Time 2: Gen.G → Gen.G

📈 Estatísticas Históricas (15 jogos):
   Média: 24.5 kills
   Mediana: 24.0 kills
   Desvio Padrão: 3.2

💰 Análise de Markets:
   ✅ VALOR | OVER 25.5 | Odd: 1.95
      Prob. Implícita: 51.3%
      Prob. Estimada: 58.2%
      Expected Value: +6.9%
      Edge: +6.9%
```
