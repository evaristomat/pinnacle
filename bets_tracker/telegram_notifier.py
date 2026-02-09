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

# Separador visual
SEP = "────────────────────────────────"


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
    """Formata EV como porcentagem com sinal."""
    return f"+{ev * 100:.1f}%"


def _format_odd(odd: float) -> str:
    """Formata odd decimal."""
    return f"{odd:.2f}"


def _format_method(metodo: str) -> str:
    """Formata nome do método."""
    if metodo == "probabilidade_empirica":
        return "Empírico"
    elif metodo in ("ml", "machinelearning"):
        return "ML"
    return metodo


def _format_side(side: str) -> str:
    """Formata side."""
    return side.upper()


def _format_market_label(market_type: str, side: str, line_value) -> str:
    """Formata label do mercado completo (ex: OVER KILLS 27.5)."""
    side_str = side.upper()
    line_str = f" {line_value}" if line_value is not None else ""

    mapping = {
        "total_kills": "KILLS",
        "total_kill_home": "KILLS HOME",
        "total_kill_away": "KILLS AWAY",
    }
    market_label = mapping.get(market_type, market_type.upper())
    return f"{side_str} {market_label}{line_str}"


def _format_date(date_str: str) -> str:
    """Formata data para exibição dd/mm às HH:MM."""
    if not date_str:
        return "?"
    try:
        dt_clean = date_str.replace("Z", "").split("+")[0]
        if "T" in dt_clean:
            dt = datetime.fromisoformat(dt_clean)
        else:
            dt = datetime.strptime(dt_clean[:19], "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%d/%m às %H:%M")
    except Exception:
        return date_str[:10]


