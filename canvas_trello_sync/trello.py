from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import hashlib
from datetime import datetime, timezone


@dataclass(frozen=True)
class BoardLists:
    by_name: Dict[str, str]
    by_id: Dict[str, str]


@dataclass(frozen=True)
class LabelInfo:
    id: str
    color: str


def _raise_for_status_with_context(resp: requests.Response, *, method: str, url: str) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        text = (resp.text or "").strip()
        detail = f"{resp.status_code} {resp.reason} for {method} {url}"
        if resp.status_code == 401:
            hint = (
                "Trello auth failed (401). Double-check `TRELLO_KEY` and `TRELLO_TOKEN` (and that the token was "
                "generated for that key, with read/write access). Also ensure your `.env` is being loaded."
            )
            if text:
                raise SystemExit(f"{detail}\n{hint}\nResponse: {text}") from e
            raise SystemExit(f"{detail}\n{hint}") from e
        if text:
            raise SystemExit(f"{detail}\nResponse: {text}") from e
        raise SystemExit(detail) from e


class TrelloClient:
    def __init__(self, key: str, token: str) -> None:
        self.key = key
        self.token = token
        self.session = requests.Session()

    def _params(self) -> Dict[str, str]:
        return {"key": self.key, "token": self.token}

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"https://api.trello.com/1{path}"
        p = self._params()
        if params:
            p.update(params)
        r = self.session.get(url, params=p, timeout=30)
        _raise_for_status_with_context(r, method="GET", url=url)
        return r.json() if r.text else None

    def _post(self, path: str, data: Dict[str, Any]) -> Any:
        url = f"https://api.trello.com/1{path}"
        r = self.session.post(url, params=self._params(), data=data, timeout=30)
        _raise_for_status_with_context(r, method="POST", url=url)
        return r.json() if r.text else None

    def _put(self, path: str, data: Dict[str, Any]) -> Any:
        url = f"https://api.trello.com/1{path}"
        r = self.session.put(url, params=self._params(), data=data, timeout=30)
        _raise_for_status_with_context(r, method="PUT", url=url)
        return r.json() if r.text else None

    def validate_auth(self) -> Dict[str, Any]:
        return self._get("/members/me", params={"fields": "id,username,fullName"})

    def get_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        url = f"https://api.trello.com/1/cards/{card_id}"
        r = self.session.get(url, params={**self._params(), "fields": "id,name,desc,due,idList,closed"}, timeout=30)
        if r.status_code == 404:
            return None
        _raise_for_status_with_context(r, method="GET", url=url)
        return r.json() if r.text else None

    def set_card_closed(self, card_id: str, closed: bool) -> None:
        self._put(f"/cards/{card_id}", {"closed": "true" if closed else "false"})

    def move_card(self, card_id: str, list_id: str) -> None:
        self._put(f"/cards/{card_id}", {"idList": list_id})

    def get_board_id_from_url(self, board_url: str) -> str:
        parts = board_url.split("/")
        shortlink = ""
        try:
            b_index = parts.index("b")
            shortlink = parts[b_index + 1]
        except (ValueError, IndexError):
            shortlink = ""

        shortlink = shortlink.strip()
        if not shortlink:
            raise SystemExit("Could not parse TRELLO_BOARD_URL. Set TRELLO_BOARD_ID instead.")
        board = self._get(f"/boards/{shortlink}", params={"fields": "id"})
        return board["id"]

    def get_board_lists(self, board_id: str) -> BoardLists:
        lists: List[Dict[str, Any]] = self._get(
            f"/boards/{board_id}/lists", params={"fields": "id,name", "filter": "open"}
        )
        by_name: Dict[str, str] = {}
        by_id: Dict[str, str] = {}
        for lst in lists:
            by_name[str(lst["name"])] = str(lst["id"])
            by_id[str(lst["id"])] = str(lst["name"])
        return BoardLists(by_name=by_name, by_id=by_id)

    def get_board_labels(self, board_id: str) -> Dict[str, LabelInfo]:
        labels: List[Dict[str, Any]] = self._get(
            f"/boards/{board_id}/labels", params={"fields": "id,name,color", "limit": 1000}
        )
        out: Dict[str, LabelInfo] = {}
        for lbl in labels:
            name = (lbl.get("name") or "").strip()
            if name:
                out[name] = LabelInfo(id=str(lbl["id"]), color=str(lbl.get("color") or ""))
        return out

    @staticmethod
    def _pick_label_color(seed: str) -> str:
        colors = ["green", "yellow", "orange", "red", "purple", "blue", "sky", "lime", "pink", "black"]
        h = hashlib.sha256(seed.encode("utf-8")).digest()
        return colors[h[0] % len(colors)]

    def update_label(self, label_id: str, *, name: Optional[str] = None, color: Optional[str] = None) -> None:
        data: Dict[str, Any] = {}
        if name is not None:
            data["name"] = name
        if color is not None:
            data["color"] = color
        self._put(f"/labels/{label_id}", data)

    def ensure_label(
        self, board_id: str, name: str, existing: Dict[str, LabelInfo], *, color: Optional[str] = None
    ) -> str:
        if name in existing:
            info = existing[name]
            desired = (color or "").strip()
            if desired and info.color != desired:
                self.update_label(info.id, color=desired)
                existing[name] = LabelInfo(id=info.id, color=desired)
            return info.id
        chosen = (color or "").strip() or self._pick_label_color(name)
        lbl = self._post("/labels", {"idBoard": board_id, "name": name, "color": chosen})
        label_id = str(lbl["id"])
        existing[name] = LabelInfo(id=label_id, color=chosen)
        return label_id

    def add_label_to_card(self, card_id: str, label_id: str) -> None:
        url = f"https://api.trello.com/1/cards/{card_id}/idLabels"
        r = self.session.post(url, params=self._params(), data={"value": label_id}, timeout=30)
        if r.status_code in (200, 201):
            return
        # Trello may return 400 if label already exists on the card.
        if r.status_code == 400 and ("already" in (r.text or "").lower() or "exists" in (r.text or "").lower()):
            return
        _raise_for_status_with_context(r, method="POST", url=url)

    def get_open_cards(self, board_id: str) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = self._get(
            f"/boards/{board_id}/cards", params={"fields": "id,idList", "filter": "open"}
        )
        return cards

    def archive_card(self, card_id: str) -> None:
        self._put(f"/cards/{card_id}", {"closed": "true"})

    def archive_list(self, list_id: str) -> None:
        self._put(f"/lists/{list_id}", {"closed": "true"})

    def wipe_board(self, board_id: str) -> None:
        cards = self.get_open_cards(board_id)
        for c in cards:
            self.archive_card(str(c["id"]))

        lists = self._get(f"/boards/{board_id}/lists", params={"fields": "id", "filter": "open"}) or []
        for lst in lists:
            self.archive_list(str(lst["id"]))

    def wipe_managed(
        self,
        board_id: str,
        *,
        managed_cards: List[Dict[str, Any]],
        managed_list_ids: List[str],
        protected_list_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        protected = {str(x) for x in (protected_list_ids or []) if x}
        managed_list_set = {str(x) for x in managed_list_ids if x} - protected

        eligible_cards: Dict[str, Dict[str, Any]] = {}
        for c in managed_cards:
            if not isinstance(c, dict):
                continue
            cid = str(c.get("card_id") or "")
            if not cid:
                continue
            eligible_cards[cid] = c

        archived_cards: List[str] = []
        for c in self.get_open_cards(board_id):
            cid = str(c.get("id") or "")
            if not cid or cid not in eligible_cards:
                continue

            info = eligible_cards[cid]
            if info.get("locked") is True or str(info.get("status") or "") in {"done", "manual"}:
                continue

            origin = str(info.get("origin_list_id") or "")
            current_list = str(c.get("idList") or "")
            if origin and current_list != origin:
                continue

            # If the user manually edited the card (name/desc/due), don't wipe it.
            rendered_name = str(info.get("rendered_name") or "")
            rendered_desc = str(info.get("rendered_desc") or "")
            rendered_due = str(info.get("rendered_due") or "")
            if rendered_name or rendered_desc or rendered_due:
                full = self.get_card(cid)
                if full is None:
                    continue

                def _norm(s: str) -> str:
                    return (s or "").replace("\r\n", "\n").strip()

                def _parse_due(s: str) -> Optional[datetime]:
                    if not s:
                        return None
                    try:
                        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
                    except Exception:
                        return None

                due_ok = True
                if rendered_due or full.get("due"):
                    da = _parse_due(str(rendered_due))
                    db = _parse_due(str(full.get("due") or ""))
                    due_ok = (da is None and db is None) or (da is not None and db is not None and int(da.timestamp()) == int(db.timestamp()))

                if _norm(str(full.get("name") or "")) != _norm(rendered_name) or _norm(str(full.get("desc") or "")) != _norm(
                    rendered_desc
                ) or not due_ok:
                    continue

            self.archive_card(cid)
            archived_cards.append(cid)

        if not managed_list_set:
            return {"archived_cards": archived_cards, "archived_lists": []}

        remaining = self.get_open_cards(board_id)
        list_has_any_cards: Dict[str, bool] = {}
        for c in remaining:
            lid = str(c.get("idList") or "")
            if lid:
                list_has_any_cards[lid] = True

        archived_lists: List[str] = []
        for list_id in managed_list_set:
            if list_has_any_cards.get(list_id):
                continue
            self.archive_list(list_id)
            archived_lists.append(list_id)

        return {"archived_cards": archived_cards, "archived_lists": archived_lists}

    def ensure_list(self, board_id: str, list_name: str, existing: BoardLists, *, pos: str = "bottom") -> str:
        if list_name in existing.by_name:
            return existing.by_name[list_name]
        new_list = self._post("/lists", {"name": list_name, "idBoard": board_id, "pos": pos})
        existing.by_name[list_name] = new_list["id"]
        existing.by_id[new_list["id"]] = list_name
        return new_list["id"]

    def create_card(
        self,
        list_id: str,
        name: str,
        desc: str,
        due_iso: Optional[str],
        *,
        label_ids: Optional[List[str]] = None,
        pos: Optional[str] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"idList": list_id, "name": name, "desc": desc}
        if due_iso:
            data["due"] = due_iso
        if label_ids:
            data["idLabels"] = ",".join(label_ids)
        if pos:
            data["pos"] = pos
        return self._post("/cards", data)

    def update_card(
        self,
        card_id: str,
        name: str,
        desc: str,
        due_iso: Optional[str],
        *,
        label_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        data: Dict[str, Any] = {"name": name, "desc": desc, "due": due_iso or ""}
        if label_ids is not None:
            data["idLabels"] = ",".join(label_ids)
        return self._put(f"/cards/{card_id}", data)

    def set_card_pos_top(self, card_id: str) -> None:
        self._put(f"/cards/{card_id}", {"pos": "top"})

    def get_list_cards(self, list_id: str) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = self._get(
            f"/lists/{list_id}/cards", params={"fields": "id,due,name", "filter": "open"}
        )
        return cards

    def set_card_cover(
        self,
        card_id: str,
        *,
        color: str,
        size: Optional[str] = None,
        brightness: Optional[str] = "dark",
    ) -> None:
        data: Dict[str, Any] = {"color": color}
        if size:
            data["size"] = size
        if brightness:
            data["brightness"] = brightness
        url = f"https://api.trello.com/1/cards/{card_id}/cover"
        params = {**self._params(), **data}
        r = self.session.put(url, params=params, timeout=30)
        _raise_for_status_with_context(r, method="PUT", url=url)

    def set_card_cover_color(self, card_id: str, color: str) -> None:
        self.set_card_cover(card_id, color=color)
