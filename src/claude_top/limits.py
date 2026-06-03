"""Usage limits and tier information."""

from typing import Any, Optional
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json

# Anthropic API rate limits by tier (tokens per period)
# Based on common rate limit structures
RATE_LIMITS = {
    "default_raven": {
        "name": "Team Tier",
        "requests_per_minute": 50,
        "requests_per_day": 5000,
        "tokens_per_minute": 80000,
        "tokens_per_day": 2500000,
        "tokens_per_week": 17500000,
    },
    "default": {
        "name": "Standard Tier",
        "requests_per_minute": 50,
        "requests_per_day": 5000,
        "tokens_per_minute": 40000,
        "tokens_per_day": 1000000,
        "tokens_per_week": 7000000,
    },
    "pro": {
        "name": "Pro Tier",
        "requests_per_minute": 100,
        "requests_per_day": 10000,
        "tokens_per_minute": 100000,
        "tokens_per_day": 5000000,
        "tokens_per_week": 35000000,
    },
}


def get_user_tier() -> Optional[dict[str, Any]]:
    """
    Get the user's rate limit tier from Claude Code credentials.

    Returns:
        Dictionary with tier information or None if not found
    """
    claude_dir = Path.home() / ".claude"
    creds_file = claude_dir / ".credentials.json"

    if not creds_file.exists():
        return None

    try:
        with open(creds_file, "r") as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        tier_name = oauth.get("rateLimitTier", "default")
        subscription = oauth.get("subscriptionType", "unknown")

        tier_limits = RATE_LIMITS.get(tier_name, RATE_LIMITS["default"])

        return {
            "tier_name": tier_name,
            "subscription_type": subscription,
            "limits": tier_limits,
        }
    except (json.JSONDecodeError, IOError):
        return None


def calculate_usage_percentage(used: int, limit: int) -> float:
    """Calculate usage percentage."""
    if limit == 0:
        return 0.0
    return min((used / limit) * 100, 100.0)


def get_time_until_reset(first_request_time: datetime, reset_type: str = "daily") -> dict[str, Any]:
    """
    Calculate time until the next limit reset based on first request time.

    Args:
        first_request_time: Timestamp of the first request in the period
        reset_type: Either "daily" or "weekly"

    Returns:
        Dictionary with reset time and human-readable countdown
    """
    now = datetime.now(timezone.utc)

    # Ensure first_request_time is timezone-aware
    if first_request_time.tzinfo is None:
        first_request_time = first_request_time.replace(tzinfo=timezone.utc)
    else:
        first_request_time = first_request_time.astimezone(timezone.utc)

    if reset_type == "daily":
        # Daily resets 24 hours after first request
        next_reset = first_request_time + timedelta(hours=24)
    else:  # weekly
        # Weekly resets 7 days after first request
        next_reset = first_request_time + timedelta(days=7)

    time_until = next_reset - now

    # If reset time has passed, it already reset (show as reset)
    if time_until.total_seconds() <= 0:
        return {
            "reset_time": next_reset,
            "countdown": "now",
            "has_reset": True
        }

    hours = int(time_until.total_seconds() // 3600)
    minutes = int((time_until.total_seconds() % 3600) // 60)

    # Format countdown
    if hours > 24:
        days = hours // 24
        remaining_hours = hours % 24
        countdown = f"{days}d {remaining_hours}h"
    elif hours > 0:
        countdown = f"{hours}h {minutes}m"
    else:
        countdown = f"{minutes}m"

    return {
        "reset_time": next_reset,
        "countdown": countdown,
        "hours_until": hours,
        "minutes_until": minutes,
        "has_reset": False
    }


def get_usage_status(usage_data: dict[str, Any]) -> dict[str, Any]:
    """
    Get usage status with limits and percentages.

    Args:
        usage_data: Formatted usage data

    Returns:
        Dictionary with usage status and limits
    """
    from . import data as data_module

    tier_info = get_user_tier()

    if not tier_info:
        return {
            "tier_available": False,
            "tier_name": "Unknown",
        }

    limits = tier_info["limits"]
    total_tokens = usage_data.get("total_tokens", 0)
    total_requests = usage_data.get("total_requests", 0)

    # Try to get accurate reset times from API
    api_data = data_module.fetch_usage_from_api()

    daily_reset = {"countdown": "unknown"}
    weekly_reset = {"countdown": "unknown"}

    if api_data:
        # Extract reset times from API (five_hour = session, seven_day = weekly)
        try:
            # Parse five_hour (5-hour session) reset time
            if "five_hour" in api_data and api_data["five_hour"].get("resets_at"):
                reset_time = datetime.fromisoformat(
                    api_data["five_hour"]["resets_at"].replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                time_until = reset_time - now
                if time_until.total_seconds() > 0:
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    if hours > 0:
                        daily_reset["countdown"] = f"{hours}h {minutes}m"
                    else:
                        daily_reset["countdown"] = f"{minutes}m"

            # Parse seven_day (weekly) reset time
            if "seven_day" in api_data and api_data["seven_day"].get("resets_at"):
                reset_time = datetime.fromisoformat(
                    api_data["seven_day"]["resets_at"].replace("Z", "+00:00")
                )
                now = datetime.now(timezone.utc)
                time_until = reset_time - now
                if time_until.total_seconds() > 0:
                    hours = int(time_until.total_seconds() // 3600)
                    minutes = int((time_until.total_seconds() % 3600) // 60)
                    if hours > 24:
                        days = hours // 24
                        remaining_hours = hours % 24
                        weekly_reset["countdown"] = f"{days}d {remaining_hours}h"
                    elif hours > 0:
                        weekly_reset["countdown"] = f"{hours}h {minutes}m"
                    else:
                        weekly_reset["countdown"] = f"{minutes}m"
        except:
            pass

    # Calculate session usage (all data is from current sessions)
    session_tokens_used = total_tokens
    session_requests_used = total_requests

    # For week, we'd use all the data (assuming sessions span less than a week)
    week_tokens_used = total_tokens
    week_requests_used = total_requests

    return {
        "tier_available": True,
        "tier_name": limits["name"],
        "subscription_type": tier_info["subscription_type"],

        # Daily limits
        "daily_tokens_limit": limits["tokens_per_day"],
        "daily_tokens_used": session_tokens_used,
        "daily_tokens_remaining": max(0, limits["tokens_per_day"] - session_tokens_used),
        "daily_tokens_percentage": calculate_usage_percentage(
            session_tokens_used, limits["tokens_per_day"]
        ),
        "daily_reset_countdown": daily_reset["countdown"],

        # Weekly limits
        "weekly_tokens_limit": limits["tokens_per_week"],
        "weekly_tokens_used": week_tokens_used,
        "weekly_tokens_remaining": max(0, limits["tokens_per_week"] - week_tokens_used),
        "weekly_tokens_percentage": calculate_usage_percentage(
            week_tokens_used, limits["tokens_per_week"]
        ),
        "weekly_reset_countdown": weekly_reset["countdown"],

        # Request limits
        "daily_requests_limit": limits["requests_per_day"],
        "daily_requests_used": session_requests_used,
        "daily_requests_remaining": max(0, limits["requests_per_day"] - session_requests_used),
        "daily_requests_percentage": calculate_usage_percentage(
            session_requests_used, limits["requests_per_day"]
        ),
    }
