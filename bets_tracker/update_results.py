"""
Atualiza resultados das apostas comparando com histórico
"""
import sqlite3
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

import pandas as pd

from bets_database import (
    get_pending_bets,
    get_placed_bets,
    update_bet_result,
    get_bet_stats
)
from result_matcher import ResultMatcher
from config import BETS_DB, USER_BETS_DB
from telegram_notifier import notify_results_updated, is_enabled as telegram_enabled


def _log_old_pending_bets(db_path: Path, days: int = 2) -> None:
    """
    Imprime no final as apostas ainda pendentes/feita cujo jogo aconteceu há mais de X dias
    (sem resultado encontrado no histórico).
    """
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # game_date pode ser 'YYYY-MM-DDTHH:MM:SS'; SQLite compara datetime em formato ISO
        cur.execute(
            """
            SELECT id, game_date, league_name, home_team, away_team, status
            FROM bets
            WHERE status IN ('pending', 'feita')
              AND datetime(REPLACE(REPLACE(game_date, 'T', ' '), 'Z', '')) < datetime('now', 'localtime', ?)
            ORDER BY game_date ASC
            """,
            (f"-{days} days",),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return
        print("\n" + "=" * 60)
        print(f"[LOG] Apostas com jogo há mais de {days} dias sem resultado encontrado: {len(rows)}")
        print("=" * 60)
        for r in rows:
            game_date_short = (r["game_date"] or "")[:10] if r["game_date"] else "?"
            print(f"   #{r['id']}  {game_date_short}  {r['league_name']}  {r['home_team']} vs {r['away_team']}  ({r['status']})")
        print("=" * 60)
    except Exception as e:
        print(f"\n[AVISO] Erro ao listar apostas antigas pendentes: {e}")


class ResultsUpdater:
    """Atualiza resultados das apostas."""
    
    def __init__(self, db_path=USER_BETS_DB):
        """Inicializa o atualizador."""
        self.matcher = ResultMatcher()
        self.db_path = db_path
        self.stats = {
            'pending_bets': 0,
            'matched': 0,
            'updated': 0,
            'not_found': 0,
            'errors': 0
        }
    
    def update_all_results(
        self,
        dry_run: bool = False,
        include_pending: bool = False,
        min_hours: Optional[float] = None,
        limit: Optional[int] = None,
        summary: bool = False,
    ) -> Dict:
        """
        Atualiza resultados de todas as apostas marcadas como 'feita'
        (usuário já apostou), cruzando com o histórico.
        
        Args:
            dry_run: Se True, apenas mostra o que seria atualizado
            
        Returns:
            Dicionário com estatísticas
        """
        if include_pending:
            print("[BUSCANDO] Buscando apostas pendentes + feitas (aguardando resultado)...")
            pending_bets = get_pending_bets(db_path=self.db_path) + get_placed_bets(db_path=self.db_path)
            # remove duplicatas por id (conservador)
            seen = set()
            deduped = []
            for b in pending_bets:
                bid = b.get("id")
                if bid in seen:
                    continue
                seen.add(bid)
                deduped.append(b)
            pending_bets = deduped
        else:
            print("[BUSCANDO] Buscando apostas feitas (aguardando resultado)...")
            pending_bets = get_placed_bets(db_path=self.db_path)
        
        if not pending_bets:
            print("   [OK] Nenhuma aposta aguardando resultado")
            _log_old_pending_bets(self.db_path, days=2)
            return self.stats

        # Filtra por idade mínima (opcional; se None, processa todas as pendentes)
        if min_hours is not None:
            now = pd.Timestamp(datetime.now())
            filtered = []
            skipped_recent = 0
            skipped_bad_date = 0
            for b in pending_bets:
                dt = pd.to_datetime(b.get("game_date"), errors="coerce")
                if pd.isna(dt):
                    skipped_bad_date += 1
                    continue
                age = now - dt
                if age >= pd.Timedelta(hours=float(min_hours)):
                    filtered.append(b)
                else:
                    skipped_recent += 1
            pending_bets = filtered
            print(f"   [FILTRO] min_hours={min_hours}: mantendo {len(pending_bets)}, pulando {skipped_recent} recentes e {skipped_bad_date} com data inválida")

        # Aplica limite (útil para testar)
        if limit is not None:
            pending_bets = pending_bets[: max(0, int(limit))]
        
        self.stats['pending_bets'] = len(pending_bets)
        print(f"   [OK] {len(pending_bets)} apostas encontradas\n")
        
        print("[COMPARANDO] Comparando com historico para encontrar resultados...\n")
        
        updated_preview: List[Tuple[int, str, float]] = []
        resolved_for_telegram: List[Dict] = []  # Para notificação Telegram

        for i, bet in enumerate(pending_bets, 1):
            bet_id = bet['id']
            matchup_id = bet['matchup_id']

            if not summary:
                print(f"[{i}/{len(pending_bets)}] Aposta #{bet_id}: {bet['home_team']} vs {bet['away_team']}")
                mapa_info = f" (Mapa {bet['mapa']})" if bet.get('mapa') else ""
                print(f"   Market: {bet['side']} {bet['line_value']} @ {bet['odd_decimal']}{mapa_info}")
            
            try:
                # Tenta fazer match
                game_result = self.matcher.match_game(bet)
                
                if not game_result:
                    if not summary:
                        print(f"   [AVISO] Jogo nao encontrado no historico")
                    self.stats['not_found'] += 1
                    continue
                
                confidence = game_result.get('confidence', 0)
                match_info = game_result.get('match_info', {})
                game_map = match_info.get('game')
                map_info = f" (Mapa histórico: {game_map})" if game_map is not None else ""
                if not summary:
                    print(f"   [OK] Match encontrado (confianca: {confidence:.1%}){map_info}")
                
                # Determina resultado
                status, result_value = self.matcher.determine_bet_result(bet, game_result)

                updated_preview.append((int(bet_id), str(status), float(result_value) if result_value is not None else None))
                if not summary:
                    print(f"   Resultado: {status.upper()} | Total kills: {result_value}")
                
                if not dry_run:
                    # Atualiza no banco
                    update_bet_result(bet_id, result_value, status, db_path=self.db_path)
                    if not summary:
                        print(f"   [SALVO] Atualizado no banco")
                    self.stats['updated'] += 1
                    
                    # Coleta para notificação Telegram
                    if status in ('won', 'lost'):
                        resolved_for_telegram.append({
                            'bet': bet,
                            'status': status,
                            'result_value': result_value,
                        })
                else:
                    if not summary:
                        print(f"   [DRY RUN] Seria atualizado: {status} com {result_value}")
                
                self.stats['matched'] += 1
                
            except Exception as e:
                if not summary:
                    print(f"   [ERRO] Erro ao processar: {e}")
                self.stats['errors'] += 1
                continue

            if not summary:
                print()

        if summary:
            # mostra uma amostra do que seria atualizado (sem spam)
            sample = updated_preview[:10]
            if sample:
                print("\n[AMOSTRA] primeiras 10 atualizações:")
                for bid, st, rv in sample:
                    print(f"  - bet_id={bid} -> {st} (result={rv})")

        # Notifica via Telegram os resultados atualizados
        if resolved_for_telegram and telegram_enabled():
            print(f"\n[TELEGRAM] Enviando notificacao de {len(resolved_for_telegram)} resultados...")
            # Busca ROI atualizado para incluir no resumo
            try:
                roi_stats = get_bet_stats(db_path=self.db_path).get('roi', {})
            except Exception:
                roi_stats = None
            success = notify_results_updated(resolved_for_telegram, roi_stats)
            if success:
                print(f"[TELEGRAM] Notificacao enviada!")
            else:
                print(f"[TELEGRAM] Falha ao enviar notificacao")

        _log_old_pending_bets(self.db_path, days=2)
        return self.stats
    
    def print_stats(self):
        """Imprime estatísticas da atualização."""
        print("=" * 60)
        print("[ESTATISTICAS] Estatisticas da Atualizacao")
        print("=" * 60)
        print(f"   Apostas pendentes: {self.stats['pending_bets']}")
        print(f"   Matches encontrados: {self.stats['matched']}")
        print(f"   Resultados atualizados: {self.stats['updated']}")
        print(f"   Não encontrados: {self.stats['not_found']}")
        print(f"   Erros: {self.stats['errors']}")
        print("=" * 60)


def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Atualiza resultados das apostas comparando com histórico"
    )
    parser.add_argument(
        '--db',
        choices=['auto', 'bets', 'user'],
        default='auto',
        help="Qual banco atualizar: auto (padrão), bets (bets.db), user (user_bets.db)"
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Apenas mostra o que seria atualizado, sem salvar'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Mostra apenas resumo + amostra (evita imprimir cada aposta)'
    )
    parser.add_argument(
        '--include-pending',
        action='store_true',
        help="Inclui apostas 'pending' na atualização (além de 'feita')"
    )
    parser.add_argument(
        '--min-hours',
        type=float,
        default=None,
        help="Só tenta atualizar apostas com game_date pelo menos X horas no passado (ex: 24)"
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help="Limita quantas apostas processar (útil para testar)",
    )
    
    args = parser.parse_args()
    
    # Verifica se banco existe (por padrão: USER_BETS_DB)
    if args.db == 'bets':
        db_path = BETS_DB
    elif args.db == 'user':
        db_path = USER_BETS_DB
    else:
        db_path = USER_BETS_DB if USER_BETS_DB.exists() else BETS_DB
    if not db_path.exists():
        print("[ERRO] Banco de apostas nao encontrado!")
        print("   Execute primeiro o app (para criar user_bets.db) ou rode o pipeline de coleta.")
        return
    
    # Atualiza resultados
    updater = ResultsUpdater(db_path=db_path)
    stats = updater.update_all_results(
        dry_run=args.dry_run,
        include_pending=args.include_pending,
        min_hours=args.min_hours,
        limit=args.limit,
        summary=args.summary,
    )
    
    updater.print_stats()
    
    # Mostra estatísticas atualizadas do banco
    if not args.dry_run:
        print("\n[ESTATISTICAS] Estatisticas Atualizadas do Banco:")
        db_stats = get_bet_stats(db_path=db_path)
        print(f"   Total de apostas: {db_stats['total']}")
        print(f"   Por status: {db_stats['by_status']}")
        
        if db_stats['roi']['total_resolved'] > 0:
            roi = db_stats['roi']
            print(f"\n[ROI] ROI:")
            print(f"   Resolvidas: {roi['total_resolved']}")
            print(f"   Vitorias: {roi['wins']} ({roi['win_rate']:.1f}%)")
            print(f"   Derrotas: {roi['losses']}")
            print(f"   Odd media (vitorias): {roi['avg_win_odd']:.2f}")
            print(f"   Return: {roi.get('return_pct', 0):+.2f}% (lucro/total u apostadas)")
            print(f"   Lucro: {roi.get('lucro', 0):+.2f} u")


if __name__ == "__main__":
    main()
