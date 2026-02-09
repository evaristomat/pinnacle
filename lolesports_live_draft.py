"""
Helpers para buscar draft ao vivo via LoL Esports API.

Fluxo correto (sem hacks de matchId + N):
- getSchedule/getLive (esports-api.lolesports.com) -> obter match id
- getEventDetails(matchId) -> obter lista de games com gameId por mapa
- feed.lolesports.com/livestats/v1/window/{gameId} -> obter participantMetadata (championId/role)

Referências (docs não-oficiais, mas consistentes com o comportamento real):
- https://vickz84259.github.io/lolesports-api-docs/
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


LOLESPORTS_API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
SCHEDULE_URL = "https://esports-api.lolesports.com/persisted/gw/getSchedule"
LIVE_URL = "https://esports-api.lolesports.com/persisted/gw/getLive"
EVENT_DETAILS_URL = "https://esports-api.lolesports.com/persisted/gw/getEventDetails"
WINDOW_URL_FMT = "https://feed.lolesports.com/livestats/v1/window/{game_id}"


def _headers() -> Dict[str, str]:
    return {
        "x-api-key": LOLESPORTS_API_KEY,
        "User-Agent": "Mozilla/5.0",
        "accept": "application/json",
    }


def _norm(s: str) -> str:
    """Normaliza texto para comparação (lower + remove não-alfanum)."""
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _league_tokens(league_name: str) -> List[str]:
    """Extrai tokens úteis para casar ligas (bem simples, mas robusto)."""
    s = (league_name or "").lower()
    # remove prefixo comum
    s = s.replace("league of legends -", "").strip()
    tokens = []
    for t in ["lck", "lpl", "lec", "lcs", "cblol", "pcs", "vcs", "lla", "ljl", "lco", "tcl", "emea", "msi", "worlds"]:
        if t in s:
            tokens.append(t)
    # fallback: tokenização básica
    if not tokens:
        tokens = [w for w in re.split(r"[^a-z0-9]+", s) if w]
    return tokens


@dataclass(frozen=True)
class MatchCandidate:
    match_id: str
    league_name: str
    team1_name: str
    team2_name: str
    start_time: Optional[datetime]
    score: float


def fetch_schedule(hl: str = "en-US", timeout_s: int = 10) -> List[Dict[str, Any]]:
    resp = requests.get(SCHEDULE_URL, headers=_headers(), params={"hl": hl}, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("data") or {}).get("schedule", {}).get("events", []) or []


def fetch_live(hl: str = "en-US", timeout_s: int = 10) -> List[Dict[str, Any]]:
    resp = requests.get(LIVE_URL, headers=_headers(), params={"hl": hl}, timeout=timeout_s)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("data") or {}).get("schedule", {}).get("events", []) or []


def find_best_match_id(
    events: Iterable[Dict[str, Any]],
    *,
    league_name: str,
    team1: str,
    team2: str,
    start_time_iso: Optional[str] = None,
) -> Optional[MatchCandidate]:
    """
    Tenta achar o match do LoL Esports para um jogo (Pinnacle) usando:
    - liga (por tokens)
    - times (por comparação normalizada)
    - horário (se disponível) para desempate
    """
    t1n = _norm(team1)
    t2n = _norm(team2)
    league_toks = _league_tokens(league_name)
    target_dt = _parse_iso(start_time_iso) if start_time_iso else None

    best: Optional[MatchCandidate] = None

    for ev in events:
        if ev.get("type") != "match":
            continue
        match = ev.get("match") or {}
        teams = match.get("teams") or []
        if len(teams) < 2:
            continue

        ev_league = (ev.get("league") or {}).get("name", "") or ""
        ev_league_n = _norm(ev_league)
        # filtro por tokens de liga (bem permissivo)
        if league_toks:
            if not any(tok in ev_league_n for tok in league_toks):
                continue

        a = teams[0]
        b = teams[1]
        a_name = a.get("name") or a.get("code") or ""
        b_name = b.get("name") or b.get("code") or ""
        a_n = _norm(a_name)
        b_n = _norm(b_name)

        # match score times (ordem pode inverter)
        direct = (t1n and t2n and (t1n in a_n or a_n in t1n) and (t2n in b_n or b_n in t2n))
        swapped = (t1n and t2n and (t1n in b_n or b_n in t1n) and (t2n in a_n or a_n in t2n))
        team_score = 0.0
        if direct:
            team_score = 2.0
        elif swapped:
            team_score = 1.8
        else:
            # parcial: um time bate
            one = (t1n and (t1n in a_n or a_n in t1n or t1n in b_n or b_n in t1n))
            two = (t2n and (t2n in a_n or a_n in t2n or t2n in b_n or b_n in t2n))
            if one and two:
                team_score = 1.5
            elif one or two:
                team_score = 0.6
            else:
                continue

        ev_dt = _parse_iso(ev.get("startTime", ""))
        time_penalty = 0.0
        if target_dt and ev_dt:
            diff_min = abs((ev_dt - target_dt).total_seconds()) / 60.0
            # penaliza diferença grande, mas não mata o match
            time_penalty = min(1.2, diff_min / 180.0)  # 3h -> 1.0 aprox

        score = team_score - time_penalty

        cand = MatchCandidate(
            match_id=str(match.get("id", "")),
            league_name=ev_league,
            team1_name=a_name,
            team2_name=b_name,
            start_time=ev_dt,
            score=score,
        )
        if not cand.match_id or cand.match_id == "N/A":
            continue

        if best is None or cand.score > best.score:
            best = cand

    return best


def fetch_event_details(match_id: str, hl: str = "en-US", timeout_s: int = 10) -> Dict[str, Any]:
    resp = requests.get(EVENT_DETAILS_URL, headers=_headers(), params={"hl": hl, "id": match_id}, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def extract_game_ids_by_map(event_details: Dict[str, Any]) -> Tuple[Dict[int, str], Dict[int, Dict[str, str]]]:
    """
    Retorna:
    - map_number -> gameId
    - map_number -> {"blue": teamId, "red": teamId} (se disponível)
    """
    out: Dict[int, str] = {}
    sides: Dict[int, Dict[str, str]] = {}

    event = (event_details.get("data") or {}).get("event") or {}
    match = (event.get("match") or {})
    games = match.get("games") or []

    for g in games:
        try:
            num = int(g.get("number") or 0)
        except Exception:
            continue
        gid = str(g.get("id") or "")
        if num <= 0 or not gid:
            continue
        out[num] = gid

        st = {}
        for t in (g.get("teams") or []):
            side = (t.get("side") or "").lower()
            tid = str(t.get("id") or "")
            if side in ("blue", "red") and tid:
                st[side] = tid
        if st:
            sides[num] = st

    return out, sides


def extract_match_team_names(event_details: Dict[str, Any]) -> Dict[str, str]:
    """teamId -> teamName"""
    out: Dict[str, str] = {}
    event = (event_details.get("data") or {}).get("event") or {}
    match = (event.get("match") or {})
    for t in (match.get("teams") or []):
        tid = str(t.get("id") or "")
        name = t.get("name") or t.get("code") or ""
        if tid and name:
            out[tid] = name
    return out


def fetch_window(game_id: str, timeout_s: int = 7) -> Dict[str, Any]:
    url = WINDOW_URL_FMT.format(game_id=game_id)
    resp = requests.get(url, timeout=timeout_s)
    resp.raise_for_status()
    return resp.json()


def extract_draft_from_window(window: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    Retorna:
    {"blue": {"top": "...", "jung": "...", "mid": "...", "adc": "...", "sup": "..."},
     "red":  {...}}
    """
    meta = window.get("gameMetadata") or {}
    blue = (meta.get("blueTeamMetadata") or {}).get("participantMetadata") or []
    red = (meta.get("redTeamMetadata") or {}).get("participantMetadata") or []

    def role_to_key(role: str) -> Optional[str]:
        r = (role or "").lower()
        if r == "top":
            return "top"
        if r in ("jungle", "jung"):
            return "jung"
        if r == "mid":
            return "mid"
        if r in ("bot", "bottom", "adc"):
            return "adc"
        if r in ("support", "sup"):
            return "sup"
        return None

    def parse_team(participants: List[Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        # Preferencialmente pelo campo role; fallback por ordem
        for p in participants:
            champ = p.get("championId") or ""
            key = role_to_key(p.get("role") or "")
            if key and champ:
                out[key] = str(champ)
        if len(out) < 5:
            # fallback por ordem (TOP,JUNG,MID,ADC,SUP) como no app antigo
            order = ["top", "jung", "mid", "adc", "sup"]
            for i, p in enumerate(participants[:5]):
                champ = p.get("championId") or ""
                if not champ:
                    continue
                k = order[i]
                out.setdefault(k, str(champ))
        return out

    return {"blue": parse_team(blue), "red": parse_team(red)}

