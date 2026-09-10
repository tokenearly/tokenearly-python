"""Allow ``python -m tokenearly``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
