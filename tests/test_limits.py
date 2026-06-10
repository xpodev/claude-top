"""Tests for limits module."""

from unittest.mock import patch

from claude_top import limits


def test_tier_display_names():
    """Known tier keys map to readable names."""
    assert limits._TIER_DISPLAY_NAMES["default_raven"] == "Team"
    assert limits._TIER_DISPLAY_NAMES["default"] == "Standard"
    assert limits._TIER_DISPLAY_NAMES["pro"] == "Pro"


def test_get_usage_status_no_api_data():
    """Returns tier_available=False when API is unavailable."""
    with (
        patch("claude_top.data.get_cached_api_data", return_value=None),
        patch("claude_top.limits.get_user_tier", return_value=None),
    ):
        status = limits.get_usage_status({})
        assert status["tier_available"] is False


def test_get_usage_status_with_api_data():
    """Percentages come directly from API utilization; no token counts."""
    api_data = {
        "five_hour": {"utilization": 35.0, "resets_at": None},
        "seven_day": {"utilization": 12.5, "resets_at": None},
    }
    with (
        patch("claude_top.data.get_cached_api_data", return_value=api_data),
        patch(
            "claude_top.limits.get_user_tier",
            return_value={"tier_name": "Team", "subscription_type": "team"},
        ),
    ):
        status = limits.get_usage_status({"total_tokens": 1000000})

    assert status["tier_available"] is True
    assert status["daily_tokens_percentage"] == 35.0
    assert status["weekly_tokens_percentage"] == 12.5
    assert "daily_tokens_used" not in status
    assert "weekly_tokens_used" not in status


def test_parse_countdown_unknown_when_none():
    """None resets_at returns 'unknown'."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    assert limits._parse_countdown(None, now) == "unknown"


def test_parse_countdown_now_when_past():
    """Expired reset time returns 'now'."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert limits._parse_countdown(past, now) == "now"
