"""
Treinamento do modelo UNDER/OVER total_kills v2 - DADOS 2026.

Mudanças vs v1:
  - Split temporal (primeiros 80% treino, últimos 20% teste) em vez de aleatório
  - Calibração do z-score usando dados de treino (em vez de constantes mágicas)
  - Dataset maior (~1014 amostras vs 587)
  - Champion impacts com min 5 jogos
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score, accuracy_score, classification_report,
    confusion_matrix, brier_score_loss,
)
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "models"
OUTPUT_DIR.mkdir(exist_ok=True)

# Parâmetros
TEST_FRACTION = 0.2   # últimos 20% como teste
RANDOM_STATE = 42


# ── helpers ──────────────────────────────────────────────────────────────────

def load_data():
    """Carrega dados pré-processados pelo data_preparation_v2."""
    print("Carregando dados pré-processados (v2)...")

    features_df = pd.read_csv(DATA_DIR / "features.csv")
    labels = np.load(DATA_DIR / "labels.npy")
    dates = np.load(DATA_DIR / "dates.npy", allow_pickle=True)
    total_kills = np.load(DATA_DIR / "total_kills.npy")

    with open(DATA_DIR / "league_stats.pkl", "rb") as f:
        league_stats = pickle.load(f)
    with open(DATA_DIR / "champion_impacts.pkl", "rb") as f:
        champion_impacts = pickle.load(f)
    with open(DATA_DIR / "feature_columns.pkl", "rb") as f:
        feature_columns = pickle.load(f)
    with open(DATA_DIR / "leagues_array.pkl", "rb") as f:
        leagues_arr = pickle.load(f)

    print(f"  Features: {features_df.shape}")
    print(f"  Labels:   {labels.shape}")
    print(f"  Dist:     UNDER={np.sum(labels == 0)}, OVER={np.sum(labels == 1)}")

    return (features_df, labels, dates, total_kills,
            leagues_arr, league_stats, champion_impacts, feature_columns)


def temporal_split(features_df, labels, dates, total_kills, leagues_arr):
    """Split temporal: primeiros ~80% treino, últimos ~20% teste."""
    n = len(labels)
    split_idx = int(n * (1 - TEST_FRACTION))

    # dados já estão ordenados por date (data_preparation ordena)
    dates_pd = pd.to_datetime(dates)
    sorted_idx = np.argsort(dates_pd)

    X = features_df.values[sorted_idx]
    y = labels[sorted_idx]
    d = dates_pd[sorted_idx]
    tk = total_kills[sorted_idx]
    lg = leagues_arr[sorted_idx]

    X_train, X_test = X[:split_idx], X[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]
    d_train, d_test = d[:split_idx], d[split_idx:]
    tk_train, tk_test = tk[:split_idx], tk[split_idx:]
    lg_train, lg_test = lg[:split_idx], lg[split_idx:]

    print(f"\n  Split temporal @ index {split_idx}")
    print(f"  Train: {len(X_train)} amostras  ({d_train[0].date()} a {d_train[-1].date()})")
    print(f"  Test:  {len(X_test)} amostras  ({d_test[0].date()} a {d_test[-1].date()})")
    print(f"  Dist train: UNDER={np.sum(y_train == 0)}, OVER={np.sum(y_train == 1)}")
    print(f"  Dist test:  UNDER={np.sum(y_test == 0)}, OVER={np.sum(y_test == 1)}")

    return (X_train, X_test, y_train, y_test,
            d_train, d_test, tk_train, tk_test, lg_train, lg_test)


# ── z-score calibration ─────────────────────────────────────────────────────

def _adjusted_prob(prob_over_mean: float, z_score: float,
                   sigmoid_k: float, adjust_strength: float) -> float:
    """Aplica ajuste de z-score parametrizado."""
    adjustment = 1.0 / (1.0 + np.exp(-z_score * sigmoid_k))
    if z_score > 0:
        # Linha acima da média → reduz prob OVER
        p = prob_over_mean * (1.0 - adjustment * adjust_strength)
    else:
        # Linha abaixo da média → aumenta prob OVER
        p = prob_over_mean + (1.0 - prob_over_mean) * adjustment * adjust_strength
    return np.clip(p, 0.001, 0.999)


def calibrate_zscore(model, scaler, X_train, tk_train, lg_train,
                     league_stats: dict):
    """
    Encontra (sigmoid_k, adjust_strength) que minimizam Brier score no treino.

    Para cada amostra de treino, simula linhas = [mean-2σ, mean-σ, mean-0.5σ,
    mean, mean+0.5σ, mean+σ, mean+2σ] e mede o erro do modelo ajustado vs
    resultado real (1 se total_kills > line, 0 caso contrário).
    """
    print("\nCalibrando z-score no conjunto de treino...")

    X_train_scaled = scaler.transform(X_train)
    probs_over_mean = model.predict_proba(X_train_scaled)[:, 1]

    # Gera pares (prob_over_mean, z_score, label_for_line)
    offsets = [-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0]
    rows = []  # (prob_over_mean, z_score, y_line)
    for i in range(len(X_train)):
        league = str(lg_train[i])
        ls = league_stats.get(league)
        if ls is None:
            continue
        mean_l = ls["mean"]
        std_l = ls["std"]
        if std_l <= 0:
            continue
        p_over = float(probs_over_mean[i])
        real_kills = float(tk_train[i])
        for off in offsets:
            fake_line = mean_l + off * std_l
            z = (fake_line - mean_l) / std_l  # = off
            y_line = 1.0 if real_kills > fake_line else 0.0
            rows.append((p_over, z, y_line))

    prob_arr = np.array([r[0] for r in rows])
    z_arr = np.array([r[1] for r in rows])
    y_arr = np.array([r[2] for r in rows])
    print(f"  Amostras para calibração: {len(rows)}")

    best_params = {"sigmoid_k": 0.5, "adjust_strength": 0.3}  # fallback = v1
    best_brier = 1.0

    # Grid search simples (rápido o suficiente)
    for sk in np.arange(0.1, 2.01, 0.1):
        for ast in np.arange(0.05, 0.81, 0.05):
            preds = np.array([
                _adjusted_prob(prob_arr[j], z_arr[j], sk, ast)
                for j in range(len(rows))
            ])
            brier = brier_score_loss(y_arr, preds)
            if brier < best_brier:
                best_brier = brier
                best_params = {"sigmoid_k": float(round(sk, 2)),
                               "adjust_strength": float(round(ast, 2))}

    print(f"  Melhor sigmoid_k:       {best_params['sigmoid_k']}")
    print(f"  Melhor adjust_strength: {best_params['adjust_strength']}")
    print(f"  Brier score (treino):   {best_brier:.6f}")

    # Compara com v1 (constantes 0.5, 0.3)
    preds_v1 = np.array([
        _adjusted_prob(prob_arr[j], z_arr[j], 0.5, 0.3)
        for j in range(len(rows))
    ])
    brier_v1 = brier_score_loss(y_arr, preds_v1)
    print(f"  Brier score v1 (0.5/0.3): {brier_v1:.6f}")
    improvement = (brier_v1 - best_brier) / brier_v1 * 100 if brier_v1 > 0 else 0
    print(f"  Melhoria: {improvement:+.2f}%")

    return best_params, best_brier


# ── training ─────────────────────────────────────────────────────────────────

def train_model(X_train, y_train, X_test, y_test):
    """Treina Logistic Regression com StandardScaler."""
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    model = LogisticRegression(
        max_iter=1000,
        random_state=RANDOM_STATE,
        class_weight="balanced",
    )
    model.fit(X_train_s, y_train)

    y_pred = model.predict(X_test_s)
    y_proba = model.predict_proba(X_test_s)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_proba)
    except ValueError:
        auc = 0.0

    return model, scaler, {
        "accuracy": acc,
        "roc_auc": auc,
        "y_pred": y_pred,
        "y_pred_proba": y_proba,
        "y_test": y_test,
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("TREINAMENTO MODELO v2 - UNDER/OVER TOTAL_KILLS 2026")
    print("Split temporal | Z-score calibrado | Min 5 jogos/champion")
    print("=" * 60)

    (features_df, labels, dates, total_kills,
     leagues_arr, league_stats, champion_impacts, feature_columns) = load_data()

    (X_train, X_test, y_train, y_test,
     d_train, d_test, tk_train, tk_test,
     lg_train, lg_test) = temporal_split(
        features_df, labels, dates, total_kills, leagues_arr)

    # 1. Treina modelo
    model, scaler, metrics = train_model(X_train, y_train, X_test, y_test)

    # 2. Métricas
    print(f"\n{'=' * 60}")
    print("MÉTRICAS DO MODELO (split temporal)")
    print(f"{'=' * 60}")
    print(f"  Accuracy: {metrics['accuracy']:.4f}")
    print(f"  ROC-AUC:  {metrics['roc_auc']:.4f}")

    report = classification_report(
        y_test, metrics["y_pred"],
        target_names=["UNDER", "OVER"], output_dict=True,
    )
    print(f"\n  Classification Report:")
    print(f"    UNDER - P: {report['UNDER']['precision']:.4f}  "
          f"R: {report['UNDER']['recall']:.4f}  "
          f"F1: {report['UNDER']['f1-score']:.4f}")
    print(f"    OVER  - P: {report['OVER']['precision']:.4f}  "
          f"R: {report['OVER']['recall']:.4f}  "
          f"F1: {report['OVER']['f1-score']:.4f}")

    cm = confusion_matrix(y_test, metrics["y_pred"])
    print(f"\n  Confusion Matrix:")
    print(f"              Predito")
    print(f"            UNDER  OVER")
    print(f"  Real UNDER  {cm[0,0]:4d}   {cm[0,1]:4d}")
    print(f"       OVER   {cm[1,0]:4d}   {cm[1,1]:4d}")

    # Brier score no test set (predição vs média)
    brier_base = brier_score_loss(y_test, metrics["y_pred_proba"])
    print(f"\n  Brier score (OVER média, test): {brier_base:.6f}")

    # 3. Calibra z-score no treino
    z_params, z_brier = calibrate_zscore(
        model, scaler, X_train, tk_train, lg_train, league_stats)

    # 4. Salva tudo
    print(f"\n{'=' * 60}")
    print("Salvando modelo v2...")

    with open(OUTPUT_DIR / "model.pkl", "wb") as f:
        pickle.dump(model, f)
    with open(OUTPUT_DIR / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)
    with open(OUTPUT_DIR / "league_stats.pkl", "wb") as f:
        pickle.dump(league_stats, f)
    with open(OUTPUT_DIR / "champion_impacts.pkl", "wb") as f:
        pickle.dump(champion_impacts, f)
    with open(OUTPUT_DIR / "feature_columns.pkl", "wb") as f:
        pickle.dump(feature_columns, f)
    with open(OUTPUT_DIR / "z_calibration.pkl", "wb") as f:
        pickle.dump(z_params, f)

    metrics_full = {
        "accuracy": metrics["accuracy"],
        "roc_auc": metrics["roc_auc"],
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "brier_score_base": brier_base,
        "z_calibration": z_params,
        "z_brier_train": z_brier,
        "split": "temporal",
        "train_size": len(X_train),
        "test_size": len(X_test),
        "train_period": f"{d_train[0].date()} a {d_train[-1].date()}",
        "test_period": f"{d_test[0].date()} a {d_test[-1].date()}",
    }
    with open(OUTPUT_DIR / "metrics.pkl", "wb") as f:
        pickle.dump(metrics_full, f)

    print("Modelo v2 salvo com sucesso!")
    print(f"\n{'=' * 60}")
    print("TREINAMENTO v2 CONCLUÍDO!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
