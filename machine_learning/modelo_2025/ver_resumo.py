import pickle
from pathlib import Path

m = pickle.load(open(Path("models/metrics.pkl"), "rb"))

print("=" * 70)
print("RESUMO DAS METRICAS DO MODELO 2025")
print("=" * 70)
print(f"\nAccuracy: {m['accuracy']:.2%}")
print(f"ROC-AUC: {m['roc_auc']:.4f}")

cr = m['classification_report']
print(f"\nUNDER:")
print(f"  Precision: {cr['UNDER']['precision']:.2%}")
print(f"  Recall: {cr['UNDER']['recall']:.2%}")
print(f"  F1-Score: {cr['UNDER']['f1-score']:.2%}")

print(f"\nOVER:")
print(f"  Precision: {cr['OVER']['precision']:.2%}")
print(f"  Recall: {cr['OVER']['recall']:.2%}")
print(f"  F1-Score: {cr['OVER']['f1-score']:.2%}")

cm = m['confusion_matrix']
print(f"\nConfusion Matrix:")
print(f"  TN (UNDER correto): {cm[0][0]}")
print(f"  FP (OVER incorreto): {cm[0][1]}")
print(f"  FN (UNDER incorreto): {cm[1][0]}")
print(f"  TP (OVER correto): {cm[1][1]}")

print(f"\nTotal acertos: {cm[0][0] + cm[1][1]} de {cm[0][0] + cm[0][1] + cm[1][0] + cm[1][1]}")
