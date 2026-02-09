"""
Notificações via Telegram para o sistema de apostas.

Envia alertas formatados quando:
- Novas value bets são encontradas
- Resultados de apostas são atualizados (won/lost)

Configuração via variáveis de ambiente:
    TELEGRAM_BOT_TOKEN  - Token do bot (@BotFather)
    TELEGRAM_CHAT_ID    - ID do chat/grupo/canal

Para desabilitar, basta não definir as variáveis.
"""
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime


# Configuração
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Controle de habilitação
ENABLED = bool(BOT_TOKEN and CHAT_ID)


def is_enabled() -> bool:
    """Retorna True se o Telegram está configurado."""
    return ENABLED


def _send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Envia mensagem via Telegram Bot API.

    Args:
        text: Texto da mensagem (HTML ou Markdown)
        parse_mode: 'HTML' ou 'MarkdownV2'

    Returns:
        True se enviou com sucesso
    """
    if not ENABLED:
        return False

    try:
        # Telegram limita mensagens a 4096 caracteres
        # Se maior, envia em partes
        chunks = _split_message(text, max_len=4000)

        for chunk in chunks:
            resp = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": chunk,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"   [TELEGRAM] Erro ao enviar: {resp.status_code} - {resp.text[:200]}")
                return False

        return True

    except Exception as e:
        print(f"   [TELEGRAM] Erro de conexao: {e}")
        return False


def _split_message(text: str, max_len: int = 4000) -> List[str]:
    """Divide mensagem longa em partes respeitando quebras de linha."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line

    if current:
        chunks.append(current)

    return chunks


