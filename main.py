"""
Sistema Integrado de Coleta e Processamento de Dados Pinnacle
Busca dados da API, processa, salva no banco e atualiza JSON único
"""
import requests
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Union

# Importa módulos locais
from database import init_database, save_games_and_markets, get_database_stats, get_all_games

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================

LEAGUE_IDS = [
    218181, 228009, 241160, 233800, 223983, 209234, 211515, 199353,
    240984, 204030, 211390, 284474, 272187
]

# Arquivos JSON únicos (sempre os mesmos, atualizados a cada execução)
MARKETS_JSON_FILE = "pinnacle_markets.json"
MATCHUPS_JSON_FILE = "pinnacle_matchups.json"
EXPORT_JSON_FILE = "league_of_legends_data.json"

# ============================================================================
# MÓDULO 1: API FETCHER
# ============================================================================

# Configuração da Nova API
USE_NEW_API = True  # Tenta usar nova API primeiro
NEW_API_COOKIES = {
    "_sig": "Acy1NbVUwTlRnd01ESmhPRGxsT1RrMVlROmJvTkRZcnJSaFNKQ2hCVkJvekpFVWdaN2g6LTgyNjU4NTk2Mjo3NjkwMzc0NDk6Mi4xMS4wOl9iUUJ5bTN5TXM%3D",
    "_apt": "_bQBym3yMs",
    "closeAnnTime": "0",
    "pctag": "3cbdf5af-49c7-4376-971a-66212d5cf965",
    "C_U_I": "",
    "BIAB_LANGUAGE": "PT_BR",
    "BIAB_TZ": "240"
}

def get_headers() -> Dict:
    """Retorna os headers padrão para as requisições"""
    return {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "origin": "https://www.pinnacle.com",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": "https://www.pinnacle.com/",
        "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not;A=Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "api-key": "CkM2XNyMuFwgNyF7eDEyRTClOIkN",
        "device-uuid": "a95be66e-ea9e-4f8e-a52b-3dd4b559878f"
    }

def fetch_markets(league_id: int, headers: Dict) -> Optional[Dict]:
    """Faz requisição para obter markets de uma liga"""
    try:
        url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/markets/straight"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return {
            "league_id": league_id,
            "url": url,
            "status_code": response.status_code,
            "timestamp": datetime.now().isoformat(),
            "data": response.json()
        }
    except Exception:
        return None

def fetch_matchups(league_id: int, headers: Dict) -> Optional[Dict]:
    """Faz requisição para obter matchups de uma liga"""
    try:
        url = f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{league_id}/matchups"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return {
            "league_id": league_id,
            "url": url,
            "status_code": response.status_code,
            "timestamp": datetime.now().isoformat(),
            "data": response.json()
        }
    except Exception:
        return None

def get_new_api_headers() -> Dict:
    """Retorna headers para a nova API"""
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pt-BR,pt;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json; charset=utf-8",
        "priority": "u=1, i",
        "referer": "https://sports.pinnacle.bet.br/pt/standard/esports/games/league-of-legends",
        "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0",
        "x-app-data": "pctag=3cbdf5af-49c7-4376-971a-66212d5cf965;directusToken=TwEdnphtyxsfMpXoJkCkWaPsL2KJJ3lo;dpVXz=ZDfaFZUP9"
    }

def fetch_new_api_data() -> Optional[Dict]:
    """
    Busca todos os dados da nova API em uma única chamada.
    Retorna dados completos de todas as ligas de League of Legends.
    """
    try:
        timestamp = int(time.time() * 1000)
        url = (
            f"https://sports.pinnacle.bet.br/sports-service/sv/euro/odds/matchups"
            f"?sportId=12"
            f"&oddsType=1"
            f"&version=0"
            f"&timeStamp={timestamp}"
            f"&language=pt"
            f"&eSportCode=league-of-legends"
            f"&periodNum=0%2C1%2C2%2C3%2C11%2C12%2C13"
            f"&locale=pt_BR"
            f"&_={timestamp}"
            f"&withCredentials=true"
        )
        
        headers = get_new_api_headers()
        cookies = NEW_API_COOKIES
        
        response = requests.get(url, headers=headers, cookies=cookies, timeout=30)
        response.raise_for_status()
        
        return {
            "url": url,
            "status_code": response.status_code,
            "timestamp": datetime.now().isoformat(),
            "data": response.json()
        }
    except Exception as e:
        print(f"  [AVISO] Erro ao buscar nova API: {e}")
        return None

