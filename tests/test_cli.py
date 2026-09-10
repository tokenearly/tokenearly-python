"""Tests for the command line interface. No network."""

import json

import pytest

from tokenearly import cli
from tokenearly.client import TokenearlyError

LISTING = {
    "exchange": "binance",
    "exchange_name": "Binance",
    "type": "spot",
    "symbols": ["ARB"],
    "published_at": "2026-09-10T08:12:00Z",
    "title": {"en": "Binance Will List Arbitrum (ARB)", "zh": "币安将上线 Arbitrum (ARB)"},
    "source_url": "https://www.binance.com/x",
    "permalink": "https://tokenearly.com/announcement/abc.html",
}
EXCHANGE = {
    "id": "gate",
    "name": "Gate.io",
    "collection": "websocket",
    "listings_30d": 67,
    "spot_30d": 26,
    "futures_30d": 41,
}


@pytest.fixture
def feed(monkeypatch):
    """Stub the transport for whatever Client the CLI constructs."""
    state = {"listings": {"count": 1, "items": [LISTING]},
             "exchanges": {"exchanges": [EXCHANGE]},
             "raise": None}

    def fake_get(self, path, params=None):
        if state["raise"] is not None:
            raise state["raise"]
        return state["listings"] if "listings" in path else state["exchanges"]

    monkeypatch.setattr("tokenearly.client.Client._get", fake_get)
    return state


class TestListingsCommand:
    def test_table_output_contains_the_headline_and_exchange(self, feed, capsys):
        assert cli.main(["listings"]) == 0
        out = capsys.readouterr().out
        assert "Binance" in out and "Arbitrum" in out
        assert "1 listing(s)." in out

    def test_lang_switches_the_headline(self, feed, capsys):
        assert cli.main(["--lang", "zh", "listings"]) == 0
        assert "币安将上线" in capsys.readouterr().out

    def test_json_output_is_the_raw_feed_objects(self, feed, capsys):
        assert cli.main(["--json", "listings"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == [LISTING]

    def test_empty_window_says_so_instead_of_printing_an_empty_table(self, feed, capsys):
        feed["listings"] = {"count": 0, "items": []}
        assert cli.main(["listings"]) == 0
        assert "No listings" in capsys.readouterr().out

    def test_bad_days_exits_two_with_a_message_not_a_traceback(self, feed, capsys):
        assert cli.main(["listings", "--days", "999"]) == 2
        assert "days must be between" in capsys.readouterr().err

    def test_bad_type_is_rejected_by_the_parser(self, feed):
        with pytest.raises(SystemExit):
            cli.main(["listings", "--type", "perpetual"])

    def test_feed_failure_exits_one(self, feed, capsys):
        feed["raise"] = TokenearlyError("could not read feed")
        assert cli.main(["listings"]) == 1
        assert "could not read feed" in capsys.readouterr().err

    def test_long_headline_is_truncated_to_the_width(self, feed, capsys):
        feed["listings"] = {"items": [dict(LISTING, title={"en": "x" * 200})]}
        assert cli.main(["--width", "20", "listings"]) == 0
        # 19 characters plus the ellipsis
        assert "x" * 19 + "…" in capsys.readouterr().out


class TestExchangesCommand:
    def test_table_lists_counts_and_names_the_websocket_exchanges(self, feed, capsys):
        assert cli.main(["exchanges"]) == 0
        out = capsys.readouterr().out
        assert "gate" in out and "67" in out
        assert "1 exchanges, 67 listings in the last 30 days." in out
        assert "WebSocket stream for: gate" in out

    def test_no_websocket_line_when_all_are_polled(self, feed, capsys):
        feed["exchanges"] = {"exchanges": [dict(EXCHANGE, collection="polling")]}
        assert cli.main(["exchanges"]) == 0
        assert "WebSocket" not in capsys.readouterr().out

    def test_json_output(self, feed, capsys):
        assert cli.main(["--json", "exchanges"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert rows[0]["id"] == "gate" and rows[0]["listings_30d"] == 67


class TestWatchCommand:
    def test_prints_one_line_per_new_listing(self, feed, monkeypatch, capsys):
        monkeypatch.setattr("tokenearly.client.time.sleep", lambda _s: None)
        calls = {"n": 0}
        real = cli.Client.watch

        def bounded(self, **kw):
            for item in real(self, **kw):
                calls["n"] += 1
                yield item
                if calls["n"] >= 1:
                    return

        monkeypatch.setattr("tokenearly.cli.Client.watch", bounded)
        assert cli.main(["watch", "--interval", "1"]) == 0
        out = capsys.readouterr().out
        assert "Binance" in out and "ARB" in out
        assert out.count("\n") == 1


class TestParser:
    def test_no_command_prints_help_and_exits_two(self, capsys):
        assert cli.main([]) == 2
        assert "usage" in capsys.readouterr().out.lower()

    def test_defaults_match_the_documented_values(self):
        args = cli.build_parser().parse_args(["listings"])
        assert args.days == 7 and args.limit == 50 and args.lang == "en"
        watch = cli.build_parser().parse_args(["watch"])
        assert watch.days == 1 and watch.interval == 300.0

    def test_table_helper_aligns_columns(self):
        text = cli._table([["a", "bbb"], ["cccc", "d"]], ["h1", "h2"])
        lines = text.splitlines()
        assert lines[0].startswith("h1")
        # every row starts at the same offset for the second column
        assert lines[2].index("bbb") == lines[3].index("d")


class TestGlobalOptionPosition:
    """全局选项在子命令前后都必须生效，且前置的值不能被子命令默认值覆盖。

    第一版把全局项只挂在顶层 parser 上，`tokenearly listings --lang zh` 直接报
    unrecognized arguments。改成也挂到每个子命令后，前置写法又被子命令的默认值
    静默覆盖成英文。两个方向都要锁。
    """

    @pytest.mark.parametrize(
        "argv",
        [
            ["--lang", "zh", "listings"],   # 子命令之前
            ["listings", "--lang", "zh"],   # 子命令之后
        ],
    )
    def test_lang_works_in_both_positions(self, feed, capsys, argv):
        assert cli.main(argv) == 0
        assert "币安将上线" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "argv",
        [["--json", "listings"], ["listings", "--json"]],
    )
    def test_json_works_in_both_positions(self, feed, capsys, argv):
        assert cli.main(argv) == 0
        assert json.loads(capsys.readouterr().out) == [LISTING]

    @pytest.mark.parametrize(
        "argv",
        [["--width", "20", "listings"], ["listings", "--width", "20"]],
    )
    def test_width_works_in_both_positions(self, feed, capsys, argv):
        feed["listings"] = {"items": [dict(LISTING, title={"en": "x" * 200})]}
        assert cli.main(argv) == 0
        assert "x" * 19 + "…" in capsys.readouterr().out

    def test_defaults_apply_when_nothing_is_given(self, feed, capsys):
        assert cli.main(["listings"]) == 0
        out = capsys.readouterr().out
        assert "Arbitrum" in out          # en headline
        assert "币安" not in out

    def test_subcommand_value_wins_over_a_preceding_one(self, feed, capsys):
        """两处都给时，靠近命令的那个生效，符合一般 CLI 直觉。"""
        assert cli.main(["--lang", "en", "listings", "--lang", "zh"]) == 0
        assert "币安将上线" in capsys.readouterr().out
