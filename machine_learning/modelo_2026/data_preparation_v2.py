"""
Preparação de dados para o modelo ML v2 de total_kills UNDER/OVER - DADOS 2026.

Mudanças vs v1:
  - Mínimo 5 jogos por campeão/liga para calcular impacto (era 3)
  - Preserva coluna `date` no output para permitir split temporal
  - Usa dataset completo atualizado (~1014 jogos vs 587)
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent.parent
CSV_PATH = PROJECT_ROOT / "database_improved" / "data_transformed.csv"
OUTPUT_DIR = BASE_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

# Mínimo de jogos para um campeão ter impacto != 0
MIN_CHAMPION_GAMES = 5


def load_data() -> pd.DataFrame:
    """Carrega dados 2026 do data_transformed.csv."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"Arquivo {CSV_PATH} não encontrado!\n"
            f"Execute: cd database_improved && python main.py"
        )
    print(f"Carregando dados de {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH)
    if "year" in df.columns:
        df = df[df["year"] == 2026].copy()
    print(f"  Partidas 2026: {len(df)}")

    # Garante coluna date como datetime
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        print(f"  Periodo: {df['date'].min().date()} a {df['date'].max().date()}")
    else:
        raise ValueError("Coluna 'date' não encontrada - necessária para split temporal.")

    required = ["league", "total_kills", "top_t1", "jung_t1", "mid_t1", "adc_t1", "sup_t1",
                 "top_t2", "jung_t2", "mid_t2", "adc_t2", "sup_t2"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas faltando: {missing}")
    return df


def calculate_league_stats(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Média e std de total_kills por liga."""
    league_stats = {}
    for league in df["league"].unique():
        if pd.isna(league):
            continue
        data = df[df["league"] == league]["total_kills"].dropna()
        if len(data) == 0:
            continue
        mean_val = data.mean()
        std_val = data.std()
        if pd.isna(std_val) or std_val == 0:
            std_val = 1.0
        league_stats[league] = {
            "mean": float(mean_val) if not pd.isna(mean_val) else 0.0,
            "std": float(std_val),
        }
    print(f"\nEstatísticas por liga ({len(league_stats)} ligas):")
    for lg, s in sorted(league_stats.items()):
        n = len(df[df["league"] == lg])
        print(f"  {lg}: mean={s['mean']:.1f}, std={s['std']:.1f}, n={n}")
    return league_stats


def calculate_champion_impacts(
    df: pd.DataFrame, league_stats: Dict[str, Dict[str, float]]
) -> Dict[str, Dict[str, float]]:
    """Impacto de cada campeão por liga. Mínimo MIN_CHAMPION_GAMES jogos."""
    champ_kills: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    champ_cols = [
        "top_t1", "jung_t1", "mid_t1", "adc_t1", "sup_t1",
        "top_t2", "jung_t2", "mid_t2", "adc_t2", "sup_t2",
    ]
    for _, row in df.iterrows():
        if pd.isna(row["total_kills"]) or pd.isna(row["league"]):
            continue
        league = row["league"]
        tk = row["total_kills"]
        for col in champ_cols:
            if col not in df.columns:
                continue
            champ = row[col]
            if pd.notna(champ) and str(champ).strip():
                champ_kills[league][str(champ).strip()].append(tk)

    impacts: Dict[str, Dict[str, float]] = {}
    total_with_impact = 0
    total_zero = 0
    for league in champ_kills:
        if league not in league_stats:
            continue
        league_mean = league_stats[league]["mean"]
        impacts[league] = {}
        for champ, kills_list in champ_kills[league].items():
            if len(kills_list) >= MIN_CHAMPION_GAMES:
                impacts[league][champ] = float(np.mean(kills_list) - league_mean)
                total_with_impact += 1
            else:
                impacts[league][champ] = 0.0
                total_zero += 1

    print(f"\nChampion impacts (min {MIN_CHAMPION_GAMES} jogos):")
    print(f"  Com impacto: {total_with_impact}")
    print(f"  Impacto zero (< {MIN_CHAMPION_GAMES} jogos): {total_zero}")
    print(f"  Ligas: {len(impacts)}")
    return impacts


def create_features(
    df: pd.DataFrame,
    league_stats: Dict[str, Dict[str, float]],
    champion_impacts: Dict[str, Dict[str, float]],
) -> pd.DataFrame:
    """Cria features. Preserva coluna `date` para split temporal."""
    features_list = []
    valid_indices = []
    leagues = sorted([lg for lg in df["league"].dropna().unique() if lg in league_stats])

    def norm(champ):
        return str(champ).strip() if pd.notna(champ) else ""

    for idx, row in df.iterrows():
        if pd.isna(row["total_kills"]) or pd.isna(row["league"]):
            continue
        league = row["league"]
        if league not in league_stats:
            continue
        li = champion_impacts.get(league, {})

        t1 = [li.get(norm(row.get(f"{r}_t1", "")), 0.0) for r in ["top", "jung", "mid", "adc", "sup"]]
        t2 = [li.get(norm(row.get(f"{r}_t2", "")), 0.0) for r in ["top", "jung", "mid", "adc", "sup"]]

        team1_avg = float(np.mean(t1))
        team2_avg = float(np.mean(t2))

        fd = {
            "league_mean": league_stats[league]["mean"],
            "league_std": league_stats[league]["std"],
            "team1_avg_impact": team1_avg,
            "team2_avg_impact": team2_avg,
            "impact_diff": team1_avg - team2_avg,
            "top_t1_impact": t1[0], "jung_t1_impact": t1[1], "mid_t1_impact": t1[2],
            "adc_t1_impact": t1[3], "sup_t1_impact": t1[4],
            "top_t2_impact": t2[0], "jung_t2_impact": t2[1], "mid_t2_impact": t2[2],
            "adc_t2_impact": t2[3], "sup_t2_impact": t2[4],
        }
        for lg in leagues:
            fd[f"league_{lg}"] = 1.0 if lg == league else 0.0

        features_list.append(fd)
        valid_indices.append(idx)

    features_df = pd.DataFrame(features_list).fillna(0.0)
    features_df.index = valid_indices

    # Preserva date e total_kills alinhados para o treino
    dates = df.loc[valid_indices, "date"].values
    total_kills = df.loc[valid_indices, "total_kills"].values
    leagues_arr = df.loc[valid_indices, "league"].values

    print(f"\nFeatures: {features_df.shape[1]} colunas, {len(features_df)} amostras")
    return features_df, dates, total_kills, leagues_arr


def create_labels_loo(
    df: pd.DataFrame, valid_indices: list, league_stats: Dict[str, Dict[str, float]]
) -> np.ndarray:
    """Labels com leave-one-out na média da liga."""
    loo_means = {}
    for idx in valid_indices:
        row = df.loc[idx]
        league = row["league"]
        if pd.isna(league):
            continue
        other = df[(df["league"] == league) & (df.index != idx)]["total_kills"].dropna()
        if len(other) == 0:
            m = df[df["league"] == league]["total_kills"].mean()
            loo_means[idx] = float(m) if not pd.isna(m) else 0.0
        else:
            loo_means[idx] = float(other.mean())

    y = []
    for idx in valid_indices:
        row = df.loc[idx]
        tk = row["total_kills"]
        mean_loo = loo_means.get(idx, league_stats.get(row["league"], {}).get("mean", 0.0))
        y.append(1 if tk > mean_loo else 0)

    y = np.array(y)
    print(f"\nLabels (leave-one-out):")
    print(f"  UNDER: {np.sum(y == 0)} ({np.sum(y == 0)/len(y)*100:.1f}%)")
    print(f"  OVER:  {np.sum(y == 1)} ({np.sum(y == 1)/len(y)*100:.1f}%)")
    return y


def main():
    print("=" * 60)
    print("DATA PREPARATION v2 - MODELO 2026")
    print(f"Min champion games: {MIN_CHAMPION_GAMES} | Split temporal | Dataset completo")
    print("=" * 60)

    df = load_data()
    league_stats = calculate_league_stats(df)
    champion_impacts = calculate_champion_impacts(df, league_stats)
    features_df, dates, total_kills, leagues_arr = create_features(df, league_stats, champion_impacts)

    valid_indices = list(features_df.index)
    labels = create_labels_loo(df, valid_indices, league_stats)

    # Salva
    print(f"\nSalvando em {OUTPUT_DIR}...")
    features_df.to_csv(OUTPUT_DIR / "features.csv", index=False)
    np.save(OUTPUT_DIR / "labels.npy", labels)
    np.save(OUTPUT_DIR / "dates.npy", dates)
    np.save(OUTPUT_DIR / "total_kills.npy", total_kills)

    with open(OUTPUT_DIR / "leagues_array.pkl", "wb") as f:
        pickle.dump(leagues_arr, f)
    with open(OUTPUT_DIR / "league_stats.pkl", "wb") as f:
        pickle.dump(league_stats, f)
    with open(OUTPUT_DIR / "champion_impacts.pkl", "wb") as f:
        pickle.dump(champion_impacts, f)
    with open(OUTPUT_DIR / "feature_columns.pkl", "wb") as f:
        pickle.dump(list(features_df.columns), f)

    print("Dados salvos!")
    print("=" * 60)


if __name__ == "__main__":
    main()
