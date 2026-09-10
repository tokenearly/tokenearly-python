"""Tests for the client. No network: the transport is stubbed."""

import json

import pytest

from tokenearly.client import (
    MAX_DAYS,
    MAX_LIMIT,
    Client,
    Exchange,
    Listing,
    TokenearlyError,
)

LISTING = {
    "exchange": "binance",
    "exchange_name": "Binance",
    "type": "spot",
    "symbols": ["ARB", "OP"],
    "published_at": "2026-09-10T08:12:00Z",
    "title": {
        "en": "Binance Will List Arbitrum (ARB)",
        "zh": "币安将上线 Arbitrum (ARB)",
        "ko": "바이낸스 Arbitrum (ARB) 상장",
    },
    "source_url": "https://www.binance.com/en/support/announcement/x",
    "permalink": "https://tokenearly.com/announcement/abc.html",
}

EXCHANGE = {
    "id": "gate",
    "name": "Gate.io",
    "name_i18n": {"zh": "芝麻开门"},
    "collection": "websocket",
    "listings_30d": 67,
    "spot_30d": 26,
    "futures_30d": 41,
    "archive_url": "https://tokenearly.com/en/exchanges/gate/announcements",
}


class _Stub(Client):
    """Client whose transport returns canned payloads and records the calls."""

    def __init__(self, payloads, **kw):
        super().__init__(**kw)
        self._payloads = payloads
        self.calls = []

    def _get(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        value = self._payloads[path]
        if isinstance(value, Exception):
            raise value
        return value


class TestListing:
    def test_from_dict_maps_every_field(self):
        item = Listing.from_dict(LISTING)
        assert item.exchange == "binance"
        assert item.exchange_name == "Binance"
        assert item.type == "spot"
        assert item.symbols == ["ARB", "OP"]
        assert item.permalink.endswith("abc.html")
        assert item.raw is LISTING

    def test_headline_falls_back_through_languages(self):
        item = Listing.from_dict(LISTING)
        assert item.headline("ko").startswith("바이낸스")
        assert item.headline("zh").startswith("币安")
        # A language the feed does not carry falls back rather than returning ""
        assert item.headline("fr") == LISTING["title"]["en"]

    def test_headline_of_an_empty_title_is_empty_not_an_error(self):
        assert Listing.from_dict({"title": {}}).headline() == ""

    def test_is_futures(self):
        assert Listing.from_dict({"type": "futures"}).is_futures
        assert not Listing.from_dict({"type": "spot"}).is_futures

    def test_missing_fields_do_not_raise(self):
        item = Listing.from_dict({})
        assert item.exchange == "" and item.symbols == [] and item.title == {}

    def test_symbols_are_coerced_to_strings(self):
        assert Listing.from_dict({"symbols": [1, "OP"]}).symbols == ["1", "OP"]


class TestExchange:
    def test_from_dict_and_websocket_flag(self):
        ex = Exchange.from_dict(EXCHANGE)
        assert ex.id == "gate" and ex.name == "Gate.io"
        assert ex.listings_30d == 67 and ex.spot_30d == 26 and ex.futures_30d == 41
        assert ex.websocket is True
        assert ex.name_i18n["zh"] == "芝麻开门"

    def test_polling_exchange_is_not_websocket(self):
        assert Exchange.from_dict({"collection": "polling"}).websocket is False

    def test_counts_default_to_zero(self):
        ex = Exchange.from_dict({"id": "x"})
        assert (ex.listings_30d, ex.spot_30d, ex.futures_30d) == (0, 0, 0)


class TestListings:
    def _client(self, items=None):
        return _Stub({"/api/public/listings.json": {"count": 1, "items": items or [LISTING]}})

    def test_returns_typed_listings(self):
        items = self._client().listings()
        assert len(items) == 1 and isinstance(items[0], Listing)

    def test_sends_the_documented_query_parameters(self):
        c = self._client()
        c.listings(days=3, exchange="BINANCE", type="spot", limit=10)
        path, params = c.calls[0]
        assert path == "/api/public/listings.json"
        # exchange is lowercased for the caller, so "BINANCE" still matches
        assert params == {"days": 3, "exchange": "binance", "type": "spot", "limit": 10}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"days": 0},
            {"days": MAX_DAYS + 1},
            {"limit": 0},
            {"limit": MAX_LIMIT + 1},
            {"type": "perpetual"},
        ],
    )
    def test_bad_arguments_fail_locally_instead_of_being_clamped(self, kwargs):
        """The server clamps silently; failing here keeps the window honest."""
        c = self._client()
        with pytest.raises(ValueError):
            c.listings(**kwargs)
        assert c.calls == []  # never left the process

    def test_edges_of_the_allowed_range_are_accepted(self):
        c = self._client()
        c.listings(days=1, limit=1)
        c.listings(days=MAX_DAYS, limit=MAX_LIMIT)
        assert len(c.calls) == 2

    def test_response_without_items_is_an_error_not_an_empty_list(self):
        c = _Stub({"/api/public/listings.json": {"count": 0}})
        with pytest.raises(TokenearlyError, match="items"):
            c.listings()

    def test_non_dict_entries_are_skipped(self):
        c = _Stub({"/api/public/listings.json": {"items": [LISTING, "junk", None]}})
        assert len(c.listings()) == 1


