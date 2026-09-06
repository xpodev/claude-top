"""Tests for the CLI entry point and its flags."""

import json
import time

import pytest
from typer.testing import CliRunner

from claude_top import cli, data

runner = CliRunner()

SAMPLE_RAW = {
    "total_input_tokens": 1000,
    "total_output_tokens": 500,
    "total_cache_creation_tokens": 100,
    "total_cache_read_tokens": 200,
    "total_fable_tokens": 0,
    "total_requests": 10,
    "total_sessions": 2,
    "models": {
        "claude-sonnet-4-6": {
            "input_tokens": 800,
            "output_tokens": 400,
            "requests": 8,
            "cache_creation_tokens": 50,
            "cache_read_tokens": 150,
        }
    },
    "projects": {},
    "daily_trend": [],
    "weekly_comparison": {},
    "first_message": None,
    "last_message": None,
}


class DummyClaudeTop:
    """Stand-in for the Textual TUI so tests never actually launch it."""

    instances: list["DummyClaudeTop"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.run_called = False
        DummyClaudeTop.instances.append(self)

    def run(self):
        self.run_called = True


@pytest.fixture(autouse=True)
def _reset_dummy_tui():
    DummyClaudeTop.instances.clear()
    yield
    DummyClaudeTop.instances.clear()


@pytest.fixture(autouse=True)
def _stub_data_and_auth(monkeypatch):
    """Avoid any real filesystem/network access: no local session files,
    no OAuth credentials, no outbound API calls."""
    monkeypatch.setattr(cli.auth, "is_token_expired", lambda: False)
    monkeypatch.setattr(cli.data, "fetch_api_data_fresh", lambda: None)
    monkeypatch.setattr(cli.data, "fetch_usage", lambda: dict(SAMPLE_RAW))
    monkeypatch.setattr(cli, "ClaudeTop", DummyClaudeTop)


def test_once_prints_table_and_exits():
    """--once must print the usage table once and exit, not launch the TUI."""
    result = runner.invoke(cli.app, ["--once"])

    assert result.exit_code == 0
    assert "Total Tokens:" in result.output
    assert "1,500" in result.output
    assert not DummyClaudeTop.instances, "TUI must not be launched when --once is passed"


def test_once_takes_precedence_over_watch():
    """--once combined with --watch must still print once and return promptly,
    not enter the Live-refresh loop."""
    start = time.monotonic()
    result = runner.invoke(cli.app, ["--once", "--watch", "5"])
    elapsed = time.monotonic() - start

    assert result.exit_code == 0
    assert elapsed < 2, "--once must not wait for the watch interval"
    assert not DummyClaudeTop.instances


def test_json_flag_prints_json_and_exits():
    result = runner.invoke(cli.app, ["--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_tokens"] == 1500
    assert payload["total_requests"] == 10
    assert not DummyClaudeTop.instances


def test_json_takes_precedence_over_no_ui():
    """--json together with --no-ui should still emit JSON, not the Rich table."""
    result = runner.invoke(cli.app, ["--json", "--no-ui"])

    assert result.exit_code == 0
    json.loads(result.output)  # raises if not valid JSON


def test_no_ui_with_once_prints_table():
    result = runner.invoke(cli.app, ["--no-ui", "--once"])

    assert result.exit_code == 0
    assert "Total Tokens:" in result.output
    assert not DummyClaudeTop.instances


def test_detailed_flag_shows_extra_stats():
    result = runner.invoke(cli.app, ["--once", "--detailed"])

    assert result.exit_code == 0
    assert "Cache Statistics" in result.output
    assert "Avg tokens/request" in result.output
    assert "Estimated cost" in result.output


def test_default_invocation_launches_tui_and_returns():
    """With no flags at all, the TUI is launched instead of printing a table."""
    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0
    assert len(DummyClaudeTop.instances) == 1
    instance = DummyClaudeTop.instances[0]
    assert instance.run_called
    assert instance.kwargs["watch_interval"] == 1
    assert "Total Tokens:" not in result.output


def test_no_ui_alone_defaults_to_watching(monkeypatch):
    """--no-ui without --once/--watch still enters the watch loop (default
    behavior), but should stop as soon as the loop body raises KeyboardInterrupt
    on the first iteration -- this just proves the watch path is reachable and
    doesn't hang forever with no exit path."""

    call_count = {"n": 0}

    def fake_sleep(_seconds):
        call_count["n"] += 1
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", fake_sleep)

    result = runner.invoke(cli.app, ["--no-ui"])

    assert result.exit_code == 0
    assert call_count["n"] == 1
    assert "Total Tokens:" in result.output


def test_usage_data_error_exits_with_code_1(monkeypatch):
    def raise_error():
        raise data.UsageDataError("No Claude Code session data found.")

    monkeypatch.setattr(cli.data, "fetch_usage", raise_error)

    result = runner.invoke(cli.app, ["--once"])

    assert result.exit_code == 1
    assert "Error" in result.output


def test_expired_token_warns_but_still_prints(monkeypatch):
    monkeypatch.setattr(cli.auth, "is_token_expired", lambda: True)
    monkeypatch.setattr(cli.auth, "try_launch_claude_for_refresh", lambda: False)

    result = runner.invoke(cli.app, ["--once"])

    assert result.exit_code == 0
    assert "Token still expired" in result.output
    assert "Total Tokens:" in result.output
