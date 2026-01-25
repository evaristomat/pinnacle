# Análise das Métricas do Modelo ML

## Métricas do Modelo 2025

### Métricas Gerais
- **Accuracy**: 61.93% (moderado, melhor que aleatório mas não excelente)
- **ROC-AUC**: 0.6833 (moderado, melhor que aleatório)

### Métricas por Classe

#### UNDER (total_kills <= média da liga)
- **Precision**: 66.56% ✅ (quando prediz UNDER, está correto 66.56% das vezes)
- **Recall**: 60.65%
- **F1-Score**: 63.47%

#### OVER (total_kills > média da liga)
- **Precision**: 57.35% ⚠️ (quando prediz OVER, está correto apenas 57.35% das vezes)
- **Recall**: 63.45%
- **F1-Score**: 60.24%

### Matriz de Confusão
```
                Predito
              UNDER  OVER
    Real UNDER   649    421
         OVER    326    566
```

**Interpretação:**
- **True Negatives (TN)**: 649 - UNDER predito corretamente
- **False Positives (FP)**: 421 - OVER predito incorretamente (era UNDER)
- **False Negatives (FN)**: 326 - UNDER predito incorretamente (era OVER)
- **True Positives (TP)**: 566 - OVER predito corretamente

## Problemas Identificados

### 1. OVER tem Precision Baixa (57.35%)
- Quando o modelo prediz OVER, está **errado quase 43% das vezes**
- Isso explica por que as apostas ML estão com win rate ruim (31%)
- **421 falsos positivos** - muitas vezes prediz OVER quando deveria ser UNDER

### 2. UNDER tem Precision Melhor (66.56%)
- Quando o modelo prediz UNDER, está correto **66.56% das vezes**
- Mais confiável que OVER
- **649 verdadeiros negativos** - boa capacidade de identificar UNDER

### 3. Desbalanceamento de Performance
- Modelo é **melhor em predizer UNDER** do que OVER
- Diferença de ~9% na precision entre classes

## Nova Lógica Proposta

### Abordagem 1: Thresholds Diferentes por Classe

Baseado na precision de cada classe:

1. **Para OVER**: Usar apenas quando confiança >= **80%**
   - Precision baixa (57.35%) requer confiança muito alta
   - Reduz falsos positivos

2. **Para UNDER**: Usar quando confiança >= **70%**
   - Precision melhor (66.56%) permite threshold menor
   - Aproveita melhor performance do modelo

3. **Convergência com Empírico**:
   - Se empírico tem valor E ML confirma com threshold adequado → Método ML
   - Se empírico tem valor mas ML diverge OU não atinge threshold → Método Empírico

### Abordagem 2: Usar Apenas Predições UNDER do ML

Como UNDER tem precision melhor (66.56%):

1. **Apenas usar ML quando prediz UNDER** com confiança >= 70%
2. **Ignorar predições OVER do ML** (precision muito baixa)
3. **Sempre priorizar empírico** quando ML prediz OVER

### Abordagem 3: Threshold Dinâmico Baseado em Precision

Calcular threshold mínimo baseado na precision esperada:

- **OVER**: Precision 57.35% → Threshold = 1 / 0.5735 = **1.74** (probabilidade mínima = 57.4%)
- **UNDER**: Precision 66.56% → Threshold = 1 / 0.6656 = **1.50** (probabilidade mínima = 66.7%)

Mas isso ainda não garante win rate > 50% devido aos falsos positivos.

## Recomendação Final

**Usar Abordagem 1 com ajustes:**

1. **OVER**: Confiança >= **80%** (muito restritivo devido à precision baixa)
2. **UNDER**: Confiança >= **70%** (aproveita melhor performance)
3. **Sempre priorizar empírico** se ML não atinge threshold ou diverge
4. **Considerar usar apenas predições UNDER do ML** se resultados ainda forem ruins

Isso garante:
- Menos apostas ML (apenas quando há alta confiança)
- Melhor qualidade das apostas ML (menos falsos positivos)
- Não perdemos boas apostas empíricas
