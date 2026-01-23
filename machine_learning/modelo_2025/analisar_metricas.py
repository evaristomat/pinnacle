"""
Script para analisar e explicar as métricas do modelo 2025.
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"

def load_metrics():
    """Carrega métricas do modelo treinado."""
    metrics_path = MODELS_DIR / "metrics.pkl"
    
    if not metrics_path.exists():
        print("ERRO: Modelo ainda não foi treinado!")
        print("Execute primeiro: python train_2025.py")
        return None
    
    with open(metrics_path, "rb") as f:
        metrics = pickle.load(f)
    
    return metrics


def explain_metrics(metrics):
    """Explica as métricas do modelo."""
    print("=" * 70)
    print("ANÁLISE DAS MÉTRICAS DO MODELO 2025")
    print("=" * 70)
    
    # Métricas básicas
    accuracy = metrics['accuracy']
    roc_auc = metrics['roc_auc']
    
    print("\n" + "=" * 70)
    print("1. MÉTRICAS BÁSICAS")
    print("=" * 70)
    
    print(f"\n📊 ACCURACY (Precisão Geral): {accuracy:.4f} ({accuracy*100:.2f}%)")
    print("   → Percentual de predições corretas (OVER e UNDER)")
    print("   → Quanto maior, melhor (máximo = 1.0 = 100%)")
    if accuracy >= 0.70:
        print("   ✅ EXCELENTE: Modelo com alta precisão geral")
    elif accuracy >= 0.60:
        print("   ✅ BOM: Modelo com boa precisão")
    elif accuracy >= 0.50:
        print("   ⚠️  MODERADO: Melhor que aleatório, mas pode melhorar")
    else:
        print("   ❌ RUIM: Pior que aleatório (50%)")
    
    print(f"\n📈 ROC-AUC (Área sob a Curva ROC): {roc_auc:.4f}")
    print("   → Capacidade do modelo de distinguir entre OVER e UNDER")
    print("   → Varia de 0.0 a 1.0")
    print("   → 0.5 = aleatório, 1.0 = perfeito")
    if roc_auc >= 0.80:
        print("   ✅ EXCELENTE: Modelo muito bom em distinguir classes")
    elif roc_auc >= 0.70:
        print("   ✅ BOM: Modelo bom em distinguir classes")
    elif roc_auc >= 0.60:
        print("   ⚠️  MODERADO: Melhor que aleatório")
    else:
        print("   ❌ RUIM: Próximo do aleatório")
    
    # Classification Report
    cr = metrics['classification_report']
    
    print("\n" + "=" * 70)
    print("2. MÉTRICAS POR CLASSE")
    print("=" * 70)
    
    # UNDER
    under_precision = cr['UNDER']['precision']
    under_recall = cr['UNDER']['recall']
    under_f1 = cr['UNDER']['f1-score']
    under_support = cr['UNDER']['support']
    
    print(f"\n📉 CLASSE: UNDER (total_kills <= média da liga)")
    print(f"   Precision: {under_precision:.4f} ({under_precision*100:.2f}%)")
    print("   → Quando o modelo prediz UNDER, está correto X% das vezes")
    print(f"   Recall: {under_recall:.4f} ({under_recall*100:.2f}%)")
    print("   → O modelo identifica X% de todos os casos UNDER reais")
    print(f"   F1-Score: {under_f1:.4f}")
    print("   → Média harmônica entre Precision e Recall")
    print(f"   Support: {under_support} amostras")
    
    # OVER
    over_precision = cr['OVER']['precision']
    over_recall = cr['OVER']['recall']
    over_f1 = cr['OVER']['f1-score']
    over_support = cr['OVER']['support']
    
    print(f"\n📈 CLASSE: OVER (total_kills > média da liga)")
    print(f"   Precision: {over_precision:.4f} ({over_precision*100:.2f}%)")
    print("   → Quando o modelo prediz OVER, está correto X% das vezes")
    print(f"   Recall: {over_recall:.4f} ({over_recall*100:.2f}%)")
    print("   → O modelo identifica X% de todos os casos OVER reais")
    print(f"   F1-Score: {over_f1:.4f}")
    print("   → Média harmônica entre Precision e Recall")
    print(f"   Support: {over_support} amostras")
    
    # Confusion Matrix
    cm = metrics['confusion_matrix']
    tn, fp, fn, tp = cm[0][0], cm[0][1], cm[1][0], cm[1][1]
    total = tn + fp + fn + tp
    
    print("\n" + "=" * 70)
    print("3. MATRIZ DE CONFUSÃO")
    print("=" * 70)
    
    print(f"\n                Predito")
    print(f"              UNDER  OVER")
    print(f"    Real UNDER   {tn:4d}   {fp:4d}")
    print(f"         OVER    {fn:4d}   {tp:4d}")
    
    print(f"\n📊 INTERPRETAÇÃO:")
    print(f"   ✅ True Negatives (TN): {tn} - UNDER predito corretamente")
    print(f"   ❌ False Positives (FP): {fp} - OVER predito incorretamente (era UNDER)")
    print(f"   ❌ False Negatives (FN): {fn} - UNDER predito incorretamente (era OVER)")
    print(f"   ✅ True Positives (TP): {tp} - OVER predito corretamente")
    
    # Taxas derivadas
    print("\n" + "=" * 70)
    print("4. TAXAS DERIVADAS")
    print("=" * 70)
    
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0
    
    print(f"\n🎯 Specificity (Taxa de Verdadeiros Negativos): {specificity:.4f}")
    print("   → Capacidade de identificar corretamente casos UNDER")
    print("   → IMPORTANTE: Evita apostas erradas em UNDER quando deveria ser OVER")
    
    print(f"\n🎯 Sensitivity/Recall (Taxa de Verdadeiros Positivos): {sensitivity:.4f}")
    print("   → Capacidade de identificar corretamente casos OVER")
    print("   → IMPORTANTE: Identifica oportunidades de apostar em OVER")
    
    # Análise de balanceamento
    print("\n" + "=" * 70)
    print("5. ANÁLISE DE BALANCEAMENTO")
    print("=" * 70)
    
    under_pct = (tn + fp) / total * 100
    over_pct = (fn + tp) / total * 100
    
    print(f"\n📊 Distribuição das classes no conjunto de teste:")
    print(f"   UNDER: {tn + fp} amostras ({under_pct:.1f}%)")
    print(f"   OVER: {fn + tp} amostras ({over_pct:.1f}%)")
    
    if abs(under_pct - over_pct) < 10:
        print("   ✅ Classes bem balanceadas")
    else:
        print("   ⚠️  Classes desbalanceadas - modelo usa class_weight='balanced'")
    
    # Resumo final
    print("\n" + "=" * 70)
    print("6. RESUMO E RECOMENDAÇÕES")
    print("=" * 70)
    
    print(f"\n✅ PONTOS FORTES:")
    if accuracy >= 0.65:
        print(f"   • Accuracy de {accuracy*100:.1f}% indica boa capacidade preditiva")
    if roc_auc >= 0.70:
        print(f"   • ROC-AUC de {roc_auc:.3f} mostra boa separação entre classes")
    if under_precision >= 0.65 and over_precision >= 0.65:
        print("   • Boa precisão em ambas as classes")
    
    print(f"\n⚠️  PONTOS DE ATENÇÃO:")
    if accuracy < 0.60:
        print("   • Accuracy abaixo de 60% - considerar mais features ou dados")
    if roc_auc < 0.65:
        print("   • ROC-AUC baixo - modelo pode estar subajustado")
    if abs(under_precision - over_precision) > 0.15:
        print("   • Grande diferença entre precisões - modelo pode ter viés")
    
    print(f"\n💡 COMO USAR O MODELO:")
    print("   • Use probabilidades acima de 55% para apostas com confiança média")
    print("   • Use probabilidades acima de 70% para apostas com alta confiança")
    print("   • Evite apostar quando probabilidade estiver entre 45-55%")
    print("   • Considere o contexto da liga e dos times antes de apostar")
    
    print("\n" + "=" * 70)


def main():
    """Função principal."""
    metrics = load_metrics()
    
    if metrics is None:
        return
    
    explain_metrics(metrics)


if __name__ == "__main__":
    main()
