from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


def sanitize_url(url: str, *, redact_query_keys: Optional[set[str]] = None) -> str:
    redact = redact_query_keys or set()
    parts = urlsplit(url)
    query_pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if k in redact:
            query_pairs.append((k, "<redacted>"))
        else:
            query_pairs.append((k, v))
    safe_query = urlencode(query_pairs)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query, parts.fragment))


def _safe_headers(headers: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (headers or {}).items():
        lk = str(k).lower()
        if lk in {"authorization", "cookie"}:
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def instrument_session(
    session: requests.Session,
    *,
    name: str,
    logger: logging.Logger,
    redact_query_keys: Optional[set[str]] = None,
    log_bodies: bool = False,
    max_body_chars: int = 800,
) -> None:
    redact = redact_query_keys or set()
    original = session.request

    def wrapped(method: str, url: str, **kwargs: Any) -> requests.Response:
        safe_url = sanitize_url(url, redact_query_keys=redact)
        headers = _safe_headers(kwargs.get("headers") or {})
        params = kwargs.get("params")
        data = kwargs.get("data")
        json_body = kwargs.get("json")
        timeout = kwargs.get("timeout")

        start = time.time()
        logger.debug(
            "[%s] %s %s params=%s timeout=%s headers=%s data=%s json=%s",
            name,
            method.upper(),
            safe_url,
            "yes" if params else "no",
            timeout,
            headers if headers else None,
            "yes" if data else "no",
            "yes" if json_body else "no",
        )
        resp = original(method, url, **kwargs)
        elapsed_ms = int((time.time() - start) * 1000)
        logger.debug("[%s] -> %s %sms", name, resp.status_code, elapsed_ms)

        if log_bodies and resp.status_code >= 400:
            body = (resp.text or "")[:max_body_chars]
            logger.debug("[%s] error_body=%r", name, body)
        return resp

    session.request = wrapped  # type: ignore[assignment]