def _calc_fair_odd(implied_prob: float = None, empirical_prob: float = None) -> Optional[float]:
    """Calcula fair odd a partir da probabilidade empírica."""
    prob = empirical_prob or implied_prob
    if prob and prob > 0:
        return 1.0 / prob
    return None


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

    # Envia uma mensagem por jogo para ficar mais limpo
    messages_sent = 0
    for mid, game in games.items():
        home = _escape_html(game["home"])
        away = _escape_html(game["away"])
        league = _escape_html(game["league"])
        date_str = _format_date(game["date"])

        lines = [
            f"🎯 <b>JOGO — {home} vs {away}</b>",
            f"📅 {date_str}",
            f"🏆 {league}",
            SEP,
        ]

        # Agrupa bets por mapa
        bets_by_map = {}
        for bet in game["bets"]:
            mapa = bet.get("mapa")
            if mapa not in bets_by_map:
                bets_by_map[mapa] = []
            bets_by_map[mapa].append(bet)

        for mapa in sorted(bets_by_map.keys(), key=lambda x: x if x is not None else 99):
            map_bets = bets_by_map[mapa]
            mapa_label = f"MAP {mapa}" if mapa else "MATCH"

            for bet in map_bets:
                method = _format_method(bet.get("metodo", ""))
                market_label = _format_market_label(
                    bet.get("market_type", ""),
                    bet.get("side", ""),
                    bet.get("line_value"),
                )
                odd = _format_odd(bet.get("odd_decimal", 0))
                ev = _format_ev(bet.get("expected_value", 0))

                # Calcula fair odd
                fair_odd = _calc_fair_odd(
                    empirical_prob=bet.get("empirical_prob"),
                )
                fair_str = f" → Fair: {fair_odd:.2f}" if fair_odd else ""

                # Historico
                hist_games = bet.get("historical_games")
                hist_str = f" ({hist_games} jogos)" if hist_games else ""

                lines.append("")
                lines.append(f"<b>{mapa_label}</b>")
                lines.append(f"🔬 Método: {method}{hist_str}")
                lines.append(f"✅ <b>{market_label}</b>")
                lines.append(f"💰 Odds: <b>{odd}</b>{fair_str}")
                lines.append(f"📊 EV: <b>{ev}</b>")

        text = "\n".join(lines).strip()
        if _send_message(text):
            messages_sent += 1

    # Mensagem de resumo se muitos jogos
    if len(games) > 1 and stats:
        summary = (
            f"📋 <b>RESUMO DA COLETA</b>\n"
            f"{SEP}\n"
            f"🎮 Jogos analisados: {stats.get('games_analyzed', 0)}\n"
            f"🎯 Bets encontradas: {stats.get('bets_found', 0)} "
            f"(🔬 {n_emp} Emp | 🤖 {n_ml} ML)\n"
            f"💾 Salvas: {stats.get('bets_saved', 0)}"
        )
        _send_message(summary)

    return messages_sent > 0


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
        f"📊 <b>RESULTADOS ATUALIZADOS ({n})</b>",
        SEP,
        f"✅ Wins: {len(wins)} | ❌ Losses: {len(losses)}"
        + (f" | ⚪ Void: {len(voids)}" if voids else ""),
        "",
    ]

    # Wins
    if wins:
        lines.append("✅ <b>WON</b>")
        lines.append("")
        for r in wins:
            bet = r["bet"]
            home = _escape_html(bet.get("home_team", "?"))
            away = _escape_html(bet.get("away_team", "?"))
            league = _escape_html(bet.get("league_name", "?"))
            method = _format_method(bet.get("metodo", ""))
            mapa = bet.get("mapa")
            mapa_str = f" — Map {mapa}" if mapa else ""

            market_label = _format_market_label(
                bet.get("market_type", ""),
                bet.get("side", ""),
                bet.get("line_value"),
            )
            odd = _format_odd(bet.get("odd_decimal", 0))
            profit = bet.get("odd_decimal", 0) - 1
            result_val = r.get("result_value")
            result_str = f" (Real: {result_val})" if result_val is not None else ""

            lines.append(f"🎯 {home} vs {away}{mapa_str}")
            lines.append(f"🏆 {league} | 🔬 {method}")
            lines.append(f"✅ {market_label} @ <b>{odd}</b>")
            lines.append(f"💰 <b>+{profit:.2f}u</b>{result_str}")
            lines.append("")

    # Losses
    if losses:
        lines.append("❌ <b>LOST</b>")
        lines.append("")
        for r in losses:
            bet = r["bet"]
            home = _escape_html(bet.get("home_team", "?"))
            away = _escape_html(bet.get("away_team", "?"))
            league = _escape_html(bet.get("league_name", "?"))
            method = _format_method(bet.get("metodo", ""))
            mapa = bet.get("mapa")
            mapa_str = f" — Map {mapa}" if mapa else ""

            market_label = _format_market_label(
                bet.get("market_type", ""),
                bet.get("side", ""),
                bet.get("line_value"),
            )
            odd = _format_odd(bet.get("odd_decimal", 0))
            result_val = r.get("result_value")
            result_str = f" (Real: {result_val})" if result_val is not None else ""

            lines.append(f"🎯 {home} vs {away}{mapa_str}")
            lines.append(f"🏆 {league} | 🔬 {method}")
            lines.append(f"❌ {market_label} @ <b>{odd}</b>")
            lines.append(f"💸 <b>-1.00u</b>{result_str}")
            lines.append("")

    # ROI summary
    if roi_stats and roi_stats.get("total_resolved", 0) > 0:
        roi = roi_stats
        total_r = roi["total_resolved"]
        w = roi.get("wins", 0)
        wr = roi.get("win_rate", 0)
        ret = roi.get("return_pct", 0)
        lucro = roi.get("lucro", 0)

        profit_emoji = "📈" if lucro >= 0 else "📉"
        profit_symbol = "+" if lucro >= 0 else ""
        ret_symbol = "+" if ret >= 0 else ""

        lines.append(SEP)
        lines.append(f"{profit_emoji} <b>ROI GERAL</b>")
        lines.append(f"📋 {total_r} resolvidas | {w} wins ({wr:.1f}%)")
        lines.append(f"💰 Return: <b>{ret_symbol}{ret:.1f}%</b> | Lucro: <b>{profit_symbol}{lucro:.2f}u</b>")

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
        "🤖 <b>Pinnacle Bot — Teste</b>\n\n"
        f"✅ Bot configurado e funcionando.\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    success = _send_message(text)
    if success:
        print("[TELEGRAM] Mensagem de teste enviada com sucesso!")
    return success


if __name__ == "__main__":
    send_test_message()
