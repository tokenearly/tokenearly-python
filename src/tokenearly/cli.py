"""Command line interface.

    tokenearly listings --exchange binance --type spot
    tokenearly exchanges
    tokenearly watch --interval 300

Every command takes ``--json`` so the output can be piped into jq or another
program instead of read by a person.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from .client import MAX_DAYS, MAX_LIMIT, Client, Listing, TokenearlyError

LANGS = ("en", "zh", "ko")


def _table(rows: List[List[str]], headers: Sequence[str]) -> str:
    """Plain text table. No dependency, and it stays aligned in a pipe."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()
    out = [line, "  ".join("-" * w for w in widths).rstrip()]
    for row in rows:
        out.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return "\n".join(out)


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _listing_row(item: Listing, lang: str, width: int) -> List[str]:
    return [
        (item.published_at or "")[:16].replace("T", " "),
        item.exchange_name or item.exchange,
        item.type,
        ",".join(item.symbols)[:24],
        _truncate(item.headline(lang), width),
    ]


def _print_listings(items: List[Listing], lang: str, width: int) -> None:
    if not items:
        print("No listings in that window.")
        return
    rows = [_listing_row(i, lang, width) for i in items]
    print(_table(rows, ["published (utc)", "exchange", "type", "symbols", "headline"]))
    print(f"\n{len(items)} listing(s).")


def _dump(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def _client(args: argparse.Namespace) -> Client:
    return Client(base_url=args.base_url, timeout=args.timeout)


def cmd_listings(args: argparse.Namespace) -> int:
    items = _client(args).listings(
        days=args.days, exchange=args.exchange, type=args.type, limit=args.limit
    )
    if args.json:
        _dump([i.raw for i in items])
    else:
        _print_listings(items, args.lang, args.width)
    return 0


def cmd_exchanges(args: argparse.Namespace) -> int:
    rows = _client(args).exchanges()
    if args.json:
        _dump(
            [
                {
                    "id": e.id,
                    "name": e.name,
                    "collection": e.collection,
                    "listings_30d": e.listings_30d,
                    "spot_30d": e.spot_30d,
                    "futures_30d": e.futures_30d,
                    "archive_url": e.archive_url,
                }
                for e in rows
            ]
        )
        return 0
    table = [
        [e.id, e.name, e.collection, str(e.listings_30d), str(e.spot_30d), str(e.futures_30d)]
        for e in rows
    ]
    print(_table(table, ["id", "name", "collection", "30d", "spot", "futures"]))
    total = sum(e.listings_30d for e in rows)
    ws = [e.id for e in rows if e.websocket]
    print(f"\n{len(rows)} exchanges, {total} listings in the last 30 days.")
    if ws:
        print("Announcements arrive over the exchange's own WebSocket stream for: " + ", ".join(ws))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        for item in client.watch(
            interval=args.interval, days=args.days, exchange=args.exchange, type=args.type
        ):
            if args.json:
                sys.stdout.write(json.dumps(item.raw, ensure_ascii=False) + "\n")
            else:
                syms = f"  [{' '.join(item.symbols)}]" if item.symbols else ""
                sys.stdout.write(
                    f"{(item.published_at or '')[:16].replace('T', ' ')}  "
                    f"{item.exchange_name}  {item.type}{syms}  "
                    f"{_truncate(item.headline(args.lang), args.width)}\n"
                )
            sys.stdout.flush()
    except KeyboardInterrupt:  # pragma: no cover - interactive
        return 130
    return 0


DEFAULTS = {
    "base_url": "https://tokenearly.com",
    "timeout": 20.0,
    "json": False,
    "lang": "en",
    "width": 72,
}


def _add_global_options(p: argparse.ArgumentParser, on_subparser: bool = False) -> None:
    """Options accepted both before and after the subcommand.

    argparse only accepts a parent-level flag before the subcommand, so
    `tokenearly listings --lang zh` fails with "unrecognized arguments" if
    these live on the top-level parser alone. Registering them on every
    subparser as well makes either position work.

    The subparser copies use ``SUPPRESS`` as their default so they set the
    attribute only when the flag is actually typed. With an ordinary default
    the subparser would overwrite a value given *before* the subcommand, and
    `tokenearly --lang zh listings` would silently print English.
    """
    d = (lambda key: argparse.SUPPRESS) if on_subparser else (lambda key: DEFAULTS[key])
    p.add_argument("--base-url", default=d("base_url"), help=argparse.SUPPRESS)
    p.add_argument("--timeout", type=float, default=d("timeout"),
                   help="request timeout in seconds")
    p.add_argument("--json", action="store_true", default=d("json"),
                   help="print raw JSON instead of a table")
    p.add_argument("--lang", default=d("lang"), choices=LANGS,
                   help="headline language (default: en)")
    p.add_argument("--width", type=int, default=d("width"), help="headline column width")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tokenearly",
        description=(
            "Read new crypto exchange token listings from the public Tokenearly feed. "
            "No account, no API key."
        ),
    )
    _add_global_options(parser)
    sub = parser.add_subparsers(dest="command")

    def add_filters(p: argparse.ArgumentParser, default_days: int) -> None:
        p.add_argument(
            "--days", type=int, default=default_days, help=f"look back N days (1-{MAX_DAYS})"
        )
        p.add_argument("--exchange", default="", help="exchange id, for example binance")
        p.add_argument("--type", default="", choices=["", "spot", "futures"], help="listing type")

    p_list = sub.add_parser("listings", help="recent listing announcements")
    _add_global_options(p_list, on_subparser=True)
    add_filters(p_list, 7)
    p_list.add_argument("--limit", type=int, default=50, help=f"max rows (1-{MAX_LIMIT})")
    p_list.set_defaults(func=cmd_listings)

    p_ex = sub.add_parser("exchanges", help="monitored exchanges and 30-day counts")
    _add_global_options(p_ex, on_subparser=True)
    p_ex.set_defaults(func=cmd_exchanges)

    p_watch = sub.add_parser("watch", help="poll and print each new listing once")
    _add_global_options(p_watch, on_subparser=True)
    add_filters(p_watch, 1)
    p_watch.add_argument(
        "--interval", type=float, default=300.0, help="seconds between polls (default: 300)"
    )
    p_watch.set_defaults(func=cmd_watch)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"tokenearly: {exc}", file=sys.stderr)
        return 2
    except TokenearlyError as exc:
        print(f"tokenearly: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
