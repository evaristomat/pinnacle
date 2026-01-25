# Independência dos métodos (empírico vs ML)

Cada método é **independente** e **não tem relação funcional** com o outro.

## Verificação no código

### Método empírico (`force_method='probabilidade_empirica'`)

- **`odds_analyzer.py`**: Quando `force_method == METODO_PROBABILIDADE_EMPIRICA`, o bloco
  `if force_method != METODO_PROBABILIDADE_EMPIRICA and self.ml_available` **não é executado**.
- Assim, **nunca** são chamados:
  - `game_exists_in_history`
  - `get_draft_data`
  - `_predict_ml`
- Usa apenas: `get_total_kills_markets` (Pinnacle), `get_historical_stats` (`data_transformed`), normalizer.
- Cálculo: `empirical_prob` via `total_kills_values`; EV e `value` só com isso.

### Método ML (`force_method='machinelearning'`)

- Entra no bloco acima: chama `game_exists_in_history`, `get_draft_data`, `_predict_ml`.
- Usa `lol_history` (matchups, compositions) e o modelo ML.
- Decisão de “aposta com valor”: exige `has_value_empirical` **e** `ml_converges` (ambos calculados **na mesma chamada** de `analyze_game`).
- O método ML **não** depende de nenhuma chamada prévia ao método empírico (ex.: PASSA 1). Cada `analyze_game(force_method='machinelearning')` recalcula o empírico internamente.

### Orquestração (`collect_value_bets`)

- **PASSA 1**: `analyze_game(matchup_id, force_method='probabilidade_empirica')` para cada jogo.
  - `_extract_value_bets(analysis, only_empirical=True)`.
- **PASSA 2**: `analyze_game(matchup_id, force_method='machinelearning')` para cada jogo.
  - `_extract_value_bets(analysis, only_ml=True)`.
- Nenhum estado é compartilhado entre passes. PASSA 2 não usa resultado da PASSA 1.

## Resumo

| | Empírico | ML |
|-|----------|-----|
| Depende do outro? | Não | Não (recalcula empírico internamente) |
| Acessa lol_history? | Não | Sim |
| Acessa modelo ML? | Não | Sim |
| Chamadas cruzadas? | Nenhuma | Nenhuma |

**Conclusão:** Os dois métodos são independentes e não possuem relação funcional entre si.
