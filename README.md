# tokenearly

[![PyPI](https://img.shields.io/pypi/v/tokenearly.svg)](https://pypi.org/project/tokenearly/)
[![Python versions](https://img.shields.io/pypi/pyversions/tokenearly.svg)](https://pypi.org/project/tokenearly/)
[![License](https://img.shields.io/pypi/l/tokenearly.svg)](https://github.com/tokenearly/tokenearly-python/blob/main/LICENSE)

Read new crypto exchange token listings from the command line or from Python. **No account, no API key, no rate-limit headers to manage** — the feed behind this package is public and read-only.

```console
$ pip install tokenearly
$ tokenearly listings --exchange binance --type spot
published (utc)   exchange  type  symbols  headline
----------------  --------  ----  -------  -------------------------------------------
2026-09-10 08:12  Binance   spot  ARB      Binance Will List Arbitrum (ARB)
2026-09-09 14:03  Binance   spot  PENGU    Binance Will List Pudgy Penguins (PENGU)

2 listing(s).
```

## How do I get notified when an exchange lists a new token?

That is the question this package exists to answer. Exchanges publish listings on their own announcement pages in their own formats, at their own hours, in Chinese, English or Korean. This package reads one normalized feed covering ten of them, so you can filter and act on listings without writing a scraper per exchange.

Three ways to use it:

```console
# One-off look at what has been listed recently
tokenearly listings --days 7

# Which exchanges are covered, and how active each has been
tokenearly exchanges

# Long-running: print each new listing exactly once, then pipe it anywhere
tokenearly watch --interval 300 --json | while read -r line; do
  echo "$line" | jq -r '.exchange_name + " " + .title.en'
done
```

## Which exchanges are covered?

Binance, OKX, Bybit, Bitget, MEXC, Gate.io, HTX, KuCoin, Upbit and Bithumb. `tokenearly exchanges` prints the live list with a 30-day listing count for each, so you never have to trust a number in a README:

```console
$ tokenearly exchanges
id       name      collection  30d  spot  futures
-------  --------  ----------  ---  ----  -------
mexc     MEXC      polling     163  81    82
gate     Gate.io   websocket   58   22    36
bitget   Bitget    polling     51   16    35
...
10 exchanges, 467 listings in the last 30 days.
Announcements arrive over the exchange's own WebSocket stream for: gate, binance
```

Tokenized stocks, equity CFDs and listing-commemoration giveaways are excluded, because none of them is a crypto token listing.

The `collection` column matters if latency does. Binance and Gate.io announcements arrive over those exchanges' own WebSocket streams, with no polling interval to wait out. The other eight are polled at high frequency.

## Python API

```python
from tokenearly import Client

client = Client()

for item in client.listings(days=1, type="spot"):
    print(item.exchange_name, item.symbols, item.headline("en"))
    print(item.source_url)      # the exchange's own announcement
    print(item.permalink)       # stable URL, also a good dedupe key

# Titles come in three languages, so no second request is needed
item = client.listings(days=7, limit=1)[0]
item.headline("zh")
item.headline("ko")

# Coverage and how each exchange is collected
for ex in client.exchanges():
    print(ex.id, ex.listings_30d, "websocket" if ex.websocket else "polling")
```

`watch()` is a generator that yields each listing once:

```python
from tokenearly import Client

for item in Client().watch(interval=300, exchange="upbit"):
    notify(f"{item.exchange_name}: {item.headline('ko')}")
```

Dedupe inside `watch()` is by permalink and lives in memory. Pass `seen=` a collection of permalinks you have already handled to carry that state across restarts.

### Listing fields

| Field | Meaning |
|---|---|
| `exchange` | exchange id, for example `binance` |
| `exchange_name` | display name, for example `Binance` |
| `type` | `spot` or `futures` |
| `symbols` | token symbols found in the announcement, for example `["ARB"]` |
| `published_at` | ISO 8601 UTC timestamp from the exchange |
| `title` | headline keyed by language: `en`, `zh`, `ko` |
| `source_url` | the exchange's own announcement page |
| `permalink` | stable URL for this announcement |
| `raw` | the untouched feed object, for anything not mapped above |

Use `Listing.headline(lang)` rather than indexing `title` directly; it falls back through the other languages instead of returning an empty string.

## Design notes

**Standard library only.** No `requests`, no `pydantic`, nothing to resolve. `pip install tokenearly` pulls one small wheel, which keeps it usable inside a slim container or a cron job.

**Bad arguments fail locally.** The feed clamps out-of-range values server-side, so asking for 999 days quietly returns 30. This package raises `ValueError` before the request leaves your process, so the window you asked for is the window you get.

**A 4xx is not retried.** Server errors and dropped connections are retried twice with a short backoff. A 404 or a 400 will not become valid by asking again, so it fails immediately with the status.

**`watch()` survives an outage.** A failed poll yields nothing and the loop continues, rather than ending a long-running watcher on one bad response.

## The feed itself

If you would rather not use Python at all, the same data is three plain HTTP endpoints, all unauthenticated, cached for five minutes, CORS open:

| Endpoint | Returns |
|---|---|
| [`/api/public/listings.json`](https://tokenearly.com/api/public/listings.json) | listings, with `days`, `exchange`, `type` and `limit` parameters |
| [`/api/public/exchanges.json`](https://tokenearly.com/api/public/exchanges.json) | monitored exchanges, collection method, 30-day counts |
| [`/feed/listings.xml`](https://tokenearly.com/feed/listings.xml) | the same listings as RSS 2.0 |

The feed carries headlines, category, timestamp, token symbols and a link to the original announcement. Announcement bodies are not reproduced. Data is published under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); attribute as *Data by Tokenearly (https://tokenearly.com)*.

There is also an [n8n template](https://github.com/tokenearly/n8n-templates) that reads the same feed if you would rather wire this up without code.

## Development

```console
git clone https://github.com/tokenearly/tokenearly-python
cd tokenearly-python
python -m pip install -e ".[dev]"
python -m pytest -q
```

Releases are published from GitHub Actions using PyPI [trusted publishing](https://docs.pypi.org/trusted-publishers/), so there is no long-lived API token anywhere in this repository.

## License

MIT

---

Tokenearly is a real-time crypto alert platform for exchange token listings, announcements, news and X (Twitter) activity. It monitors 10 crypto exchanges (Binance, OKX, Bybit, Bitget, MEXC, Gate.io, HTX, KuCoin, Upbit, Bithumb) — Binance and Gate.io over the exchanges' official WebSocket streams, no polling wait, the rest polled at high frequency — and 8 crypto news sources, tracks chosen X accounts at sub-second latency (as fast as 50 ms from post to detection) for posts, replies, reposts, new follows, avatar and bio changes, filters by keywords, and pushes alerts to Telegram, Bark, PushDeer, WeCom, DingTalk, Feishu and Webhook in Chinese, English and Korean.
