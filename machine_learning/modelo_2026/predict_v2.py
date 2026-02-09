"""
Predição usando modelo treinado v2 - DADOS 2026.

Mudanças vs v1:
  - Usa parâmetros calibrados de z-score (sigmoid_k, adjust_strength)
  - Fallback para constantes v1 (0.5, 0.3) se calibração não disponível
"""

import numpy as np
import pickle
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
DATA_DIR = BASE_DIR / "data"

# Constantes fallback (v1)
DEFAULT_SIGMOID_K = 0.5
DEFAULT_ADJUST_STRENGTH = 0.3


def load_model():
    """Carrega todos os componentes do modelo v2."""
    print("Carregando modelo 2026 v2...")

    with open(MODELS_DIR / "model.pkl", "rb") as f:
        model = pickle.load(f)
    with open(MODELS_DIR / "scaler.pkl", "rb") as f:
        scaler = pickle.load(f)
    with open(MODELS_DIR / "champion_impacts.pkl", "rb") as f:
        champion_impacts = pickle.load(f)
    with open(MODELS_DIR / "league_stats.pkl", "rb") as f:
        league_stats = pickle.load(f)
    with open(MODELS_DIR / "feature_columns.pkl", "rb") as f:
        feature_columns = pickle.load(f)

    # z-score calibrado (fallback para v1 se não existir)
    z_cal_path = MODELS_DIR / "z_calibration.pkl"
    if z_cal_path.exists():
        with open(z_cal_path, "rb") as f:
            z_calibration = pickle.load(f)
        print(f"  Z-score calibrado: sigmoid_k={z_calibration['sigmoid_k']}, "
              f"adjust_strength={z_calibration['adjust_strength']}")
    else:
        z_calibration = {
            "sigmoid_k": DEFAULT_SIGMOID_K,
            "adjust_strength": DEFAULT_ADJUST_STRENGTH,
        }
        print("  Z-score: usando fallback (constantes v1)")

    print("Modelo v2 carregado com sucesso!")
    return model, scaler, champion_impacts, league_stats, feature_columns, z_calibration


def create_features_from_game(
    game_data: Dict,
    league_stats: Dict,
    champion_impacts: Dict,
    feature_columns: List[str],
) -> np.ndarray:
    """Cria features a partir dos dados de um jogo (idêntico a v1)."""
    league = game_data["league"]
    league_impacts = champion_impacts.get(league, {})

    def norm(champ):
        return str(champ).strip() if champ else ""

    t1 = [league_impacts.get(norm(game_data.get(f"{r}_t1", "")), 0.0)
          for r in ("top", "jung", "mid", "adc", "sup")]
    t2 = [league_impacts.get(norm(game_data.get(f"{r}_t2", "")), 0.0)
          for r in ("top", "jung", "mid", "adc", "sup")]

    team1_avg = float(np.mean(t1))
    team2_avg = float(np.mean(t2))

    fd = {
        "league_mean": league_stats.get(league, {}).get("mean", 0.0),
        "league_std": league_stats.get(league, {}).get("std", 0.0),
        "team1_avg_impact": team1_avg,
        "team2_avg_impact": team2_avg,
        "impact_diff": team1_avg - team2_avg,
        "top_t1_impact": t1[0], "jung_t1_impact": t1[1], "mid_t1_impact": t1[2],
        "adc_t1_impact": t1[3], "sup_t1_impact": t1[4],
        "top_t2_impact": t2[0], "jung_t2_impact": t2[1], "mid_t2_impact": t2[2],
        "adc_t2_impact": t2[3], "sup_t2_impact": t2[4],
    }

    for col in feature_columns:
        if col.startswith("league_") and col not in ("league_mean", "league_std"):
            liga_name = col.replace("league_", "")
            fd[col] = 1.0 if liga_name == league else 0.0

    features = np.array([fd.get(col, 0.0) for col in feature_columns])
    return features.reshape(1, -1)


def predict_over_league_mean(
    game_data: Dict, model, scaler,
    champion_impacts: Dict, league_stats: Dict,
    feature_columns: List[str],
) -> Dict:
    """Prediz se total_kills será OVER da média da liga."""
    X = create_features_from_game(game_data, league_stats, champion_impacts, feature_columns)
    X_scaled = scaler.transform(X)

    prob_over_mean = float(model.predict_proba(X_scaled)[0, 1])
    prob_under_mean = 1.0 - prob_over_mean

    if prob_over_mean >= 0.5:
        prediction, confidence_percent = "OVER", prob_over_mean * 100
    else:
        prediction, confidence_percent = "UNDER", prob_under_mean * 100

    confidence = "High" if prob_over_mean >= 0.70 or prob_over_mean <= 0.30 else "Medium"

    return {
        "probability_over_mean": prob_over_mean,
        "probability_under_mean": prob_under_mean,
        "prediction": prediction,
        "confidence": confidence,
        "confidence_percent": confidence_percent,
        "league_mean": league_stats.get(game_data["league"], {}).get("mean", 0.0),
    }


