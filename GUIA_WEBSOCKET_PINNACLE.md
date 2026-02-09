# Guia: WebSocket da Pinnacle (Mercados Especiais)

## Contexto

A API REST da Pinnacle que usamos atualmente retorna apenas os mercados principais (moneyline, totals/kills). Os mercados de **Equipas** (dragões, torres, barões, head-to-head) são entregues exclusivamente via **WebSocket**.

---

## Arquitetura do Fluxo

```
1. Autenticação  ──>  2. Obter wstoken  ──>  3. Conectar WS  ──>  4. SUBSCRIBE  ──>  5. Receber FULL_ODDS
```

### Passo 1 — Autenticação (obter sessão)

**Endpoint:** `POST https://sports.pinnacle.bet.br/member-auth/v2/auth-token`

**Query params:**
- `locale=pt_BR`
- `withCredentials=true`

**Body (JSON):**
```json
{
  "token": "<token_de_login_base64>",
  "locale": "pt",
  "oddsFormat": "EU",
  "sport": "esports/games/league-of-legends"
}
```

**Resposta:**
```json
{"success": true, "message": "AUTHENTICATED"}
```

> **Nota:** Este passo requer credenciais de conta Pinnacle. A resposta seta cookies de sessão que serão usados no próximo passo.

---

### Passo 2 — Obter token WebSocket

**Endpoint:** `GET https://sports.pinnacle.bet.br/member-auth/v2/wstoken`

**Query params:**
- `locale=pt_BR`
- `withCredentials=true`

**Headers:** Deve incluir os cookies de sessão do passo 1.

**Resposta:**
```json
{"token": "AAAAAATis5kAAAGcPxfk1Busi5QDFWsagpVW0tZGHj6tzDKX1zOnVxVAwdvV5Gks"}
```

---

### Passo 3 — Conectar ao WebSocket

**URL:**
```
wss://sports.pinnacle.bet.br/sports-websocket/ws?token=<WSTOKEN>&ulp=<ULP_BASE64>&view=euro
```

| Parâmetro | Descrição |
|-----------|-----------|
| `token`   | O token obtido no Passo 2 |
| `ulp`     | Token de sessão/perfil do usuário (URL-encoded Base64) |
| `view`    | Formato de odds: `euro` (decimal) |

**Headers obrigatórios:**
```
Upgrade: websocket
Origin: https://sports.pinnacle.bet.br
Sec-WebSocket-Version: 13
```

**Ao conectar, o servidor envia uma mensagem de confirmação:**
```json
{
  "ssn": 1,
  "time": 1770584157186,
  "type": "CONNECTED",
  "destination": "ALL"
}
```

---

### Passo 4 — Inscrever-se no evento (SUBSCRIBE)

Para receber os mercados de um jogo específico, envie a seguinte mensagem:

```json
{
  "type": "SUBSCRIBE",
  "destination": "EVENT_DETAILS_EURO_ODDS",
  "body": {
    "dpLk3": "E_MA3",
    "eventId": "1623745399",
    "oddsType": 1,
    "version": 0,
    "locale": "pt_BR"
  }
}
```

| Campo       | Descrição |
|-------------|-----------|
| `type`      | Sempre `"SUBSCRIBE"` |
| `destination` | Sempre `"EVENT_DETAILS_EURO_ODDS"` para odds decimais |
| `eventId`   | ID do evento na Pinnacle (o mesmo usado na API REST) |
| `dpLk3`     | Parâmetro de exibição, sempre `"E_MA3"` para esports |
| `oddsType`  | `1` = odds decimais (formato europeu) |
| `version`   | `0` para receber snapshot completo; > 0 para deltas |
| `locale`    | Idioma: `"pt_BR"` |

---

### Passo 5 — Receber FULL_ODDS

A resposta é uma mensagem JSON do tipo `FULL_ODDS`:

```json
{
  "ssn": 2,
  "time": 1770584157200,
  "type": "FULL_ODDS",
  "destination": "EVENT_DETAILS_EURO_ODDS",
  "odds": {
    "eventId": "1623745399",
    "info": { ... },
    "normal": { ... },
    "kills": { ... },
    "specials": [ ... ],
    "version": 12345,
    "specialVersion": 678
  }
}
```

**Chaves principais dentro de `odds`:**

| Chave           | Conteúdo |
|-----------------|----------|
| `normal`        | Mercados principais (moneyline, totals) — já temos via REST |
| `kills`         | Total kills por mapa — já temos via REST |
| `specials`      | **Mercados de Equipas** (dragões, torres, barões) — **SÓ via WS** |
| `alternateLines`| Linhas alternativas para totals |
| `setMarkets`    | Mercados de sets/mapas (handicap de mapas) |
| `matchMarkets`  | Mercados de match (série completa) |
| `version`       | Versão das odds (para solicitar deltas) |
| `specialVersion`| Versão dos specials |

