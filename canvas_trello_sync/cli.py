from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

from .canvas import CanvasClient
from .config import Config, load_env
from .logging_utils import instrument_session
from .state import SyncState
from .syncer import sync_once
from .trello import TrelloClient


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sync Canvas assignments + events to Trello.")
    p.add_argument("--once", action="store_true", help="Run a single sync then exit.")
    p.add_argument("--validate", action="store_true", help="Validate Trello auth/board access then exit.")
    p.add_argument(
        "--list-courses",
        action="store_true",
        help="List active Canvas courses (id/name/term/date fields) then exit.",
    )
    p.add_argument(
        "--wipe-board",
        action="store_true",
        help="Archive only content created by this tool before syncing.",
    )
    p.add_argument(
        "--wipe-board-confirm",
        default="",
        help="Safety check: must exactly match the resolved board id when using --wipe-board.",
    )
    p.add_argument("--log-file", default="logs/canvas_trello_sync.log", help="Write logs to this file.")
    p.add_argument("--log-http", action="store_true", help="Log HTTP request/response metadata (secrets redacted).")
    p.add_argument("--log-texts", action="store_true", help="Log description samples for debugging.")
    p.add_argument("--log-max-text", type=int, default=500, help="Max chars of text snippets when using --log-texts.")
    p.add_argument(
        "--interval-minutes",
        type=int,
        default=None,
        help="Polling interval (default: POLL_INTERVAL_MINUTES or 30). Ignored with --once.",
    )
    p.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR).")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(args.log_level).upper(), logging.INFO))

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_file = str(args.log_file or "").strip()
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)

    # Avoid leaking secrets in URLs via urllib3 debug logs (Trello auth uses query params).
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    load_env()
    cfg = Config.from_env()

    trello = TrelloClient(cfg.trello_key, cfg.trello_token)
    board_id = cfg.trello_board_id or trello.get_board_id_from_url(cfg.trello_board_url)
    if args.log_http:
        logging.getLogger("http").setLevel(logging.DEBUG)
        instrument_session(
            trello.session,
            name="trello",
            logger=logging.getLogger("http"),
            redact_query_keys={"key", "token"},
            log_bodies=True,
            max_body_chars=800,
        )
    if args.validate:
        me = trello.validate_auth()
        trello.get_board_lists(board_id)
        logging.info("Trello OK: user=%s board_id=%s", me.get("username") or me.get("fullName") or "unknown", board_id)
        return

    canvas = CanvasClient(
        cfg.canvas_base_url,
        cfg.canvas_token,
        cfg.user_agent,
        log_texts=bool(args.log_texts),
        max_text_chars=int(args.log_max_text),
    )
    if args.log_http:
        instrument_session(
            canvas.session,
            name="canvas",
            logger=logging.getLogger("http"),
            redact_query_keys=set(),
            log_bodies=True,
            max_body_chars=800,
        )
    if args.list_courses:
        courses = canvas.get_active_courses()
        term_ids = [
            int(c["enrollment_term_id"])
            for c in courses
            if c.get("enrollment_term_id") is not None and str(c.get("enrollment_term_id")).isdigit()
        ]
        suggested = max(term_ids) if term_ids else None
        logging.info("Suggested current term id (max enrollment_term_id): %s", suggested)
        for c in courses:
            logging.info(
                "course id=%s term=%s name=%s start=%s end=%s",
                c.get("id"),
                c.get("enrollment_term_id"),
                c.get("name") or c.get("course_code"),
                c.get("start_at"),
                c.get("end_at"),
            )
        return

    interval_minutes = args.interval_minutes if args.interval_minutes is not None else cfg.poll_interval_minutes
    interval_seconds = max(60, int(interval_minutes * 60))

    def run_one() -> None:
        logging.info("Starting sync run: board_id=%s state_file=%s", board_id, cfg.state_file)
        if args.wipe_board:
            if args.wipe_board_confirm != board_id:
                raise SystemExit(
                    "Refusing to wipe board: pass `--wipe-board-confirm` equal to the resolved board id "
                    f"({board_id})."
                )
            state = SyncState.load(cfg.state_file)
            managed_cards = [v for v in state.item_to_card.values() if isinstance(v, dict) and v.get("card_id")]
            for course_id, card_id in state.course_info_card.items():
                lid = state.course_to_list.get(str(course_id), "")
                managed_cards.append(
                    {"card_id": str(card_id), "status": "active", "locked": False, "origin_list_id": str(lid)}
                )
            token_list_id = str(state.meta.get("token_list_id") or "")
            token_card_id = str(state.meta.get("token_card_id") or "")
            last_sync_card_id = str(state.meta.get("last_sync_card_id") or "")
            if token_card_id:
                managed_cards.append(
                    {"card_id": token_card_id, "status": "active", "locked": False, "origin_list_id": token_list_id}
                )
            if last_sync_card_id:
                managed_cards.append(
                    {
                        "card_id": last_sync_card_id,
                        "status": "active",
                        "locked": False,
                        "origin_list_id": token_list_id,
                    }
                )

            protected = state.meta.get("protected_list_ids", [])
            protected_list_ids = protected if isinstance(protected, list) else []
            managed_list_ids = [
                lid
                for (lid, is_managed) in state.managed_list_ids.items()
                if is_managed and lid not in protected_list_ids
            ]

            logging.warning(
                "Wiping managed Trello content on board %s: cards=%s lists=%s",
                board_id,
                len(managed_cards),
                len(managed_list_ids),
            )
            result = trello.wipe_managed(
                board_id,
                managed_cards=managed_cards,
                managed_list_ids=managed_list_ids,
                protected_list_ids=protected_list_ids,
            )

            archived_lists = set(result.get("archived_lists", []))
            if archived_lists:
                state.course_to_list = {cid: lid for (cid, lid) in state.course_to_list.items() if lid not in archived_lists}
                for lid in archived_lists:
                    state.managed_list_ids.pop(lid, None)

            archived_cards = set(result.get("archived_cards", []))
            state.item_to_card = {
                k: v for (k, v) in state.item_to_card.items() if str(v.get("card_id") or "") not in archived_cards
            }
            state.course_info_card = {
                k: v for (k, v) in state.course_info_card.items() if str(v or "") not in archived_cards
            }
            # Keep token card/list IDs so the next sync re-opens + updates the same card instead of creating a new one.
            state.save(cfg.state_file)

        state = SyncState.load(cfg.state_file)
        logging.info(
            "Loaded state: courses=%s items=%s managed_lists=%s",
            len(state.course_to_list),
            len(state.item_to_card),
            len(state.managed_list_ids),
        )
        state, summary = sync_once(
            canvas=canvas,
            trello=trello,
            board_id=board_id,
            due_within_days=cfg.due_within_days,
            canvas_term_id=cfg.canvas_term_id,
            canvas_token_created_at=cfg.canvas_token_created_at,
            canvas_token_lifetime_days=cfg.canvas_token_lifetime_days,
            state=state,
            log_texts=bool(args.log_texts),
        )
        state.save(cfg.state_file)
        logging.info(
            "Sync complete: lists_created=%s cards_created=%s cards_updated=%s state=%s",
            summary.lists_created,
            summary.cards_created,
            summary.cards_updated,
            cfg.state_file,
        )

    if args.once:
        run_one()
        return

    while True:
        started = datetime.utcnow()
        try:
            run_one()
        except SystemExit:
            raise
        except Exception:
            logging.exception("Sync failed; retrying after %s seconds", interval_seconds)

        elapsed = (datetime.utcnow() - started).total_seconds()
        sleep_for = max(1, interval_seconds - int(elapsed))
        time.sleep(sleep_for)
