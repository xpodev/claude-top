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


def test_get_fable_status_no_fable_usage():
    """No Fable tokens used means the feature is not reported as available."""
    usage_data = {"weekly_comparison": {"fable_this_week_tokens": 0, "this_week_tokens": 1000}}
    status = {"tier_available": True, "weekly_tokens_percentage": 10.0}
    result = limits.get_fable_status(usage_data, status)
    assert result == {"fable_available": False}


def test_get_fable_status_without_api_percentage():
    """Fable tokens exist but no API percentage is available: report tokens, no estimate."""
    usage_data = {"weekly_comparison": {"fable_this_week_tokens": 500, "this_week_tokens": 2000}}
    status = {"tier_available": False}
    result = limits.get_fable_status(usage_data, status)
    assert result["fable_available"] is True
    assert result["fable_week_tokens"] == 500
    assert result["estimated_subcap_pct"] is None


def test_get_fable_status_estimates_subcap_pct():
    """Estimated % is derived from local Fable tokens and the API's overall weekly %."""
    # 1000 tokens used this week == 10% of the weekly limit -> implied budget = 10000.
    # 50% sub-cap = 5000 tokens. 500 Fable tokens -> 10% of the sub-cap.
    usage_data = {"weekly_comparison": {"fable_this_week_tokens": 500, "this_week_tokens": 1000}}
    status = {"tier_available": True, "weekly_tokens_percentage": 10.0}
    result = limits.get_fable_status(usage_data, status)
    assert result["fable_available"] is True
    assert result["fable_week_tokens"] == 500
    assert result["estimated_subcap_pct"] == 10.0


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