---

## Estrutura dos `specials` (Equipas)

```json
{
  "specials": [
    {
      "name": "Equipas:",
      "code": "teams",
      "events": [
        {
          "name": "(Mapa 1) Total de dragões elementais mortos",
          "bt": "OVER_UNDER",
          "contestants": [
            {"n": "Mais de 4.5", "h": 4.5, "p": 1.555, "code": "over"},
            {"n": "Menos de 4.5", "h": 4.5, "p": 2.320, "code": "under"}
          ]
        },
        {
          "name": "(Mapa 1) Total de barões mortos",
          "bt": "OVER_UNDER",
          "contestants": [
            {"n": "Mais de 1.5", "h": 1.5, "p": 1.869, "code": "over"},
            {"n": "Menos de 1.5", "h": 1.5, "p": 1.869, "code": "under"}
          ]
        },
        {
          "name": "(Map 1) Total turrets destroyed",
          "bt": "OVER_UNDER",
          "contestants": [
            {"n": "Mais de 12.5", "h": 12.5, "p": 2.380, "code": "over"},
            {"n": "Menos de 12.5", "h": 12.5, "p": 1.529, "code": "under"}
          ]
        },
        {
          "name": "(Mapa 1) Cloud9 vs FlyQuest - Dragões Elementais",
          "bt": "MULTI_WAY_HEAD_TO_HEAD",
          "contestants": [
            {"n": "Cloud9", "p": 1.917, "code": "team1"},
            {"n": "FlyQuest", "p": 1.826, "code": "team2"}
          ]
        }
      ]
    }
  ]
}
```

### Tipos de mercados em `specials`

| `bt` (bet type) | Descrição | Exemplo |
|------------------|-----------|---------|
| `OVER_UNDER`     | Total over/under | Total dragões > 4.5 |
| `MULTI_WAY_HEAD_TO_HEAD` | Qual time faz mais | Cloud9 vs FlyQuest - Dragões |

### Campos de cada `contestant`

| Campo  | Descrição |
|--------|-----------|
| `n`    | Nome exibido ("Mais de 4.5", "Cloud9") |
| `h`    | Handicap/linha (apenas para OVER_UNDER) |
| `p`    | Preço (odd decimal) |
| `code` | Identificador: `over`, `under`, `team1`, `team2` |

### Mercados OVER_UNDER encontrados (exemplo Cloud9 vs FlyQuest)

| Mercado | Mapa | Linha | Over | Under |
|---------|------|-------|------|-------|
| Total de dragões elementais mortos | 1 | 4.5 | 1.555 | 2.320 |
| Total de dragões elementais mortos | 2 | 4.5 | 1.574 | 2.280 |
| Total turrets destroyed | 1 | 12.5 | 2.380 | 1.529 |
| Total turrets destroyed | 2 | 12.5 | 2.380 | 1.529 |
| Total de barões mortos | 1 | 1.5 | 1.869 | 1.869 |
| Total de barões mortos | 2 | 1.5 | 1.862 | 1.877 |

### Mercados HEAD_TO_HEAD encontrados (25 total)

Exemplos:
- Dragões Elementais (Qual time mata mais?)
- Torres (Qual time destrói mais?)
- Barões (Qual time mata mais?)
- Primeiro Dragão
- Primeira Torre
- Primeiro Barão
- Primeiro Inibidor
- Abates (Qual time tem mais kills?)

Cada um existe por mapa (Mapa 1, Mapa 2, etc.).

---

## Exemplo de Código Python

### Dependências

```bash
pip install websockets aiohttp
```

### Implementação completa

