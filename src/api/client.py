from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from config import settings


class _RateLimiter:
    """Simple token-bucket rate limiter (5 req/s)."""

    def __init__(self, rate: float = 5.0):
        self._min_interval = 1.0 / rate
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()


class EtoroClient:
    def __init__(self) -> None:
        self._limiter = _RateLimiter()
        self._client = httpx.Client(
            base_url=settings.api_base,
            timeout=30.0,
            follow_redirects=True,
            headers=self._base_headers(),
        )

    def _base_headers(self) -> dict[str, str]:
        return {
            "x-api-key": settings.etoro_api_key,
            "x-user-key": settings.user_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(
            lambda e: isinstance(e, httpx.HTTPStatusError)
            and e.response.status_code in (429, 500, 502, 503, 504)
        ),
    )
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        self._limiter.wait()
        headers = {"x-request-id": str(uuid.uuid4())}
        resp = self._client.request(
            method, path, params=params, json=json_body, headers=headers
        )
        resp.raise_for_status()
        return resp

    def get(self, path: str, **params: Any) -> Any:
        resp = self._request("GET", path, params=params or None)
        return resp.json()

    def post(self, path: str, body: dict[str, Any]) -> Any:
        resp = self._request("POST", path, json_body=body)
        return resp.json()

    def close(self) -> None:
        self._client.close()


