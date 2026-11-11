"""HTTP transport shared by every metadata service."""

from __future__ import annotations

import re
import time

import requests

from papernym import __version__


_SECRET_PARAM = re.compile(r"((?:api_key|apikey|key|token)=)[^&\s'\"]+", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    """Hide API keys that request errors copy from the URL into their message."""
    return _SECRET_PARAM.sub(lambda match: match.group(1) + "***", text)


class NetError(RuntimeError):
    """A metadata service is unavailable or rejected the request."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(self, config: dict, session=None, sleep=None):
        self.config = config
        self.session = session or requests.Session()
        self.sleep = sleep or time.sleep

    def get(self, url: str, *, params=None, headers=None, kind: str = "json"):
        mail = f" (mailto:{self.config['email']})" if self.config.get("email") else ""
        request_headers = {"User-Agent": f"PaperNym/{__version__}{mail}"}
        request_headers.update(headers or {})
        for attempt in range(2):
            try:
                response = self.session.get(url, params=params, headers=request_headers, timeout=12)
            except requests.RequestException as exc:
                if attempt == 0:
                    self.sleep(1)
                    continue
                raise NetError(mask_secrets(str(exc))) from None
            status = response.status_code
            if status == 200:
                try:
                    return response.text if kind == "text" else response.json()
                except ValueError as exc:
                    raise NetError(f"invalid {kind} response") from exc
            if status in (400, 404, 410):
                return None
            if status in (401, 403):
                raise NetError(f"HTTP {status}: key rejected or access denied", status)
            if status == 429 or 500 <= status <= 599:
                if attempt == 0:
                    self.sleep(2)
                    continue
            raise NetError(f"HTTP {status}", status)
        raise AssertionError("unreachable retry state")