def fetch_all_data() -> Tuple[Union[List, None], Union[List, Dict, None]]:
    """
    Busca todos os dados da API.
    Tenta usar a nova API primeiro, com fallback para a API antiga.
    Retorna: (markets_data, matchups_data) ou (None, new_api_response_dict)
    """
    # Tenta usar nova API primeiro
    if USE_NEW_API:
        print("Tentando usar nova API...")
        new_api_response = fetch_new_api_data()
        
        if new_api_response and new_api_response.get("data"):
            print("  [OK] Nova API funcionou!")
            # A nova API retorna dados em formato diferente
            # Retornamos None para markets_data e o dict da nova API para matchups_data
            # O processamento será feito em extract_game_data_from_new_api
            return None, new_api_response
    
    # Fallback para API antiga
    print("Usando API antiga (fallback)...")
    headers = get_headers()
    all_markets_results = []
    all_matchups_results = []
    
    print(f"Buscando dados de {len(LEAGUE_IDS)} ligas...")
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submete todas as tarefas
        markets_futures = {
            executor.submit(fetch_markets, league_id, headers): league_id 
            for league_id in LEAGUE_IDS
        }
        matchups_futures = {
            executor.submit(fetch_matchups, league_id, headers): league_id 
            for league_id in LEAGUE_IDS
        }
        
        # Processa resultados de markets
        print("  Buscando markets...")
        for future in as_completed(markets_futures):
            league_id = markets_futures[future]
            result = future.result()
            if result:
                all_markets_results.append(result)
                print(f"    [OK] Markets da liga {league_id}")
            else:
                print(f"    [ERRO] Falha ao obter markets da liga {league_id}")
        
        # Processa resultados de matchups
        print("  Buscando matchups...")
        for future in as_completed(matchups_futures):
            league_id = matchups_futures[future]
            result = future.result()
            if result:
                all_matchups_results.append(result)
                print(f"    [OK] Matchups da liga {league_id}")
            else:
                print(f"    [ERRO] Falha ao obter matchups da liga {league_id}")
    
    # Combina todos os dados
    all_markets_data = []
    for result in all_markets_results:
        if result and result.get("data"):
            all_markets_data.extend(result["data"])
    
    all_matchups_data = []
    for result in all_matchups_results:
        if result and result.get("data"):
            all_matchups_data.extend(result["data"])
    
    return all_markets_data, all_matchups_data

