"""
Teste do WebSocket Pinnacle: puxa um jogo completo (odds normais + specials).
Uso: python test_websocket_game.py [event_id]
  Se event_id não for passado, tenta obter do pinnacle_matchups.json ou usa um fixo.
Requer: PINNACLE_LOGIN_TOKEN no .env (token base64 do login no site) para auth.
  Opcional: tentar só wstoken com cookies atuais (pode falhar sem login).
"""
import os
import sys
import json
import asyncio
from pathlib import Path

# Carrega .env se existir
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent

# Configuração
BASE_URL = "https://sports.pinnacle.bet.br"
WS_URL = "wss://sports.pinnacle.bet.br/sports-websocket/ws"
MATCHUPS_JSON = ROOT / "pinnacle_matchups.json"


def get_one_event_id() -> str | None:
    """Obtém um event_id do pinnacle_matchups.json (primeiro evento pai)."""
    if not MATCHUPS_JSON.exists():
        return None
    try:
        with open(MATCHUPS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        leagues = (data.get("response_data") or {}).get("data") or {}
        leagues_list = leagues.get("leagues") or []
        for league in leagues_list:
            for event in (league.get("events") or []):
                eid = event.get("id")
                parent = event.get("parentId", 0)
                if eid and parent == 0:
                    return str(eid)
    except Exception:
        pass
    return None


def get_wstoken_with_login() -> tuple[str | None, str]:
    """Passo 1+2: auth com LOGIN_TOKEN e depois GET wstoken. Retorna (wstoken, ulp)."""
    import requests
    login_token = os.getenv("PINNACLE_LOGIN_TOKEN", "").strip()
    if not login_token:
        return None, ""

    session = requests.Session()
    session.headers.update({
        "accept": "application/json",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    })
    session.get(BASE_URL, timeout=10)

    # Passo 1: auth-token
    auth_url = f"{BASE_URL}/member-auth/v2/auth-token"
    r1 = session.post(
        auth_url,
        params={"locale": "pt_BR", "withCredentials": "true"},
        json={
            "token": login_token,
            "locale": "pt",
            "oddsFormat": "EU",
            "sport": "esports/games/league-of-legends",
        },
        timeout=15,
    )
    if r1.status_code != 200:
        print(f"  [AVISO] auth-token status {r1.status_code}: {r1.text[:200]}")
        return None, ""
    try:
        auth_data = r1.json()
        if not auth_data.get("success"):
            print(f"  [AVISO] auth-token success=false: {auth_data}")
            return None, ""
    except Exception:
        return None, ""

    # Passo 2: wstoken
    r2 = session.get(
        f"{BASE_URL}/member-auth/v2/wstoken",
        params={"locale": "pt_BR", "withCredentials": "true"},
        timeout=15,
    )
    if r2.status_code != 200:
        print(f"  [AVISO] wstoken status {r2.status_code}: {r2.text[:200]}")
        return None, ""

    try:
        token_data = r2.json()
        wstoken = token_data.get("token") or ""
    except Exception:
        return None, ""

    ulp = ""
    for c in session.cookies:
        if c.name == "ulp":
            ulp = c.value or ""
            break

    return wstoken, ulp


def get_wstoken_guest() -> tuple[str | None, str]:
    """Tenta wstoken só com cookies atuais (sem login). Pode falhar."""
    import requests
    session = requests.Session()
    session.headers.update({
        "accept": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/pt/standard/esports/games/league-of-legends",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    })
    session.cookies.set("_sig", os.getenv("PINNACLE_SIG", ""), domain="sports.pinnacle.bet.br")
    session.cookies.set("_apt", os.getenv("PINNACLE_APT", ""), domain="sports.pinnacle.bet.br")
    session.cookies.set("pctag", os.getenv("PINNACLE_PCTAG", ""), domain="sports.pinnacle.bet.br")
    session.get(BASE_URL, timeout=10)

    r = session.get(
        f"{BASE_URL}/member-auth/v2/wstoken",
        params={"locale": "pt_BR", "withCredentials": "true"},
        timeout=15,
    )
    if r.status_code != 200:
        return None, ""
    try:
        data = r.json()
        return (data.get("token") or ""), ""
    except Exception:
        return None, ""


async def fetch_full_game_ws(event_id: str, wstoken: str, ulp: str = "") -> dict | None:
    """Conecta WS, envia SUBSCRIBE, recebe FULL_ODDS e retorna odds (ou None)."""
    try:
        import websockets
    except ImportError:
        print("  Instale: pip install websockets")
        return None

    url = f"{WS_URL}?token={wstoken}&view=euro"
    if ulp:
        from urllib.parse import quote
        url += "&ulp=" + quote(ulp, safe="")

    async with websockets.connect(
        url,
        origin=BASE_URL,
        additional_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/144.0.0.0"},
        close_timeout=5,
    ) as ws:
        # CONNECTED
        msg = await ws.recv()
        obj = json.loads(msg)
        if obj.get("type") != "CONNECTED":
            print(f"  WS primeiro msg tipo inesperado: {obj.get('type')}")
            return None

        # SUBSCRIBE
        sub = {
            "type": "SUBSCRIBE",
            "destination": "EVENT_DETAILS_EURO_ODDS",
            "body": {
                "dpLk3": "E_MA3",
                "eventId": str(event_id),
                "oddsType": 1,
                "version": 0,
                "locale": "pt_BR",
            },
        }
        await ws.send(json.dumps(sub))

        # FULL_ODDS
        raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
        full = json.loads(raw)
        if full.get("type") != "FULL_ODDS":
            print(f"  WS resposta tipo inesperado: {full.get('type')}")
            return None
        return full.get("odds")


def summarize_odds(odds: dict) -> None:
    """Imprime resumo do jogo (normais, kills, specials)."""
    if not odds:
        return
    eid = odds.get("eventId", "?")
    print(f"\n  EventId: {eid}")
    print(f"  Chaves: {list(odds.keys())}")

    # normal
    normal = odds.get("normal") or {}
    if normal:
        print(f"\n  [normal] {json.dumps(normal, ensure_ascii=False)[:400]}...")

    # kills
    kills = odds.get("kills") or {}
    if kills:
        print(f"\n  [kills] periodos: {list(kills.keys())}")
        for period, data in list(kills.items())[:3]:
            print(f"    {period}: {json.dumps(data, ensure_ascii=False)[:200]}")

    # specials (Equipas)
    specials = odds.get("specials") or []
    print(f"\n  [specials] {len(specials)} grupo(s)")
    for group in specials:
        name = group.get("name", "")
        code = group.get("code", "")
        events = group.get("events") or []
        print(f"    Grupo: {name!r} code={code!r} -> {len(events)} eventos")
        for ev in events[:8]:
            bt = ev.get("bt", "")
            n = ev.get("name", "")[:50]
            contestants = ev.get("contestants", [])
            prices = [c.get("p") for c in contestants if c.get("p") is not None]
            print(f"      - {bt}: {n!r} -> {prices}")


def main():
    event_id = (sys.argv[1:] or [None])[0]
    if not event_id:
        event_id = get_one_event_id() or "1623745399"
    event_id = str(event_id).strip()
    print(f"Event ID: {event_id}")

    # 1) wstoken: login primeiro, senão guest
    wstoken, ulp = get_wstoken_with_login()
    if not wstoken:
        print("Tentando wstoken com cookies atuais (guest)...")
        wstoken, ulp = get_wstoken_guest()
    if not wstoken:
        print("Falha: não foi possível obter wstoken.")
        print("  Configure PINNACLE_LOGIN_TOKEN no .env (token do login no site) ou cookies PINNACLE_SIG/PINNACLE_APT.")
        sys.exit(1)
    print(f"  wstoken obtido (len={len(wstoken)})")

    # 2) WebSocket
    print("Conectando WebSocket e inscrevendo no evento...")
    odds = asyncio.run(fetch_full_game_ws(event_id, wstoken, ulp))
    if not odds:
        print("Falha: não recebemos FULL_ODDS.")
        sys.exit(1)

    # 3) Resumo + salvar JSON completo
    summarize_odds(odds)
    out_file = ROOT / "websocket_game_sample.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(odds, f, ensure_ascii=False, indent=2)
    print(f"\n  Jogo completo salvo em: {out_file}")


if __name__ == "__main__":
    main()
