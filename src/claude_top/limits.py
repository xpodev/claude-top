"""Usage limits and tier information."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_TIER_DISPLAY_NAMES = {
    "default_raven": "Team",
    "default": "Standard",
    "pro": "Pro",
    "enterprise": "Enterprise",
}


def get_user_tier() -> Optional[dict[str, Any]]:
    """
    Get the user's tier info from Claude Code credentials.

    Returns:
        Dictionary with tier_name and subscription_type, or None if not found.
    """
    creds_file = Path.home() / ".claude" / ".credentials.json"
    if not creds_file.exists():
        return None

    try:
        with open(creds_file) as f:
            creds = json.load(f)
        oauth = creds.get("claudeAiOauth", {})
        raw_tier = oauth.get("rateLimitTier", "default")
        return {
            "tier_name": _TIER_DISPLAY_NAMES.get(raw_tier, raw_tier.replace("_", " ").title()),
            "subscription_type": oauth.get("subscriptionType", "unknown"),
        }
    except (OSError, json.JSONDecodeError):
        return None


def _parse_countdown(resets_at: Optional[str], now: datetime) -> str:
    """Return a human-readable countdown string from a resets_at ISO timestamp."""
    if not resets_at:
        return "unknown"
    try:
        reset_time = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
        time_until = reset_time - now
        if time_until.total_seconds() <= 0:
            return "now"
        hours = int(time_until.total_seconds() // 3600)
        minutes = int((time_until.total_seconds() % 3600) // 60)
        if hours > 24:
            days = hours // 24
            return f"{days}d {hours % 24}h"
        return f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    except Exception:
        return "unknown"


def get_time_until_reset(
    first_request_time: datetime, reset_type: str = "session"
) -> dict[str, Any]:
    """
    Calculate time until the next limit reset based on first request time.

    Args:
        first_request_time: Timestamp of the first request in the period
        reset_type: Either "session" or "weekly"

    Returns:
        Dictionary with reset time and human-readable countdown
    """
    now = datetime.now(timezone.utc)

    if first_request_time.tzinfo is None:
        first_request_time = first_request_time.replace(tzinfo=timezone.utc)
    else:
        first_request_time = first_request_time.astimezone(timezone.utc)

    if reset_type == "session":
        next_reset = first_request_time + timedelta(hours=24)
    else:
        next_reset = first_request_time + timedelta(days=7)

    time_until = next_reset - now

    if time_until.total_seconds() <= 0:
        return {"reset_time": next_reset, "countdown": "now", "has_reset": True}

    hours = int(time_until.total_seconds() // 3600)
    minutes = int((time_until.total_seconds() % 3600) // 60)

    if hours > 24:
        days = hours // 24
        countdown = f"{days}d {hours % 24}h"
    elif hours > 0:
        countdown = f"{hours}h {minutes}m"
    else:
        countdown = f"{minutes}m"

    return {
        "reset_time": next_reset,
        "countdown": countdown,
        "hours_until": hours,
        "minutes_until": minutes,
        "has_reset": False,
    }


def get_usage_status(usage_data: dict[str, Any]) -> dict[str, Any]:
    """
    Get usage status with percentages sourced from the /usage API endpoint.

    Percentages come from the API's `utilization` field (0.0–1.0) so they are
    accurate regardless of tier.  Token counts shown are from local session files
    and are informational only.

    Args:
        usage_data: Formatted usage data from local session files

    Returns:
        Dictionary with usage status and API-sourced utilization percentages
    """
    from . import data as data_module

    api_data = data_module.fetch_usage_from_api()
    tier_info = get_user_tier()

    tier_name = tier_info["tier_name"] if tier_info else "Unknown"
    subscription_type = tier_info["subscription_type"] if tier_info else "unknown"

    if not api_data:
        return {
            "tier_available": False,
            "tier_name": tier_name,
            "subscription_type": subscription_type,
        }

    now = datetime.now(timezone.utc)
    five_hour = api_data.get("five_hour", {})
    seven_day = api_data.get("seven_day", {})

    return {
        "tier_available": True,
        "tier_name": tier_name,
        "subscription_type": subscription_type,
        # 5-hour session window
        "daily_tokens_percentage": float(five_hour.get("utilization", 0.0)),
        "daily_reset_countdown": _parse_countdown(five_hour.get("resets_at"), now),
        # 7-day rolling window
        "weekly_tokens_percentage": float(seven_day.get("utilization", 0.0)),
        "weekly_reset_countdown": _parse_countdown(seven_day.get("resets_at"), now),
    }
