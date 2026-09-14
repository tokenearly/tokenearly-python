"""Read new crypto exchange token listings from the public Tokenearly feed.

The feed is read-only and needs no account and no API key:

    >>> from tokenearly import listings
    >>> for item in listings(days=1, exchange="binance"):
    ...     print(item.exchange_name, item.headline())

There is also a command line entry point:

    tokenearly listings --exchange binance --type spot
    tokenearly exchanges
    tokenearly watch --interval 300
"""

from .client import (
    BASE_URL,
    Client,
    Exchange,
    Listing,
    TokenearlyError,
    exchanges,
    listings,
)

__version__ = "0.1.1"
__all__ = [
    "BASE_URL",
    "Client",
    "Exchange",
    "Listing",
    "TokenearlyError",
    "exchanges",
    "listings",
    "__version__",
]
