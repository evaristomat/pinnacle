"""
Cliente OpenDota API para obter resultados de partidas de Dota 2.
Usado pelo ResultMatcher quando PINNACLE_ESPORT=dota2 para cruzar jogos do pinnacle_dota.db.

API: https://docs.opendota.com/#tag/pro-matches
GET /api/proMatches?less_than_match_id=X retorna até 100 partidas (mais recentes primeiro).
"""
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None

from config import DATE_TOLERANCE_HOURS

OPENDOTA_PRO_MATCHES = "https://api.opendota.com/api/proMatches"
# Evitar rate limit (API livre ~1-2 req/s)
REQUEST_DELAY_SEC = 1.2
MAX_MATCHES_FETCH = 500  # quantas partidas buscar (5 páginas de 100)


def _remove_accents(s: str) -> str:
    """Remove acentos para comparação (Divisão -> Divisao, etc.)."""
    if not s:
        return s
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    """Normaliza para comparação: minúsculo, sem acentos, sem espaços extras, remove pontuação comum."""
    if not s or not isinstance(s, str):
        return ""
    s = _remove_accents(s)
    s = re.sub(r"\s+", " ", s.strip().lower())
    s = s.replace(".", "").replace(",", "")
    return s


def _league_match(league_bet: str, league_api: str) -> bool:
    """True se as ligas correspondem (exato ou um contém o outro)."""
    a, b = _norm(league_bet), _norm(league_api)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    # Partes em comum (ex: "DreamLeague Division 2")
    words_a = set(a.split())
    words_b = set(b.split())
    overlap = len(words_a & words_b) / max(len(words_a), 1)
    return overlap >= 0.5


def _team_match(name_bet: str, name_api: str) -> bool:
    """True se os nomes de time correspondem."""
    a, b = _norm(name_bet), _norm(name_api)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return False


def fetch_pro_matches(less_than_match_id: Optional[int] = None) -> List[Dict]:
    """
    Busca uma página de pro matches no OpenDota.
    less_than_match_id: para paginação (próximas mais antigas).
    """
    if requests is None:
        return []
    url = OPENDOTA_PRO_MATCHES
    params = {}
    if less_than_match_id is not None:
        params["less_than_match_id"] = less_than_match_id
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json() or []
    except Exception as e:
        print(f"   [OpenDota] Erro ao buscar partidas: {e}")
        return []


def load_pro_matches(max_matches: int = MAX_MATCHES_FETCH) -> List[Dict]:
    """
    Carrega várias páginas de pro matches (mais recentes primeiro).
    Retorna lista de dicts com: match_id, start_time, radiant_name, dire_name,
    radiant_win, radiant_score, dire_score, league_name, etc.
    """
    all_matches = []
    less_than = None
    page = 0
    while len(all_matches) < max_matches:
        page += 1
        batch = fetch_pro_matches(less_than_match_id=less_than)
        if not batch:
            break
        for m in batch:
            all_matches.append(m)
            if len(all_matches) >= max_matches:
                break
        if len(batch) < 100:
            break
        less_than = batch[-1].get("match_id")
        if less_than is None:
            break
        time.sleep(REQUEST_DELAY_SEC)
    return all_matches


def find_match_for_bet(
    league_name: str,
    home_team: str,
    away_team: str,
    game_date: str,
    mapa: Optional[int] = None,
    matches_cache: Optional[List[Dict]] = None,
) -> Optional[Dict]:
    """
    Encontra uma partida OpenDota que corresponda ao jogo da aposta.

    Args:
        league_name: nome da liga (Pinnacle)
        home_team: time da casa (Pinnacle)
        away_team: time visitante (Pinnacle)
        game_date: data do jogo (ISO ou YYYY-MM-DD)
        mapa: mapa do jogo (opcional; OpenDota não tem mapa, cada match_id é um jogo)
        matches_cache: lista de partidas já buscadas (evita refetch)

    Returns:
        Dict no formato esperado pelo ResultMatcher:
        {
            'total_kills': radiant_score + dire_score,
            'date': datetime do jogo,
            'confidence': 0.0-1.0,
            'match_info': { 'league', 't1', 't2', 'date', 'game': None }
        }
        ou None se não encontrar.
    """
    try:
        bet_dt = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
    except Exception:
        try:
            bet_dt = datetime.strptime(game_date[:10], "%Y-%m-%d")
        except Exception:
            return None
    # Pinnacle sem fuso: assumir UTC para comparar com OpenDota (timestamps UTC)
    if bet_dt.tzinfo is None:
        bet_dt = bet_dt.replace(tzinfo=timezone.utc)
    bet_dt_naive_utc = bet_dt.astimezone(timezone.utc).replace(tzinfo=None)

    if matches_cache is None:
        matches_cache = load_pro_matches()

    tolerance = timedelta(hours=DATE_TOLERANCE_HOURS)
    best = None
    best_score = 0.0

    for m in matches_cache:
        api_league = (m.get("league_name") or "").strip()
        radiant = (m.get("radiant_name") or "").strip()
        dire = (m.get("dire_name") or "").strip()
        start_time = m.get("start_time")
        if start_time is None:
            continue
        try:
            match_dt = datetime.fromtimestamp(int(start_time), tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            continue

        if not _league_match(league_name, api_league):
            continue
        if abs(match_dt - bet_dt_naive_utc) > tolerance:
            continue

        # Pinnacle home/away pode ser em qualquer ordem vs radiant/dire
        home_radiant = _team_match(home_team, radiant) and _team_match(away_team, dire)
        home_dire = _team_match(home_team, dire) and _team_match(away_team, radiant)
        if not (home_radiant or home_dire):
            continue

        # Confiança: liga exata + data próxima
        score = 0.7
        if _norm(league_name) == _norm(api_league):
            score += 0.2
        delta_h = abs((match_dt - bet_dt_naive_utc).total_seconds()) / 3600
        if delta_h < 1:
            score += 0.1
        elif delta_h < 6:
            score += 0.05

        if score > best_score:
            best_score = score
            radiant_score = int(m.get("radiant_score") or 0)
            dire_score = int(m.get("dire_score") or 0)
            total_kills = radiant_score + dire_score
            best = {
                "total_kills": total_kills,
                "date": match_dt,
                "confidence": min(score, 1.0),
                "match_info": {
                    "league": api_league,
                    "t1": radiant,
                    "t2": dire,
                    "date": match_dt,
                    "game": mapa,
                },
            }

    return best