def predict_for_betting_line(
    game_data: Dict, betting_line: float,
    model, scaler,
    champion_impacts: Dict, league_stats: Dict,
    feature_columns: List[str],
    z_calibration: Optional[Dict] = None,
) -> Dict:
    """
    Prediz para uma linha específica da casa de apostas.
    Usa parâmetros calibrados de z-score (sigmoid_k, adjust_strength).
    """
    league = game_data["league"]
    league_mean = league_stats.get(league, {}).get("mean", 0.0)
    league_std = league_stats.get(league, {}).get("std", 1.0)

    pred_mean = predict_over_league_mean(
        game_data, model, scaler, champion_impacts, league_stats, feature_columns)
    prob_over_mean = pred_mean["probability_over_mean"]

    # Parâmetros de z-score (calibrados ou fallback)
    if z_calibration:
        sigmoid_k = z_calibration.get("sigmoid_k", DEFAULT_SIGMOID_K)
        adjust_strength = z_calibration.get("adjust_strength", DEFAULT_ADJUST_STRENGTH)
    else:
        sigmoid_k = DEFAULT_SIGMOID_K
        adjust_strength = DEFAULT_ADJUST_STRENGTH

    if league_std > 0:
        z_score = (betting_line - league_mean) / league_std
        adjustment = 1.0 / (1.0 + np.exp(-z_score * sigmoid_k))

        if betting_line > league_mean:
            prob_over_line = prob_over_mean * (1.0 - adjustment * adjust_strength)
        else:
            prob_over_line = prob_over_mean + (1.0 - prob_over_mean) * adjustment * adjust_strength

        prob_over_line = float(np.clip(prob_over_line, 0.0, 1.0))
    else:
        prob_over_line = prob_over_mean

    prob_under_line = 1.0 - prob_over_line

    if prob_over_line >= 0.5:
        prediction, confidence_percent = "OVER", prob_over_line * 100
    else:
        prediction, confidence_percent = "UNDER", prob_under_line * 100

    threshold = 0.65
    bet_over = prob_over_line >= threshold
    bet_under = prob_under_line >= threshold

    confidence = "High" if prob_over_line >= 0.70 or prob_over_line <= 0.30 else "Medium"

    return {
        "betting_line": betting_line,
        "league_mean": league_mean,
        "difference": betting_line - league_mean,
        "probability_over_line": prob_over_line,
        "probability_under_line": prob_under_line,
        "prediction": prediction,
        "confidence": confidence,
        "confidence_percent": confidence_percent,
        "bet_over": bet_over,
        "bet_under": bet_under,
        "probability_over_mean": prob_over_mean,
        "z_calibration_used": {
            "sigmoid_k": sigmoid_k,
            "adjust_strength": adjust_strength,
        },
    }


def main():
    """Exemplo de uso."""
    model, scaler, champion_impacts, league_stats, feature_columns, z_cal = load_model()

    game_example = {
        "league": "LCK",
        "top_t1": "Aatrox", "jung_t1": "Graves", "mid_t1": "Azir",
        "adc_t1": "Jinx", "sup_t1": "Thresh",
        "top_t2": "Gnar", "jung_t2": "Sejuani", "mid_t2": "Orianna",
        "adc_t2": "Aphelios", "sup_t2": "Braum",
    }

    print(f"\n{'=' * 60}")
    print("EXEMPLO DE PREDIÇÃO - MODELO v2 2026")
    print(f"{'=' * 60}")
    print(f"\nJogo: {game_example['league']}")

    pred_mean = predict_over_league_mean(
        game_example, model, scaler, champion_impacts, league_stats, feature_columns)
    print(f"\nOVER/UNDER MÉDIA DA LIGA:")
    print(f"  Média: {pred_mean['league_mean']:.2f} kills")
    print(f"  P(OVER média): {pred_mean['probability_over_mean']:.1%}")
    print(f"  Predição: {pred_mean['prediction']} ({pred_mean['confidence_percent']:.1f}%)")

    betting_line = 28.5
    pred_line = predict_for_betting_line(
        game_example, betting_line, model, scaler,
        champion_impacts, league_stats, feature_columns, z_cal)

    print(f"\nOVER/UNDER LINHA {betting_line}:")
    print(f"  Diferença: {pred_line['difference']:+.2f}")
    print(f"  P(OVER {betting_line}): {pred_line['probability_over_line']:.1%}")
    print(f"  Predição: {pred_line['prediction']} ({pred_line['confidence_percent']:.1f}%)")
    print(f"  Z-score params: {pred_line['z_calibration_used']}")


if __name__ == "__main__":
    main()
