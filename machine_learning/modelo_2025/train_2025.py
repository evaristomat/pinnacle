"""
Treinamento do modelo UNDER/OVER total_kills - DADOS 2025.
Usa MÉDIA DA LIGA como target (1 modelo único).

- 1 modelo único
- Regressão Logística
- StandardScaler para normalização
- Train/Test Split 80/20
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score, classification_report, confusion_matrix
import warnings
warnings.filterwarnings('ignore')

# Caminhos - modelo 2025
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "models"
OUTPUT_DIR.mkdir(exist_ok=True)

# Parâmetros do modelo
TEST_SIZE = 0.2
RANDOM_STATE = 42


def load_data():
    """Carrega dados pré-processados."""
    print("Carregando dados pré-processados...")
    
    features_df = pd.read_csv(DATA_DIR / "features.csv")
    labels = np.load(DATA_DIR / "labels.npy")
    
    with open(DATA_DIR / "league_stats.pkl", "rb") as f:
        league_stats = pickle.load(f)
    
    with open(DATA_DIR / "champion_impacts.pkl", "rb") as f:
        champion_impacts = pickle.load(f)
    
    with open(DATA_DIR / "feature_columns.pkl", "rb") as f:
        feature_columns = pickle.load(f)
    
    print(f"  Features: {features_df.shape}")
    print(f"  Labels: {labels.shape}")
    print(f"  Distribuição: UNDER={np.sum(labels == 0)}, OVER={np.sum(labels == 1)}")
    
    return features_df, labels, league_stats, champion_impacts, feature_columns


def train_model(X_train, y_train, X_test, y_test):
    """
    Treina um modelo de Regressão Logística.
    
    Returns:
        Modelo treinado, scaler, métricas
    """
    # Normalização
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Treina modelo
    model = LogisticRegression(
        max_iter=1000,
        random_state=RANDOM_STATE,
        class_weight='balanced'  # Balanceia classes desbalanceadas
    )
    
    model.fit(X_train_scaled, y_train)
    
    # Predições
    y_pred = model.predict(X_test_scaled)
    y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
    
    # Métricas
    accuracy = accuracy_score(y_test, y_pred)
    roc_auc = roc_auc_score(y_test, y_pred_proba)
    
    return model, scaler, {
        'accuracy': accuracy,
        'roc_auc': roc_auc,
        'y_pred': y_pred,
        'y_pred_proba': y_pred_proba,
        'y_test': y_test
    }


def main():
    """Pipeline completo de treinamento."""
    print("=" * 60)
    print("TREINAMENTO DO MODELO UNDER/OVER TOTAL_KILLS - 2025")
    print("Usando MÉDIA DA LIGA como target (1 modelo único)")
    print("=" * 60)
    
    # Carrega dados
    features_df, labels, league_stats, champion_impacts, feature_columns = load_data()
    
    # Prepara features
    X = features_df.values
    
    print(f"\nTreinando modelo único...")
    print(f"Train/Test Split: {int((1-TEST_SIZE)*100)}%/{int(TEST_SIZE*100)}%")
    
    # Split train/test
    X_train, X_test, y_train, y_test = train_test_split(
        X, labels, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=labels
    )
    
    print(f"  Train: {len(X_train)} amostras")
    print(f"  Test: {len(X_test)} amostras")
    print(f"  Distribuição train: UNDER={np.sum(y_train == 0)}, OVER={np.sum(y_train == 1)}")
    print(f"  Distribuição test: UNDER={np.sum(y_test == 0)}, OVER={np.sum(y_test == 1)}")
    
    # Treina modelo
    model, scaler, metrics = train_model(X_train, y_train, X_test, y_test)
    
    # Mostra métricas
    print(f"\n{'='*60}")
    print("MÉTRICAS DO MODELO")
    print(f"{'='*60}")
    print(f"\n  Accuracy: {metrics['accuracy']:.4f}")
    print(f"  ROC-AUC: {metrics['roc_auc']:.4f}")
    
    # Classification report
    print(f"\n  Classification Report:")
    report = classification_report(y_test, metrics['y_pred'], 
                                 target_names=['UNDER', 'OVER'], 
                                 output_dict=True)
    print(f"    UNDER - Precision: {report['UNDER']['precision']:.4f}, "
          f"Recall: {report['UNDER']['recall']:.4f}, "
          f"F1: {report['UNDER']['f1-score']:.4f}")
    print(f"    OVER - Precision: {report['OVER']['precision']:.4f}, "
          f"Recall: {report['OVER']['recall']:.4f}, "
          f"F1: {report['OVER']['f1-score']:.4f}")
    
    # Confusion Matrix
    cm = confusion_matrix(y_test, metrics['y_pred'])
    print(f"\n  Confusion Matrix:")
    print(f"                Predito")
    print(f"              UNDER  OVER")
    print(f"    Real UNDER   {cm[0,0]:4d}   {cm[0,1]:4d}")
    print(f"         OVER    {cm[1,0]:4d}   {cm[1,1]:4d}")
    
    # Salva modelo
    print(f"\n{'='*60}")
    print("Salvando modelo...")
    
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
    
    # Salva métricas completas
    metrics_full = {
        'accuracy': metrics['accuracy'],
        'roc_auc': metrics['roc_auc'],
        'classification_report': report,
        'confusion_matrix': cm.tolist(),
        'y_test': y_test.tolist(),
        'y_pred': metrics['y_pred'].tolist(),
        'y_pred_proba': metrics['y_pred_proba'].tolist()
    }
    
    with open(OUTPUT_DIR / "metrics.pkl", "wb") as f:
        pickle.dump(metrics_full, f)
    
    print("Modelo salvo com sucesso!")
    
    print(f"\n{'='*60}")
    print("TREINAMENTO CONCLUÍDO!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