```python
import asyncio
import json
import aiohttp
import websockets

# ── Configuração ──
BASE_URL = "https://sports.pinnacle.bet.br"
WS_URL = "wss://sports.pinnacle.bet.br/sports-websocket/ws"

# Credenciais (usar variáveis de ambiente em produção!)
LOGIN_TOKEN = "SEU_TOKEN_BASE64_AQUI"  # token gerado no login do site


async def get_session_and_wstoken():
    """Etapas 1 e 2: autenticar e obter wstoken."""
    async with aiohttp.ClientSession() as session:
        # Passo 1: Autenticação
        auth_url = f"{BASE_URL}/member-auth/v2/auth-token"
        auth_body = {
            "token": LOGIN_TOKEN,
            "locale": "pt",
            "oddsFormat": "EU",
            "sport": "esports/games/league-of-legends",
        }
        async with session.post(
            auth_url,
            json=auth_body,
            params={"locale": "pt_BR", "withCredentials": "true"},
        ) as resp:
            auth_data = await resp.json()
            if not auth_data.get("success"):
                raise RuntimeError(f"Autenticação falhou: {auth_data}")
            print(f"✓ Autenticado: {auth_data['message']}")

        # Passo 2: Obter wstoken
        wstoken_url = f"{BASE_URL}/member-auth/v2/wstoken"
        async with session.get(
            wstoken_url,
            params={"locale": "pt_BR", "withCredentials": "true"},
        ) as resp:
            token_data = await resp.json()
            wstoken = token_data["token"]
            print(f"✓ WS Token obtido: {wstoken[:20]}...")

        # Extrair ULP dos cookies da sessão (se necessário)
        ulp = ""  # Pode ser extraído dos cookies ou ignorado
        for cookie in session.cookie_jar:
            if cookie.key == "ulp":
                ulp = cookie.value
                break

        return wstoken, ulp


async def fetch_specials(event_id: str, wstoken: str, ulp: str = ""):
    """Etapas 3-5: conectar WS, inscrever e receber specials."""
    ws_full_url = f"{WS_URL}?token={wstoken}&view=euro"
    if ulp:
        ws_full_url += f"&ulp={ulp}"

    async with websockets.connect(
        ws_full_url,
        origin="https://sports.pinnacle.bet.br",
        additional_headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        },
    ) as ws:
        # Receber CONNECTED
        connected_msg = await ws.recv()
        connected = json.loads(connected_msg)
        assert connected["type"] == "CONNECTED", f"Esperado CONNECTED, recebeu: {connected['type']}"
        print(f"✓ WebSocket conectado (ssn={connected['ssn']})")

        # Enviar SUBSCRIBE
        subscribe_msg = {
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
        await ws.send(json.dumps(subscribe_msg))
        print(f"✓ SUBSCRIBE enviado para evento {event_id}")

        # Receber FULL_ODDS
        odds_msg = await ws.recv()
        full_odds = json.loads(odds_msg)

        if full_odds.get("type") != "FULL_ODDS":
            print(f"✗ Tipo inesperado: {full_odds.get('type')}")
            return None

        print(f"✓ FULL_ODDS recebido")
        return full_odds["odds"]


def parse_specials(odds: dict) -> list[dict]:
    """Extrair mercados de specials (dragões, torres, barões)."""
    results = []
    specials = odds.get("specials", [])

    for group in specials:
        group_name = group.get("name", "")
        group_code = group.get("code", "")

        for event in group.get("events", []):
            name = event.get("name", "")
            bt = event.get("bt", "")
            contestants = event.get("contestants", [])

            # Extrair mapa do nome: "(Mapa 1) ..." ou "(Map 2) ..."
            map_num = None
            import re
            map_match = re.search(r'\((?:Mapa|Map)\s+(\d+)\)', name)
            if map_match:
                map_num = int(map_match.group(1))

            if bt == "OVER_UNDER":
                over = next((c for c in contestants if c.get("code") == "over"), None)
                under = next((c for c in contestants if c.get("code") == "under"), None)
                line = None
                for c in contestants:
                    if c.get("h") is not None:
                        line = c["h"]
                        break

                # Identificar tipo de mercado
                market_type = "unknown"
                name_lower = name.lower()
                if "dragõ" in name_lower or "dragon" in name_lower or "dragões" in name_lower:
                    market_type = "total_dragons"
                elif "turret" in name_lower or "torre" in name_lower:
                    market_type = "total_towers"
                elif "barõ" in name_lower or "baron" in name_lower or "barões" in name_lower:
                    market_type = "total_barons"

                results.append({
                    "group": group_code,
                    "market_type": market_type,
                    "bet_type": "OVER_UNDER",
                    "name": name,
                    "map": map_num,
                    "line": line,
                    "over_price": over["p"] if over else None,
                    "under_price": under["p"] if under else None,
                })

            elif bt == "MULTI_WAY_HEAD_TO_HEAD":
                team1 = next((c for c in contestants if c.get("code") == "team1"), None)
                team2 = next((c for c in contestants if c.get("code") == "team2"), None)

                results.append({
                    "group": group_code,
                    "market_type": "head_to_head",
                    "bet_type": "HEAD_TO_HEAD",
                    "name": name,
                    "map": map_num,
                    "team1_name": team1["n"] if team1 else None,
                    "team1_price": team1["p"] if team1 else None,
                    "team2_name": team2["n"] if team2 else None,
                    "team2_price": team2["p"] if team2 else None,
                })

    return results


# ── Uso ──

async def main():
    # Obter tokens
    wstoken, ulp = await get_session_and_wstoken()

    # Buscar odds do evento (ex: Cloud9 vs FlyQuest)
    event_id = "1623745399"
    odds = await fetch_specials(event_id, wstoken, ulp)

    if odds:
        specials = parse_specials(odds)
        print(f"\n{'='*60}")
        print(f"Encontrados {len(specials)} mercados especiais:\n")

        for s in specials:
            if s["bet_type"] == "OVER_UNDER":
                print(f"  [{s['market_type']}] Mapa {s['map']}: "
                      f"Over {s['line']} @ {s['over_price']} | "
                      f"Under {s['line']} @ {s['under_price']}")
            else:
                print(f"  [H2H] Mapa {s['map']}: {s['name']}")
                print(f"    {s['team1_name']} @ {s['team1_price']} | "
                      f"{s['team2_name']} @ {s['team2_price']}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Como obter o `eventId`

O `eventId` é o mesmo ID que já usamos na API REST da Pinnacle. Você pode obtê-lo de:

1. **`pinnacle_data.db`** — tabela `matchups`, coluna `event_id`
2. **API REST** — endpoint de matchups que `main.py` já consulta
3. **URL do site** — ao acessar um jogo, o ID aparece na URL:
   ```
   https://sports.pinnacle.bet.br/.../1623745399
                                       ^^^^^^^^^^
   ```

---

## Notas de Implementação

### Autenticação

- A WebSocket da Pinnacle **requer autenticação**.
- É necessário ter uma conta na Pinnacle e fazer login via API.
- O token de login (`LOGIN_TOKEN`) é gerado pelo frontend da Pinnacle ao fazer login no site.
- Os cookies de sessão do auth devem ser mantidos para obter o wstoken.

### Considerações sobre o Token

- O `wstoken` tem validade limitada (provavelmente 5-10 minutos).
- A cada nova sessão, é necessário repetir o fluxo de autenticação.
- O parâmetro `ulp` nos query params do WS é o perfil do usuário em Base64.

### Performance e Rate Limiting

- Após o SUBSCRIBE, o WS mantém a conexão e envia **atualizações em tempo real** (deltas).
- Para buscar vários jogos, pode-se enviar múltiplos SUBSCRIBEs na mesma conexão.
- Cada SUBSCRIBE retorna um FULL_ODDS com todos os mercados daquele evento.

### Mapeamento de Nomes de Mercado

Os nomes dos mercados vêm em **português** (quando `locale=pt_BR`) ou **inglês** (dependendo do mercado):

| Padrão no nome | market_type |
|----------------|-------------|
| `dragões elementais` / `dragon` | `total_dragons` |
| `turrets destroyed` / `torres` | `total_towers` |
| `barões mortos` / `baron` | `total_barons` |

> **Atenção:** O idioma pode variar mesmo dentro da mesma resposta (ex: "Total turrets destroyed" em inglês junto com "Total de dragões" em português).

### Integração com o Sistema Atual

Para integrar com o pipeline existente:

1. **`main.py`** — Adicionar chamada ao WebSocket após a coleta REST, para cada evento.
2. **`database.py`** — As colunas `total_dragons` e `total_towers` **já existem** no schema. Seria necessário adicionar `total_barons`.
3. **`odds_analyzer.py`** — Adicionar análise de valor para os novos mercados.
4. **`collect_bets.py`** — Incluir os novos mercados na coleta de apostas.

### Fluxo de Integração Sugerido

```
run_all.py
  └── main.py
       ├── API REST → matchups + odds (total_kills)     [JÁ EXISTE]
       └── WebSocket → specials (dragons/towers/barons)  [A IMPLEMENTAR]
            └── database.py → salvar em pinnacle_data.db
```

---

## Resumo

| Item | Valor |
|------|-------|
| **Protocolo** | WebSocket (wss://) |
| **Requer autenticação** | Sim (conta Pinnacle) |
| **Endpoint WS** | `wss://sports.pinnacle.bet.br/sports-websocket/ws` |
| **Mensagem de inscrição** | `SUBSCRIBE` → `EVENT_DETAILS_EURO_ODDS` |
| **Mensagem de resposta** | `FULL_ODDS` → campo `specials` |
| **Mercados disponíveis** | Dragões, Torres, Barões (Over/Under + H2H) |
| **Bibliotecas Python** | `websockets`, `aiohttp` |