class TestExchanges:
    def test_returns_typed_exchanges(self):
        c = _Stub({"/api/public/exchanges.json": {"exchanges": [EXCHANGE]}})
        rows = c.exchanges()
        assert len(rows) == 1 and rows[0].id == "gate"

    def test_response_without_array_is_an_error(self):
        c = _Stub({"/api/public/exchanges.json": {"total": 10}})
        with pytest.raises(TokenearlyError, match="exchanges"):
            c.exchanges()


class TestWatch:
    def test_yields_each_listing_once_and_oldest_first(self, monkeypatch):
        newer = dict(LISTING, permalink="p2", published_at="2026-09-10T09:00:00Z")
        older = dict(LISTING, permalink="p1", published_at="2026-09-10T08:00:00Z")
        # The feed returns newest first; watch should emit chronologically.
        c = _Stub({"/api/public/listings.json": {"items": [newer, older]}})
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)

        seen = []
        for item in c.watch(interval=1):
            seen.append(item.permalink)
            if len(seen) == 2:
                break
        assert seen == ["p1", "p2"]

    def test_already_seen_permalinks_are_not_re_emitted(self, monkeypatch):
        c = _Stub({"/api/public/listings.json": {"items": [LISTING]}})
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)
        gen = c.watch(interval=1, seen={LISTING["permalink"]})
        # Nothing new, so pulling would loop forever; assert via a bounded poll.
        c._payloads["/api/public/listings.json"] = {"items": [LISTING, dict(LISTING, permalink="p9")]}
        assert next(gen).permalink == "p9"

    def test_a_feed_outage_does_not_end_the_watcher(self, monkeypatch):
        c = _Stub({"/api/public/listings.json": TokenearlyError("boom")})
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)
        gen = c.watch(interval=1)
        c._payloads["/api/public/listings.json"] = {"items": [LISTING]}
        assert next(gen).exchange == "binance"

    def test_non_positive_interval_is_rejected(self):
        with pytest.raises(ValueError):
            next(Client().watch(interval=0))


class TestTransport:
    def test_base_url_trailing_slash_is_normalised(self):
        assert Client(base_url="https://example.com/").base_url == "https://example.com"

    def test_empty_params_are_dropped_from_the_query(self, monkeypatch):
        captured = {}

        class _Resp:
            def read(self):
                return json.dumps({"items": []}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["ua"] = request.headers.get("User-agent")
            return _Resp()

        monkeypatch.setattr("tokenearly.client.urllib.request.urlopen", fake_urlopen)
        Client().listings(days=1, exchange="", type="", limit=5)
        assert "exchange=" not in captured["url"] and "type=" not in captured["url"]
        assert "days=1" in captured["url"] and "limit=5" in captured["url"]
        assert captured["ua"] == "tokenearly-python"

    def test_client_error_is_not_retried(self, monkeypatch):
        import urllib.error

        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        monkeypatch.setattr("tokenearly.client.urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)
        with pytest.raises(TokenearlyError, match="404"):
            Client(retries=3).listings()
        assert calls["n"] == 1  # a 404 will not become valid by asking again

    def test_server_error_is_retried_then_reported(self, monkeypatch):
        import urllib.error

        calls = {"n": 0}

        def fake_urlopen(request, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

        monkeypatch.setattr("tokenearly.client.urllib.request.urlopen", fake_urlopen)
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)
        with pytest.raises(TokenearlyError):
            Client(retries=2).listings()
        assert calls["n"] == 3

    def test_non_json_body_is_reported_clearly(self, monkeypatch):
        class _Resp:
            def read(self):
                return b"<html>gateway</html>"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            "tokenearly.client.urllib.request.urlopen", lambda r, timeout=None: _Resp()
        )
        with pytest.raises(TokenearlyError, match="did not return JSON"):
            Client().listings()
