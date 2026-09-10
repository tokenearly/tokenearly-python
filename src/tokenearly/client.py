"""Client for the public Tokenearly listings feed.

The feed is read-only and unauthenticated, so there is nothing to configure and
no account to create. Everything here is stdlib only, which keeps the install
small enough to drop into a cron job or a container without a resolver step.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

__all__ = [
    "BASE_URL",
    "Listing",
    "Exchange",
    "TokenearlyError",
    "Client",
    "listings",
    "exchanges",
]

BASE_URL = "https://tokenearly.com"
USER_AGENT = "tokenearly-python"

# Server-side caps, mirrored here so a bad argument fails locally with a clear
# message instead of being silently clamped and returning a surprising window.
MAX_DAYS = 30
MAX_LIMIT = 500
LISTING_TYPES = ("spot", "futures")


class TokenearlyError(RuntimeError):
    """Raised when the feed cannot be read or returns something unusable."""


@dataclass(frozen=True)
class Listing:
    """One listing announcement.

    ``title`` holds the headline in every language the feed publishes, so
    ``listing.headline("ko")`` works without a second request.
    """

    exchange: str
    exchange_name: str
    type: str
    symbols: List[str] = field(default_factory=list)
    published_at: Optional[str] = None
    title: Dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    permalink: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Listing":
        return cls(
            exchange=str(d.get("exchange") or ""),
            exchange_name=str(d.get("exchange_name") or ""),
            type=str(d.get("type") or ""),
            symbols=[str(s) for s in (d.get("symbols") or [])],
            published_at=d.get("published_at"),
            title={k: str(v) for k, v in (d.get("title") or {}).items() if v},
            source_url=str(d.get("source_url") or ""),
            permalink=str(d.get("permalink") or ""),
            raw=d,
        )

    def headline(self, lang: str = "en") -> str:
        """Headline in ``lang``, falling back through the other languages."""
        for key in (lang, "en", "zh", "ko"):
            value = self.title.get(key)
            if value:
                return value
        return ""

    @property
    def is_futures(self) -> bool:
        return self.type == "futures"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        syms = " ".join(self.symbols)
        return f"[{self.exchange_name}] {self.headline()}" + (f" ({syms})" if syms else "")


@dataclass(frozen=True)
class Exchange:
    """One monitored exchange and how its announcements are collected."""

    id: str
    name: str
    collection: str
    listings_30d: int = 0
    spot_30d: int = 0
    futures_30d: int = 0
    archive_url: str = ""
    name_i18n: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Exchange":
        return cls(
            id=str(d.get("id") or ""),
            name=str(d.get("name") or ""),
            collection=str(d.get("collection") or ""),
            listings_30d=int(d.get("listings_30d") or 0),
            spot_30d=int(d.get("spot_30d") or 0),
            futures_30d=int(d.get("futures_30d") or 0),
            archive_url=str(d.get("archive_url") or ""),
            name_i18n={k: str(v) for k, v in (d.get("name_i18n") or {}).items() if v},
        )

    @property
    def websocket(self) -> bool:
        """True when announcements arrive over the exchange's own WebSocket stream."""
        return self.collection == "websocket"


class Client:
    """Reads the public feed.

    >>> from tokenearly import Client
    >>> for item in Client().listings(days=1, exchange="binance"):
    ...     print(item.exchange_name, item.headline())
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = 20.0,
        retries: int = 2,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Retries cover the ordinary case of a dropped connection. They are
        # deliberately not applied to 4xx, which will not become valid by
        # asking again.
        self.retries = max(0, int(retries))
        self.user_agent = user_agent

    # ---- transport -------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        last: Optional[BaseException] = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8", "replace")
                break
            except urllib.error.HTTPError as exc:
                # A 4xx will not fix itself; fail immediately with the status.
                if 400 <= exc.code < 500:
                    raise TokenearlyError(f"{url} returned HTTP {exc.code}") from exc
                last = exc
            except (urllib.error.URLError, OSError) as exc:
                last = exc
            if attempt < self.retries:
                time.sleep(0.5 * (attempt + 1))
        else:
            raise TokenearlyError(f"could not read {url}: {last}") from last

        try:
            return json.loads(body)
        except ValueError as exc:
            raise TokenearlyError(f"{url} did not return JSON") from exc

    # ---- endpoints -------------------------------------------------------

    def listings(
        self,
        days: int = 7,
        exchange: str = "",
        type: str = "",  # noqa: A002 - matches the feed's parameter name
        limit: int = 200,
    ) -> List[Listing]:
        """Listing announcements from the last ``days`` days, newest first.

        ``exchange`` takes an exchange id such as ``binance``; ``type`` takes
        ``spot`` or ``futures``. Both default to everything.
        """
        if not 1 <= days <= MAX_DAYS:
            raise ValueError(f"days must be between 1 and {MAX_DAYS}, got {days}")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}, got {limit}")
        if type and type not in LISTING_TYPES:
            raise ValueError(f"type must be one of {LISTING_TYPES}, got {type!r}")

        payload = self._get(
            "/api/public/listings.json",
            {"days": days, "exchange": exchange.lower(), "type": type, "limit": limit},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise TokenearlyError("listings response had no items array")
        return [Listing.from_dict(d) for d in items if isinstance(d, dict)]

    def exchanges(self) -> List[Exchange]:
        """The monitored exchanges, busiest first."""
        payload = self._get("/api/public/exchanges.json")
        rows = payload.get("exchanges") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise TokenearlyError("exchanges response had no exchanges array")
        return [Exchange.from_dict(d) for d in rows if isinstance(d, dict)]

    # ---- polling ---------------------------------------------------------

    def watch(
        self,
        interval: float = 300.0,
        days: int = 1,
        exchange: str = "",
        type: str = "",  # noqa: A002
        seen: Optional[Iterable[str]] = None,
    ) -> Iterator[Listing]:
        """Yield each listing once, polling every ``interval`` seconds forever.

        Dedupe is by permalink and lives in memory, so a restart may re-emit
        whatever is still inside the ``days`` window. Pass ``seen`` to carry
        state across restarts yourself.
        """
        if interval <= 0:
            raise ValueError("interval must be positive")
        known = set(seen or ())
        while True:
            try:
                batch = self.listings(days=days, exchange=exchange, type=type, limit=MAX_LIMIT)
            except TokenearlyError:
                # A transient outage should not end a long-running watcher.
                batch = []
            for item in reversed(batch):  # oldest first, so output reads chronologically
                key = item.permalink or f"{item.exchange}:{item.published_at}:{item.headline()}"
                if key in known:
                    continue
                known.add(key)
                yield item
            time.sleep(interval)


_default = Client()


def listings(**kwargs: Any) -> List[Listing]:
    """Shortcut for ``Client().listings(...)``."""
    return _default.listings(**kwargs)


def exchanges() -> List[Exchange]:
    """Shortcut for ``Client().exchanges()``."""
    return _default.exchanges()