def _escape_html(text: str) -> str:
    """Escapa caracteres especiais para HTML do Telegram."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_ev(ev: float) -> str:
    """Formata EV como porcentagem."""
    return f"{ev * 100:.1f}%"


def _format_odd(odd: float) -> str:
    """Formata odd decimal."""
    return f"{odd:.2f}"


def _format_method(metodo: str) -> str:
    """Formata nome do método."""
    if metodo == "probabilidade_empirica":
        return "Empirico"
    elif metodo in ("ml", "machinelearning"):
        return "ML"
    return metodo


def _format_side(side: str) -> str:
    """Formata side com emoji."""
    if side.lower() == "over":
        return "OVER"
    elif side.lower() == "under":
        return "UNDER"
    return side.upper()


def _format_market(market_type: str) -> str:
    """Formata tipo de mercado."""
    mapping = {
        "total_kills": "Total Kills",
        "total_kill_home": "Kills Home",
        "total_kill_away": "Kills Away",
    }
    return mapping.get(market_type, market_type)


def _format_date(date_str: str) -> str:
    """Formata data para exibição."""
    if not date_str:
        return "?"
    try:
        dt_clean = date_str.replace("Z", "").split("+")[0]
        if "T" in dt_clean:
            dt = datetime.fromisoformat(dt_clean)
        else:
            dt = datetime.strptime(dt_clean[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return date_str[:10]


# ============================================================================
# NOTIFICAÇÃO: NOVAS VALUE BETS
# ============================================================================

def notify_new_bets(bets: List[Dict], stats: Dict = None) -> bool:
    """
    Envia notificação de novas value bets encontradas.

    Args:
        bets: Lista de bets salvas (dicts com dados completos)
        stats: Estatísticas da coleta (opcional)

    Returns:
        True se enviou com sucesso
    """
    if not ENABLED or not bets:
        return False

    n = len(bets)
    n_emp = sum(1 for b in bets if b.get("metodo") == "probabilidade_empirica")
    n_ml = sum(1 for b in bets if b.get("metodo") in ("ml", "machinelearning"))

    # Header
    lines = [
        f"<b>NEW VALUE BETS ({n})</b>",
        f"Empirico: {n_emp} | ML: {n_ml}",
        "",
    ]

    # Agrupa por jogo (matchup_id)
    games = {}
    for bet in bets:
        mid = bet.get("matchup_id", 0)
        if mid not in games:
            games[mid] = {
                "home": bet.get("home_team", "?"),
                "away": bet.get("away_team", "?"),
                "league": bet.get("league_name", "?"),
                "date": bet.get("game_date", ""),
                "bets": [],
            }
        games[mid]["bets"].append(bet)

    for mid, game in games.items():
        home = _escape_html(game["home"])
        away = _escape_html(game["away"])
        league = _escape_html(game["league"])
        date_str = _format_date(game["date"])

        lines.append(f"<b>{home} vs {away}</b>")
        lines.append(f"{league} | {date_str}")

        for bet in game["bets"]:
            side = _format_side(bet.get("side", ""))
            line_val = bet.get("line_value")
            line_str = f" {line_val}" if line_val is not None else ""
            odd = _format_odd(bet.get("odd_decimal", 0))
            ev = _format_ev(bet.get("expected_value", 0))
            method = _format_method(bet.get("metodo", ""))
            market = _format_market(bet.get("market_type", ""))
            mapa = bet.get("mapa")
            mapa_str = f"M{mapa}" if mapa else ""

            lines.append(
                f"  {side}{line_str} @ <b>{odd}</b> | EV {ev} | {method} | {market} {mapa_str}"
            )

        lines.append("")

    # Footer com stats
    if stats:
        lines.append(
            f"Jogos: {stats.get('games_analyzed', 0)} | "
            f"Encontradas: {stats.get('bets_found', 0)} | "
            f"Salvas: {stats.get('bets_saved', 0)}"
        )

    text = "\n".join(lines).strip()
    return _send_message(text)


# ============================================================================
# NOTIFICAÇÃO: RESULTADOS ATUALIZADOS
# ============================================================================

def notify_results_updated(results: List[Dict], roi_stats: Dict = None) -> bool:
    """
    Envia notificação de resultados de apostas atualizados.

    Args:
        results: Lista de dicts com {bet, status, result_value}
        roi_stats: Estatísticas de ROI atualizadas (opcional)

    Returns:
        True se enviou com sucesso
    """
    if not ENABLED or not results:
        return False

    wins = [r for r in results if r["status"] == "won"]
    losses = [r for r in results if r["status"] == "lost"]
    voids = [r for r in results if r["status"] == "void"]

    n = len(results)

    # Header
    lines = [
        f"<b>RESULTS UPDATE ({n})</b>",
        f"Won: {len(wins)} | Lost: {len(losses)}" + (f" | Void: {len(voids)}" if voids else ""),
        "",
    ]

    # Wins
    if wins:
        lines.append("<b>WON</b>")
        for r in wins:
            bet = r["bet"]
            home = _escape_html(bet.get("home_team", "?"))
            away = _escape_html(bet.get("away_team", "?"))
            league = _escape_html(bet.get("league_name", "?"))
            side = _format_side(bet.get("side", ""))
            line_val = bet.get("line_value")
            line_str = f" {line_val}" if line_val is not None else ""
            odd = _format_odd(bet.get("odd_decimal", 0))
            result_val = r.get("result_value")
            result_str = f" (Real: {result_val})" if result_val is not None else ""
            profit = bet.get("odd_decimal", 0) - 1
            method = _format_method(bet.get("metodo", ""))
            mapa = bet.get("mapa")
            mapa_str = f" M{mapa}" if mapa else ""

            lines.append(f"  {home} vs {away} | {league}{mapa_str}")
            lines.append(
                f"  {side}{line_str} @ <b>{odd}</b> | +{profit:.2f}u | {method}{result_str}"
            )
        lines.append("")

    # Losses
    if losses:
        lines.append("<b>LOST</b>")
        for r in losses:
            bet = r["bet"]
            home = _escape_html(bet.get("home_team", "?"))
            away = _escape_html(bet.get("away_team", "?"))
            league = _escape_html(bet.get("league_name", "?"))
            side = _format_side(bet.get("side", ""))
            line_val = bet.get("line_value")
            line_str = f" {line_val}" if line_val is not None else ""
            odd = _format_odd(bet.get("odd_decimal", 0))
            result_val = r.get("result_value")
            result_str = f" (Real: {result_val})" if result_val is not None else ""
            method = _format_method(bet.get("metodo", ""))
            mapa = bet.get("mapa")
            mapa_str = f" M{mapa}" if mapa else ""

            lines.append(f"  {home} vs {away} | {league}{mapa_str}")
            lines.append(
                f"  {side}{line_str} @ <b>{odd}</b> | -1.00u | {method}{result_str}"
            )
        lines.append("")

    # ROI summary
    if roi_stats and roi_stats.get("total_resolved", 0) > 0:
        roi = roi_stats
        total_r = roi["total_resolved"]
        w = roi.get("wins", 0)
        wr = roi.get("win_rate", 0)
        ret = roi.get("return_pct", 0)
        lucro = roi.get("lucro", 0)

        profit_symbol = "+" if lucro >= 0 else ""
        ret_symbol = "+" if ret >= 0 else ""

        lines.append("<b>ROI GERAL</b>")
        lines.append(
            f"  {total_r} resolvidas | {w} wins ({wr:.1f}%) | "
            f"{ret_symbol}{ret:.1f}% | {profit_symbol}{lucro:.2f}u"
        )

    text = "\n".join(lines).strip()
    return _send_message(text)


# ============================================================================
# TESTE
# ============================================================================

def send_test_message() -> bool:
    """Envia mensagem de teste para verificar configuração."""
    if not ENABLED:
        print("[TELEGRAM] Nao configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID.")
        return False

    text = (
        "<b>Pinnacle Bot - Teste</b>\n\n"
        f"Bot configurado e funcionando.\n"
        f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    success = _send_message(text)
    if success:
        print("[TELEGRAM] Mensagem de teste enviada com sucesso!")
    return success


if __name__ == "__main__":
    send_test_message()
