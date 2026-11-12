"""NSE India HTTP session helper with cookie bootstrap and retry handling."""

from __future__ import annotations

import logging
from typing import Any
import requests

from ingestion.common.retry import with_retry

logger = logging.getLogger(__name__)

NSE_BASE_URL = "https://www.nseindia.com"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}


class NSESession:
    """Manages an HTTP session with NSE India cookie initialization."""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._warmed = False

    def _warmup(self) -> None:
        try:
            self.session.get(NSE_BASE_URL, timeout=self.timeout)
            self._warmed = True
        except requests.RequestException as exc:
            logger.debug("NSE homepage warm-up warning: %s", exc)

    @with_retry(max_attempts=3, delays=(2.0, 4.0, 8.0))
    def get_json(self, path_or_url: str) -> Any:
        if not self._warmed:
            self._warmup()
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{NSE_BASE_URL}{path_or_url}"
        )
        resp = self.session.get(url, timeout=self.timeout)
        if resp.status_code in (401, 403):
            self._warmup()
            resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @with_retry(max_attempts=3, delays=(2.0, 4.0, 8.0))
    def get_text(self, url: str) -> str:
        if not self._warmed and "nseindia.com" in url:
            self._warmup()
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text
