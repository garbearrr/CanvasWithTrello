from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from dateutil import parser as dtparser
import html
import re
import unicodedata


def iso_utc(dt_str: Optional[str]) -> Optional[str]:
    if not dt_str:
        return None
    dt = dtparser.isoparse(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def within_window(dt_str: Optional[str], start: datetime, end: datetime) -> bool:
    if not dt_str:
        return False
    dt = dtparser.isoparse(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return start <= dt <= end


def checksum_payload(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def html_to_text(raw_html: Optional[str]) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?s)<br\s*/?>", "\n", text)
    text = re.sub(r"(?s)</p\s*>", "\n", text)
    text = re.sub(r"(?s)<.*?>", " ", text)
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00A0", " ").replace("\u200B", "")
    # Some Canvas descriptions (copy/paste) come through with control characters where
    # letters should be. We aggressively map the common ones back to their intended letters.
    text = text.replace("\r\n", "\n")
    text = text.replace("\t", "t").replace("\f", "f").replace("\v", "d").replace("\r", "r")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    # Heuristic fixups for Canvas descriptions that contain broken URL schemes (often due to embedded tabs/newlines).
    text = re.sub(r"\bh\s*ps://", "https://", text, flags=re.IGNORECASE)
    text = re.sub(r"\bh\s*ps%3a", "https%3A", text, flags=re.IGNORECASE)
    text = re.sub(r"\bh\s*p://", "http://", text, flags=re.IGNORECASE)
    text = re.sub(r"\bh\s*p%3a", "http%3A", text, flags=re.IGNORECASE)
    return text

@dataclass(frozen=True)
class CanvasItem:
    item_type: str  # "assignment" | "event"
    course_id: int
    item_id: int
    title: str
    due_iso: Optional[str]
    url: str
    checksum: str
    details: Dict[str, Any]

    @property
    def key(self) -> str:
        return f"{self.item_type}:{self.course_id}:{self.item_id}"


class CanvasClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        user_agent: str,
        *,
        log_texts: bool = False,
        max_text_chars: int = 500,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.log_texts = log_texts
        self.max_text_chars = max_text_chars
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def _get_paginated(self, url: str, params: Optional[Dict[str, Any]] = None) -> List[Any]:
        out: List[Any] = []
        next_url: Optional[str] = url
        next_params = params or {}

        while next_url:
            r = self.session.get(next_url, params=next_params, timeout=30)
            r.raise_for_status()
            out.extend(r.json())

            link = r.headers.get("Link", "")
            next_link = None
            if link:
                parts = [p.strip() for p in link.split(",")]
                for p in parts:
                    if 'rel="next"' in p:
                        start = p.find("<") + 1
                        end = p.find(">")
                        if start > 0 and end > start:
                            next_link = p[start:end]
                            break

            next_url = next_link
            next_params = {}

        return out

    def get_active_courses(self, *, enrollment_term_id: Optional[int] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/v1/courses"
        params: Dict[str, Any] = {"enrollment_state": "active", "per_page": 100}
        if enrollment_term_id is not None:
            params["enrollment_term_id"] = enrollment_term_id
        return self._get_paginated(url, params=params)

    def get_assignments(self, course_id: int) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/v1/courses/{course_id}/assignments"
        params: Dict[str, Any] = {
            "per_page": 100,
            "include[]": ["submission"],
        }
        return self._get_paginated(url, params=params)

    def get_course_teachers(self, course_id: int) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/v1/courses/{course_id}/users"
        params = {"enrollment_type[]": "teacher", "per_page": 100}
        return self._get_paginated(url, params=params)

    def get_course(self, course_id: int) -> Dict[str, Any]:
        url = f"{self.base_url}/api/v1/courses/{course_id}"
        params = {"include[]": ["term"]}
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_calendar_events(self, course_id: int, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/api/v1/calendar_events"
        params = {
            "context_codes[]": f"course_{course_id}",
            "type": "event",
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "per_page": 100,
        }
        return self._get_paginated(url, params=params)

    def upcoming_items(self, course_id: int, within_days: int) -> List[CanvasItem]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=within_days)

        items: List[CanvasItem] = []

        for a in self.get_assignments(course_id):
            due_at = a.get("due_at")
            if not within_window(due_at, now, end):
                continue

            submission = a.get("submission") or {}
            submission_state = str(submission.get("workflow_state") or "").strip().lower()
            submitted_at = submission.get("submitted_at")
            graded_at = submission.get("graded_at")
            is_submitted = bool(submitted_at) or bool(graded_at) or submission_state in {"submitted", "graded"}

            payload = {
                "name": a.get("name"),
                "due_at": a.get("due_at"),
                "html_url": a.get("html_url"),
                "points_possible": a.get("points_possible"),
                "unlock_at": a.get("unlock_at"),
                "lock_at": a.get("lock_at"),
                "submission_types": a.get("submission_types"),
                "description": a.get("description"),
            }
            details = {
                "due_at": a.get("due_at"),
                "unlock_at": a.get("unlock_at"),
                "lock_at": a.get("lock_at"),
                "points_possible": a.get("points_possible"),
                "submission_types": a.get("submission_types"),
                "description_text": html_to_text(a.get("description")),
                "submission_workflow_state": submission_state,
                "submitted_at": submitted_at,
                "graded_at": graded_at,
                "is_submitted": is_submitted,
            }
            if self.log_texts:
                dtxt = str(details.get("description_text") or "")
                if dtxt:
                    print_sample = dtxt[: self.max_text_chars]
                    details["description_sample"] = print_sample
            items.append(
                CanvasItem(
                    item_type="assignment",
                    course_id=course_id,
                    item_id=int(a["id"]),
                    title=a.get("name") or "Untitled assignment",
                    due_iso=iso_utc(due_at),
                    url=a.get("html_url") or "",
                    checksum=checksum_payload(payload),
                    details=details,
                )
            )

        for e in self.get_calendar_events(course_id, start=now, end=end):
            start_at = e.get("start_at")
            if not within_window(start_at, now, end):
                continue

            payload = {
                "title": e.get("title"),
                "start_at": e.get("start_at"),
                "html_url": e.get("html_url"),
                "location_name": e.get("location_name"),
                "description": e.get("description"),
            }
            details = {
                "start_at": e.get("start_at"),
                "location_name": e.get("location_name"),
                "description_text": html_to_text(e.get("description")),
            }
            if self.log_texts:
                dtxt = str(details.get("description_text") or "")
                if dtxt:
                    details["description_sample"] = dtxt[: self.max_text_chars]
            items.append(
                CanvasItem(
                    item_type="event",
                    course_id=course_id,
                    item_id=int(e["id"]),
                    title=e.get("title") or "Untitled event",
                    due_iso=iso_utc(start_at),
                    url=e.get("html_url") or "",
                    checksum=checksum_payload(payload),
                    details=details,
                )
            )

        return items
