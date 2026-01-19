from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


def _ensure_parent_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@dataclass
class SyncState:
    course_to_list: Dict[str, str]
    item_to_card: Dict[str, Dict[str, str]]
    managed_list_ids: Dict[str, bool]
    course_info_card: Dict[str, str]
    meta: Dict[str, Any]

    @classmethod
    def empty(cls) -> "SyncState":
        return cls(
            course_to_list={},
            item_to_card={},
            managed_list_ids={},
            course_info_card={},
            meta={},
        )

    @staticmethod
    def _migrate(raw: Dict[str, Any]) -> "SyncState":
        course_to_list = raw.get("course_to_list", {}) or {}
        managed_list_ids = raw.get("managed_list_ids", {}) or {}
        course_info_card = raw.get("course_info_card", {}) or {}
        meta = raw.get("meta", {}) or {}

        item_to_card = raw.get("item_to_card", {})
        if isinstance(item_to_card, dict) and item_to_card:
            # Ensure each entry has expected keys.
            for v in item_to_card.values():
                if not isinstance(v, dict):
                    continue
                v.setdefault("status", "active")  # active|done|manual
                v.setdefault("locked", False)
                v.setdefault("origin_list_id", "")
                v.setdefault("last_seen_list_id", "")
                v.setdefault("rendered_name", "")
                v.setdefault("rendered_desc", "")
                v.setdefault("rendered_due", "")
            return SyncState(
                course_to_list=course_to_list,
                item_to_card=item_to_card,
                managed_list_ids=managed_list_ids,
                course_info_card=course_info_card,
                meta=meta,
            )

        # Back-compat with the original single-file script schema:
        # - assignment_to_card: {"{course_id}:{assignment_id}": {"card_id": ..., "checksum": ...}}
        assignment_to_card = raw.get("assignment_to_card", {}) or {}
        migrated: Dict[str, Dict[str, str]] = {}
        for old_key, val in assignment_to_card.items():
            if not isinstance(val, dict):
                continue
            try:
                course_id_str, assignment_id_str = old_key.split(":", 1)
            except ValueError:
                continue
            new_key = f"assignment:{course_id_str}:{assignment_id_str}"
            migrated[new_key] = {
                "card_id": str(val.get("card_id", "")),
                "checksum": str(val.get("checksum", "")),
                "status": "active",
                "locked": False,
                "origin_list_id": "",
                "last_seen_list_id": "",
                "rendered_name": "",
                "rendered_desc": "",
                "rendered_due": "",
            }

        return SyncState(
            course_to_list=course_to_list,
            item_to_card=migrated,
            managed_list_ids=managed_list_ids,
            course_info_card=course_info_card,
            meta=meta,
        )

    @classmethod
    def load(cls, state_file: str) -> "SyncState":
        if os.path.exists(state_file):
            with open(state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return cls._migrate(raw)
        return cls.empty()

    def save(self, state_file: str) -> None:
        _ensure_parent_dir(state_file)
        tmp = state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "course_to_list": self.course_to_list,
                    "item_to_card": self.item_to_card,
                    "managed_list_ids": self.managed_list_ids,
                    "course_info_card": self.course_info_card,
                    "meta": self.meta,
                },
                f,
                indent=2,
                sort_keys=True,
            )
        os.replace(tmp, state_file)