def save_api_data_to_json(markets_data: List, matchups_data: List):
    """Salva dados da API em arquivos JSON únicos (atualizados, não criados novos)"""
    # Estrutura para markets
    markets_json = {
        "request_info": {
            "timestamp": datetime.now().isoformat(),
            "total_leagues": len(LEAGUE_IDS),
            "total_markets": len(markets_data),
            "league_ids": LEAGUE_IDS
        },
        "response_data": markets_data
    }
    
    # Estrutura para matchups
    matchups_json = {
        "request_info": {
            "timestamp": datetime.now().isoformat(),
            "total_leagues": len(LEAGUE_IDS),
            "total_matchups": len(matchups_data),
            "league_ids": LEAGUE_IDS
        },
        "response_data": matchups_data
    }
    
    # Salva/atualiza arquivos únicos
    with open(MARKETS_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(markets_json, f, indent=2, ensure_ascii=False)
    
    with open(MATCHUPS_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(matchups_json, f, indent=2, ensure_ascii=False)
    
    print(f"  Dados da API salvos em: {MARKETS_JSON_FILE} e {MATCHUPS_JSON_FILE}")

# ============================================================================
# MÓDULO 2: DATA PROCESSOR
# ============================================================================

def convert_american_to_decimal(american_odds: int) -> float:
    """Converte odds americanas para decimais"""
    if american_odds > 0:
        return round((american_odds / 100) + 1, 2)
    else:
        return round((100 / abs(american_odds)) + 1, 2)

def clean_league_name(league_name: str) -> str:
    """Remove o prefixo 'League of Legends - ' do nome da liga"""
    if not league_name:
        return league_name
    
    prefix = "League of Legends - "
    if league_name.startswith(prefix):
        return league_name[len(prefix):].strip()
    
    return league_name.strip()

def parse_spread(spread_str: str) -> float:
    """Converte spread de string para float, mantendo o sinal original"""
    try:
        # float() já trata corretamente sinais + e -, mantendo o sinal original
        return float(spread_str)
    except:
        return 0.0

def extract_game_data_from_new_api(new_api_response: Dict) -> List[Dict]:
    """
    Extrai e organiza dados dos jogos da nova API.
    Converte para o formato compatível com o banco de dados existente.
    """
    games = []
    
    if not new_api_response or not new_api_response.get("data"):
        return games
    
    data = new_api_response["data"]
    leagues = data.get("leagues", [])
    
    # Mapeia eventos filhos (kills) para eventos pais
    events_by_id = {}
    parent_events = []
    
    for league in leagues:
        league_name_raw = league.get("name", "")
        league_name = clean_league_name(league_name_raw)
        league_id = league.get("id", 0)
        events = league.get("events", [])
        
        for event in events:
            event_id = event.get("id", 0)
            parent_id = event.get("parentId", 0)
            
            events_by_id[event_id] = {
                "event": event,
                "league_name": league_name,
                "league_id": league_id
            }
            
            if parent_id == 0:
                parent_events.append(event_id)
    
    # Processa apenas eventos principais (não kills)
    for event_id in parent_events:
        event_info = events_by_id.get(event_id)
        if not event_info:
            continue
        
        event = event_info["event"]
        league_name = event_info["league_name"]
        
        # Extrai participantes
        participants = event.get("participants", [])
        if len(participants) < 2:
            continue
        
        home_team = None
        away_team = None
        
        for p in participants:
            if p.get("type") == "HOME":
                home_team = p.get("name", "")
            elif p.get("type") == "AWAY":
                away_team = p.get("name", "")
        
        if not home_team or not away_team:
            continue
        
        # Converte timestamp
        event_time = event.get("time", 0)
        start_time = datetime.fromtimestamp(event_time / 1000).isoformat() if event_time else ""
        
        # Organiza markets
        game_markets = {
            "moneyline": {},
            "handicap_map": {},
            "total_map": {},
            "total_kill_home": {},
            "total_kill_away": {},
            "handicap_kills": {},
            "total_kills": {}
        }
        
        # Processa períodos do evento principal
        periods = event.get("periods", {})
        for period_str, period_data in periods.items():
            try:
                period = int(period_str)
            except:
                continue
            
            if not isinstance(period_data, dict):
                continue
            
            # Moneyline
            money_line = period_data.get("moneyLine", {})
            if isinstance(money_line, dict) and not money_line.get("unavailable", False):
                home_price = money_line.get("homePrice", "")
                away_price = money_line.get("awayPrice", "")
                if home_price and away_price:
                    try:
                        home_decimal = float(home_price)
                        away_decimal = float(away_price)
                        # Converte para americano se necessário (para compatibilidade)
                        home_american = int((home_decimal - 1) * 100) if home_decimal >= 2.0 else int(-100 / (home_decimal - 1))
                        away_american = int((away_decimal - 1) * 100) if away_decimal >= 2.0 else int(-100 / (away_decimal - 1))
                        
                        game_markets["moneyline"][period] = {
                            "home": {
                                "american": home_american,
                                "decimal": round(home_decimal, 2)
                            },
                            "away": {
                                "american": away_american,
                                "decimal": round(away_decimal, 2)
                            }
                        }
                    except:
                        pass
            
            # Handicap (Spread)
            handicap_list = period_data.get("handicap", [])
            for handicap in handicap_list:
                if not isinstance(handicap, dict) or handicap.get("unavailable", False):
                    continue
                
                home_spread_str = handicap.get("homeSpread", "")
                away_spread_str = handicap.get("awaySpread", "")
                home_odds = handicap.get("homeOdds", "")
                away_odds = handicap.get("awayOdds", "")
                is_alt = handicap.get("isAlt", False)
                
                if home_spread_str and home_odds:
                    try:
                        home_spread = parse_spread(home_spread_str)
                        away_spread = parse_spread(away_spread_str)
                        home_decimal = float(home_odds)
                        away_decimal = float(away_odds)
                        home_american = int((home_decimal - 1) * 100) if home_decimal >= 2.0 else int(-100 / (home_decimal - 1))
                        away_american = int((away_decimal - 1) * 100) if away_decimal >= 2.0 else int(-100 / (away_decimal - 1))
                        
                        spread_key = str(home_spread)
                        
                        if period not in game_markets["handicap_map"]:
                            game_markets["handicap_map"][period] = {}
                        
                        game_markets["handicap_map"][period][spread_key] = {
                            "home": {
                                "spread": home_spread,
                                "american": home_american,
                                "decimal": round(home_decimal, 2)
                            },
                            "away": {
                                "spread": away_spread,
                                "american": away_american,
                                "decimal": round(away_decimal, 2)
                            },
                            "is_alternate": is_alt
                        }
                    except:
                        pass
            
            # Over/Under (Total)
            over_under_list = period_data.get("overUnder", [])
            for ou in over_under_list:
                if not isinstance(ou, dict) or ou.get("unavailable", False):
                    continue
                
                points = ou.get("points", "")
                over_odds = ou.get("overOdds", "")
                under_odds = ou.get("underOdds", "")
                is_alt = ou.get("isAlt", False)
                
                if points and over_odds and under_odds:
                    try:
                        total_line = float(points)
                        over_decimal = float(over_odds)
                        under_decimal = float(under_odds)
                        over_american = int((over_decimal - 1) * 100) if over_decimal >= 2.0 else int(-100 / (over_decimal - 1))
                        under_american = int((under_decimal - 1) * 100) if under_decimal >= 2.0 else int(-100 / (under_decimal - 1))
                        
                        if period not in game_markets["total_map"]:
                            game_markets["total_map"][period] = {}
                        
                        game_markets["total_map"][period][str(total_line)] = {
                            "line": total_line,
                            "over": {
                                "american": over_american,
                                "decimal": round(over_decimal, 2)
                            },
                            "under": {
                                "american": under_american,
                                "decimal": round(under_decimal, 2)
                            },
                            "is_alternate": is_alt
                        }
                    except:
                        pass
        
        # Processa eventos filhos (kills) se existirem
        for child_event_id, child_info in events_by_id.items():
            child_event = child_info["event"]
            if child_event.get("parentId") == event_id:
                # É um evento de kills
                child_participants = child_event.get("participants", [])
                is_kills = any("Mortes" in p.get("name", "") or "Kills" in p.get("name", "") for p in child_participants)
                
                if is_kills:
                    child_periods = child_event.get("periods", {})
                    for period_str, period_data in child_periods.items():
                        try:
                            period = int(period_str)
                        except:
                            continue
                        
                        if not isinstance(period_data, dict):
                            continue
                        
                        # Handicap Kills
                        handicap_list = period_data.get("handicap", [])
                        for handicap in handicap_list:
                            if not isinstance(handicap, dict) or handicap.get("unavailable", False):
                                continue
                            
                            home_spread_str = handicap.get("homeSpread", "")
                            away_spread_str = handicap.get("awaySpread", "")
                            home_odds = handicap.get("homeOdds", "")
                            away_odds = handicap.get("awayOdds", "")
                            is_alt = handicap.get("isAlt", False)
                            
                            if home_spread_str and home_odds:
                                try:
                                    home_spread = parse_spread(home_spread_str)
                                    away_spread = parse_spread(away_spread_str) if away_spread_str else -home_spread
                                    home_decimal = float(home_odds)
                                    away_decimal = float(away_odds)
                                    
                                    spread_key = str(home_spread)
                                    
                                    if period not in game_markets["handicap_kills"]:
                                        game_markets["handicap_kills"][period] = {}
                                    
                                    game_markets["handicap_kills"][period][spread_key] = {
                                        "home": {
                                            "spread": home_spread,
                                            "american": int((home_decimal - 1) * 100) if home_decimal >= 2.0 else int(-100 / (home_decimal - 1)),
                                            "decimal": round(home_decimal, 2)
                                        },
                                        "away": {
                                            "spread": away_spread,
                                            "american": int((away_decimal - 1) * 100) if away_decimal >= 2.0 else int(-100 / (away_decimal - 1)),
                                            "decimal": round(away_decimal, 2)
                                        },
                                        "is_alternate": is_alt
                                    }
                                except:
                                    pass
                        
                        # Total Kills
                        over_under_list = period_data.get("overUnder", [])
                        for ou in over_under_list:
                            if not isinstance(ou, dict) or ou.get("unavailable", False):
                                continue
                            
                            points = ou.get("points", "")
                            over_odds = ou.get("overOdds", "")
                            under_odds = ou.get("underOdds", "")
                            is_alt = ou.get("isAlt", False)
                            
                            if points and over_odds and under_odds:
                                try:
                                    total_line = float(points)
                                    over_decimal = float(over_odds)
                                    under_decimal = float(under_odds)
                                    
                                    if period not in game_markets["total_kills"]:
                                        game_markets["total_kills"][period] = {}
                                    
                                    game_markets["total_kills"][period][str(total_line)] = {
                                        "line": total_line,
                                        "over": {
                                            "american": int((over_decimal - 1) * 100) if over_decimal >= 2.0 else int(-100 / (over_decimal - 1)),
                                            "decimal": round(over_decimal, 2)
                                        },
                                        "under": {
                                            "american": int((under_decimal - 1) * 100) if under_decimal >= 2.0 else int(-100 / (under_decimal - 1)),
                                            "decimal": round(under_decimal, 2)
                                        },
                                        "is_alternate": is_alt
                                    }
                                except:
                                    pass
                        
                        # Moneyline Kills (se houver)
                        money_line = period_data.get("moneyLine", {})
                        if isinstance(money_line, dict) and not money_line.get("unavailable", False):
                            # Pode ser usado para identificar qual time tem mais kills
                            pass
        
        # Cria objeto do jogo
        game = {
            "matchup_id": event_id,
            "league": league_name,
            "home_team": home_team,
            "away_team": away_team,
            "start_time": start_time,
            "status": "scheduled",  # A nova API não parece ter status explícito
            "markets": game_markets
        }
        
        games.append(game)
    
    return games

def extract_game_data(matchups_data: List, markets_data: List) -> List[Dict]:
    """Extrai e organiza dados dos jogos"""
    games = []
    
    # Cria dicionário de markets por matchupId
    markets_by_matchup = {}
    for market in markets_data:
        matchup_id = market.get("matchupId")
        if matchup_id:
            if matchup_id not in markets_by_matchup:
                markets_by_matchup[matchup_id] = []
            markets_by_matchup[matchup_id].append(market)
    
    # Mapeia matchups especiais para parent (para markets de kills)
    special_matchup_to_parent = {}
    for matchup in matchups_data:
        matchup_id = matchup.get("id")
        parent = matchup.get("parent")
        if parent and matchup_id:
            parent_id = parent.get("id")
            if parent_id:
                special_matchup_to_parent[matchup_id] = parent_id
    
    # Processa cada matchup
    for matchup in matchups_data:
        if matchup.get("type") != "matchup" or matchup.get("units", "") != "Regular":
            continue
        
        participants = matchup.get("participants", [])
        if len(participants) < 2:
            continue
        
        home_team = participants[0].get("name", "")
        away_team = participants[1].get("name", "")
        matchup_id = matchup.get("id")
        start_time = matchup.get("startTime", "")
        league_name_raw = matchup.get("league", {}).get("name", "")
        league_name = clean_league_name(league_name_raw)
        
        # Busca markets para este matchup
        markets = markets_by_matchup.get(matchup_id, [])
        
        # Adiciona markets de matchups especiais vinculados
        for special_matchup_id, parent_id in special_matchup_to_parent.items():
            if parent_id == matchup_id:
                special_markets = markets_by_matchup.get(special_matchup_id, [])
                markets.extend(special_markets)
        
        # Organiza markets
        game_markets = {
            "moneyline": {},
            "handicap_map": {},
            "total_map": {},
            "total_kill_home": {},
            "total_kill_away": {},
            "handicap_kills": {},
            "total_kills": {}
        }
        
        for market in markets:
            market_type = market.get("type")
            market_key = market.get("key", "")
            period = market.get("period", 0)
            is_alternate = market.get("isAlternate", False)
            is_kills_market = market_key.startswith("s;1;")
            
            if market_type == "moneyline":
                prices = market.get("prices", [])
                home_price = None
                away_price = None
                
                for price in prices:
                    designation = price.get("designation")
                    price_value = price.get("price")
                    if designation == "home":
                        home_price = price_value
                    elif designation == "away":
                        away_price = price_value
                
                if home_price is not None and away_price is not None:
                    game_markets["moneyline"][period] = {
                        "home": {
                            "american": home_price,
                            "decimal": convert_american_to_decimal(home_price)
                        },
                        "away": {
                            "american": away_price,
                            "decimal": convert_american_to_decimal(away_price)
                        }
                    }
            
            elif market_type == "spread":
                prices = market.get("prices", [])
                home_spread = None
                home_price = None
                away_spread = None
                away_price = None
                
                for price in prices:
                    designation = price.get("designation")
                    points = price.get("points")
                    price_value = price.get("price")
                    if designation == "home":
                        home_spread = points
                        home_price = price_value
                    elif designation == "away":
                        away_spread = points
                        away_price = price_value
                
                if home_spread is not None and home_price is not None:
                    spread_key = home_spread
                    
                    if is_kills_market and market_key.startswith("s;1;s;"):
                        if period not in game_markets["handicap_kills"]:
                            game_markets["handicap_kills"][period] = {}
                        
                        game_markets["handicap_kills"][period][spread_key] = {
                            "home": {
                                "spread": home_spread,
                                "american": home_price,
                                "decimal": convert_american_to_decimal(home_price)
                            },
                            "away": {
                                "spread": away_spread,
                                "american": away_price,
                                "decimal": convert_american_to_decimal(away_price)
                            },
                            "is_alternate": is_alternate
                        }
                    else:
                        if period not in game_markets["handicap_map"]:
                            game_markets["handicap_map"][period] = {}
                        
                        game_markets["handicap_map"][period][spread_key] = {
                            "home": {
                                "spread": home_spread,
                                "american": home_price,
                                "decimal": convert_american_to_decimal(home_price)
                            },
                            "away": {
                                "spread": away_spread,
                                "american": away_price,
                                "decimal": convert_american_to_decimal(away_price)
                            },
                            "is_alternate": is_alternate
                        }
            
            elif market_type == "total":
                prices = market.get("prices", [])
                total_line = None
                over_price = None
                under_price = None
                
                for price in prices:
                    designation = price.get("designation")
                    points = price.get("points")
                    price_value = price.get("price")
                    if designation == "over":
                        total_line = points
                        over_price = price_value
                    elif designation == "under":
                        if total_line is None:
                            total_line = points
                        under_price = price_value
                
                if total_line is not None and over_price is not None and under_price is not None:
                    if is_kills_market and market_key.startswith("s;1;ou;"):
                        if period not in game_markets["total_kills"]:
                            game_markets["total_kills"][period] = {}
                        
                        game_markets["total_kills"][period][total_line] = {
                            "line": total_line,
                            "over": {
                                "american": over_price,
                                "decimal": convert_american_to_decimal(over_price)
                            },
                            "under": {
                                "american": under_price,
                                "decimal": convert_american_to_decimal(under_price)
                            },
                            "is_alternate": is_alternate
                        }
                    else:
                        if period not in game_markets["total_map"]:
                            game_markets["total_map"][period] = {}
                        
                        game_markets["total_map"][period][total_line] = {
                            "line": total_line,
                            "over": {
                                "american": over_price,
                                "decimal": convert_american_to_decimal(over_price)
                            },
                            "under": {
                                "american": under_price,
                                "decimal": convert_american_to_decimal(under_price)
                            },
                            "is_alternate": is_alternate
                        }
            
            elif market_type == "team_total":
                if is_kills_market and market_key.startswith("s;1;tt;"):
                    prices = market.get("prices", [])
                    team_side = market.get("side", "")
                    total_line = None
                    over_price = None
                    under_price = None
                    
                    for price in prices:
                        designation = price.get("designation")
                        points = price.get("points")
                        price_value = price.get("price")
                        if designation == "over":
                            total_line = points
                            over_price = price_value
                        elif designation == "under":
                            if total_line is None:
                                total_line = points
                            under_price = price_value
                    
                    if total_line is not None and over_price is not None and under_price is not None and team_side:
                        if team_side == "home":
                            if period not in game_markets["total_kill_home"]:
                                game_markets["total_kill_home"][period] = {}
                            
                            game_markets["total_kill_home"][period][total_line] = {
                                "line": total_line,
                                "over": {
                                    "american": over_price,
                                    "decimal": convert_american_to_decimal(over_price)
                                },
                                "under": {
                                    "american": under_price,
                                    "decimal": convert_american_to_decimal(under_price)
                                },
                                "is_alternate": is_alternate
                            }
                        elif team_side == "away":
                            if period not in game_markets["total_kill_away"]:
                                game_markets["total_kill_away"][period] = {}
                            
                            game_markets["total_kill_away"][period][total_line] = {
                                "line": total_line,
                                "over": {
                                    "american": over_price,
                                    "decimal": convert_american_to_decimal(over_price)
                                },
                                "under": {
                                    "american": under_price,
                                    "decimal": convert_american_to_decimal(under_price)
                                },
                                "is_alternate": is_alternate
                            }
        
        # Cria objeto do jogo
        game = {
            "matchup_id": matchup_id,
            "league": league_name,
            "home_team": home_team,
            "away_team": away_team,
            "start_time": start_time,
            "status": matchup.get("status", ""),
            "markets": game_markets
        }
        
        games.append(game)
    
    return games

# ============================================================================
# MÓDULO 3: DATABASE MANAGER
# ============================================================================

def process_and_save_to_database(games: List[Dict]) -> Dict[str, int]:
    """Processa jogos e salva no banco de dados"""
    print("\nProcessando e salvando no banco de dados...")
    
    # Inicializa banco
    init_database()
    
    # Salva jogos e markets
    stats = save_games_and_markets(games)
    
    return stats

# ============================================================================
# MÓDULO 4: JSON EXPORTER
# ============================================================================

def export_database_to_json():
    """Exporta todos os dados do banco para JSON único (atualizado)"""
    print("\nExportando banco de dados para JSON...")
    
    # Busca todos os jogos
    games = get_all_games()
    stats = get_database_stats()
    
    # Cria estrutura final
    extracted_data = {
        "extraction_info": {
            "timestamp": datetime.now().isoformat(),
            "source": "database",
            "total_games": len(games),
            "database_stats": stats
        },
        "jogos": games
    }
    
    # Salva/atualiza arquivo único
    with open(EXPORT_JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)
    
    print(f"  Dados exportados para: {EXPORT_JSON_FILE}")

# ============================================================================
# MÓDULO 5: MAIN ORCHESTRATOR
# ============================================================================

def main():
    """Função principal que orquestra todo o processo"""
    # Configura encoding para Windows
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
    
    print("="*60)
    print("SISTEMA INTEGRADO PINNACLE - League of Legends")
    print("="*60)
    
    try:
        # ETAPA 1: Buscar dados da API
        print("\n[ETAPA 1] Buscando dados da API...")
        markets_data, matchups_data = fetch_all_data()
        
        # Verifica se usou nova API ou antiga
        using_new_api = markets_data is None and isinstance(matchups_data, dict)
        
        if using_new_api:
            new_api_response = matchups_data
            print(f"  ✓ Nova API: {len(new_api_response.get('data', {}).get('leagues', []))} ligas encontradas")
            
            # Conta eventos
            total_events = 0
            for league in new_api_response.get('data', {}).get('leagues', []):
                total_events += len(league.get('events', []))
            print(f"  ✓ {total_events} eventos encontrados")
        else:
            print(f"  ✓ {len(markets_data)} markets encontrados")
            print(f"  ✓ {len(matchups_data)} matchups encontrados")
        
        # ETAPA 2: Salvar dados da API em JSON único
        print("\n[ETAPA 2] Salvando dados da API...")
        if using_new_api:
            # Salva resposta da nova API
            with open(MATCHUPS_JSON_FILE, 'w', encoding='utf-8') as f:
                json.dump({
                    "request_info": {
                        "timestamp": datetime.now().isoformat(),
                        "api_version": "new",
                        "source": "sports.pinnacle.bet.br"
                    },
                    "response_data": new_api_response
                }, f, indent=2, ensure_ascii=False)
            print(f"  Dados da nova API salvos em: {MATCHUPS_JSON_FILE}")
        else:
            save_api_data_to_json(markets_data, matchups_data)
        
        # ETAPA 3: Processar e extrair dados dos jogos
        print("\n[ETAPA 3] Processando dados dos jogos...")
        if using_new_api:
            games = extract_game_data_from_new_api(new_api_response)
        else:
            games = extract_game_data(matchups_data, markets_data)
        print(f"  ✓ {len(games)} jogos extraídos")
        
        # ETAPA 4: Salvar no banco de dados
        print("\n[ETAPA 4] Salvando no banco de dados...")
        stats = process_and_save_to_database(games)
        print(f"  ✓ Novos jogos: {stats['new_games']}")
        print(f"  ✓ Jogos atualizados: {stats['updated_games']}")
        print(f"  ✓ Novos markets: {stats['new_markets']}")
        print(f"  ✓ Markets existentes: {stats['existing_markets']}")
        if 'new_teams' in stats:
            print(f"  ✓ Novos times: {stats['new_teams']}")
            print(f"  ✓ Times atualizados: {stats['updated_teams']}")
        
        # ETAPA 5: Exportar banco para JSON único
        print("\n[ETAPA 5] Exportando banco para JSON...")
        export_database_to_json()
        
        # ETAPA 6: Estatísticas finais
        print("\n[ETAPA 6] Estatísticas finais...")
        db_stats = get_database_stats()
        print(f"  ✓ Total de jogos no banco: {db_stats['total_games']}")
        print(f"  ✓ Total de markets no banco: {db_stats['total_markets']}")
        print(f"  ✓ Jogos com markets: {db_stats['games_with_markets']}")
        print(f"  ✓ Total de times: {db_stats['total_teams']}")
        print(f"  ✓ Total de ligas: {db_stats['total_leagues']}")
        
        print("\n" + "="*60)
        print("PROCESSO CONCLUÍDO COM SUCESSO!")
        print("="*60)
        print(f"\nArquivos atualizados:")
        print(f"  - {MARKETS_JSON_FILE}")
        print(f"  - {MATCHUPS_JSON_FILE}")
        print(f"  - {EXPORT_JSON_FILE}")
        print(f"  - pinnacle_data.db")
        print("="*60)
        
    except Exception as e:
        print(f"\n[ERRO] Falha no processo: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
