from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def load_env() -> None:
    env_file = os.getenv("ENV_FILE", ".env")
    override = os.getenv("DOTENV_OVERRIDE", "1").strip().lower() in {"1", "true", "yes", "y", "on"}
    load_dotenv(dotenv_path=Path(env_file), override=override)


@dataclass(frozen=True)
class Config:
    canvas_base_url: str
    canvas_token: str
    canvas_term_id: str
    canvas_token_created_at: str
    canvas_token_lifetime_days: int
    trello_key: str
    trello_token: str
    trello_board_id: str
    trello_board_url: str
    due_within_days: int
    poll_interval_minutes: int
    state_file: str
    user_agent: str = "canvas-trello-sync/0.1"

    @staticmethod
    def require(value: str, name: str) -> str:
        if not value:
            raise SystemExit(f"Missing required config: {name}")
        return value

    @classmethod
    def from_env(cls) -> Config:
        def int_env(name: str, default: int) -> int:
            raw = os.getenv(name)
            if raw is None:
                return default
            raw = raw.strip()
            if raw == "":
                return default
            try:
                return int(raw)
            except ValueError as e:
                raise SystemExit(f"Invalid integer for {name}: {raw!r}") from e

        canvas_base_url = os.getenv("CANVAS_BASE_URL", "").strip().rstrip("/")
        canvas_token = os.getenv("CANVAS_TOKEN", "").strip()
        canvas_term_id = os.getenv("CANVAS_TERM_ID", "").strip()
        canvas_token_created_at = os.getenv("CANVAS_TOKEN_CREATED_AT", "").strip()
        canvas_token_lifetime_days = int_env("CANVAS_TOKEN_LIFETIME_DAYS", 120)

        trello_key = os.getenv("TRELLO_KEY", "").strip()
        trello_token = os.getenv("TRELLO_TOKEN", "").strip()

        trello_board_id = os.getenv("TRELLO_BOARD_ID", "").strip()
        trello_board_url = os.getenv("TRELLO_BOARD_URL", "").strip()

        due_within_days = int_env("DUE_WITHIN_DAYS", 30)
        poll_interval_minutes = int_env("POLL_INTERVAL_MINUTES", 30)
        state_file = os.getenv("SYNC_STATE_FILE", "data/canvas_trello_state.json")

        cls.require(canvas_base_url, "CANVAS_BASE_URL")
        cls.require(canvas_token, "CANVAS_TOKEN")
        cls.require(trello_key, "TRELLO_KEY")
        cls.require(trello_token, "TRELLO_TOKEN")
        if not trello_board_id:
            cls.require(trello_board_url, "TRELLO_BOARD_ID or TRELLO_BOARD_URL")

        return cls(
            canvas_base_url=canvas_base_url,
            canvas_token=canvas_token,
            canvas_term_id=canvas_term_id,
            canvas_token_created_at=canvas_token_created_at,
            canvas_token_lifetime_days=canvas_token_lifetime_days,
            trello_key=trello_key,
            trello_token=trello_token,
            trello_board_id=trello_board_id,
            trello_board_url=trello_board_url,
            due_within_days=due_within_days,
            poll_interval_minutes=poll_interval_minutes,
            state_file=state_file,
        )
