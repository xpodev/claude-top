"""Fetch usage data from local Claude Code session files."""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

# Cache for API usage data to avoid excessive calls
_api_usage_cache: Optional[dict[str, Any]] = None
_api_cache_timestamp: Optional[datetime] = None

# Rough blended token pricing used for informational estimates only.
ESTIMATED_PRICING_USD_PER_MILLION = {
    "input_tokens": 3.00,
    "output_tokens": 15.00,
    "cache_creation_tokens": 3.75,
    "cache_read_tokens": 0.30,
}


class UsageDataError(Exception):
    """Error reading usage data from local files."""

    pass


def _parse_timestamp_utc(timestamp: str) -> Optional[datetime]:
    """Parse ISO-like timestamp string to UTC datetime."""
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def _infer_project_name(event: dict[str, Any]) -> str:
    """Infer project name from common event fields."""
    candidates = [
        event.get("project"),
        event.get("projectName"),
        event.get("cwd"),
        event.get("projectPath"),
        event.get("path"),
    ]

    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        value = candidate.strip().rstrip("/\\")
        if "/" in value or "\\" in value:
            try:
                name = Path(value).name
                if name:
                    return name
            except Exception:
                pass
        return value

    return "unknown"


def get_claude_sessions_dir() -> Path:
    """Get the Claude Code sessions directory."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        raise UsageDataError("Claude Code directory not found at ~/.claude")
    return claude_dir


def get_access_token() -> Optional[str]:
    """
    Get OAuth access token from Claude credentials.

    Returns:
        Access token string, or None if not found
    """
    try:
        claude_dir = get_claude_sessions_dir()
        creds_file = claude_dir / ".credentials.json"
        if not creds_file.exists():
            return None

        with open(creds_file, encoding="utf-8") as f:
            creds = json.load(f)
            return creds.get("claudeAiOauth", {}).get("accessToken")
    except Exception:
        return None


def fetch_usage_from_api(force_refresh: bool = False) -> Optional[dict[str, Any]]:
    """
    Fetch usage data from Anthropic OAuth API.

    Uses cached data unless force_refresh=True or a reset has occurred.

    Args:
        force_refresh: Force a new API call even if cache is valid

    Returns:
        API usage data with limits and reset times, or None if unavailable
    """
    global _api_usage_cache, _api_cache_timestamp

    # Check if we should use cached data
    if not force_refresh and _api_usage_cache is not None:
        # Check if any limit has reset
        now = datetime.now(timezone.utc)
        reset_occurred = False

        for limit_data in _api_usage_cache.values():
            if isinstance(limit_data, dict) and "resets_at" in limit_data:
                try:
                    reset_time = datetime.fromisoformat(
                        limit_data["resets_at"].replace("Z", "+00:00")
                    )
                    if now >= reset_time:
                        reset_occurred = True
                        break
                except (ValueError, AttributeError):
                    pass

        # Return cached data if no reset has occurred
        if not reset_occurred:
            return _api_usage_cache

    # Need to fetch fresh data
    token = get_access_token()
    if not token:
        return _api_usage_cache  # Return stale cache if available

    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        }

        response = requests.get(
            "https://api.anthropic.com/api/oauth/usage", headers=headers, timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            # Parse limits from API response
            limits = {}
            for key, value in data.items():
                if value is None:
                    continue
                if not isinstance(value, dict):
                    continue
                if "utilization" not in value or value["utilization"] is None:
                    continue

                limits[key] = {
                    "utilization": float(value["utilization"]),
                    "resets_at": value.get("resets_at"),
                }

            # Update cache
            if limits:
                _api_usage_cache = limits
                _api_cache_timestamp = datetime.now(timezone.utc)
                return limits

    except (requests.RequestException, ValueError, KeyError):
        # Log error but don't crash - return stale cache if available
        pass

    return _api_usage_cache  # Return stale cache on error


def get_cached_api_data() -> Optional[dict[str, Any]]:
    """Return the in-memory API usage cache without making a new API call."""
    return _api_usage_cache


def fetch_api_data_fresh() -> Optional[dict[str, Any]]:
    """Force a fresh API call, update the cache, and return the result."""
    return fetch_usage_from_api(force_refresh=True)


def read_session_files() -> list[dict[str, Any]]:
    """
    Read all Claude Code session JSONL files.

    Returns:
        List of session events/messages
    """
    claude_dir = get_claude_sessions_dir()
    projects_dir = claude_dir / "projects"

    if not projects_dir.exists():
        return []

    events: list[dict[str, Any]] = []

    # Read all .jsonl files in projects directory
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        try:
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            event = json.loads(line)
                            events.append(event)
                        except json.JSONDecodeError:
                            continue
        except OSError:
            continue

    return events


def extract_usage_from_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract usage statistics from session events.

    Args:
        events: List of session events from JSONL files

    Returns:
        Dictionary with usage statistics
    """
    usage_data: dict[str, Any] = {
        "total_requests": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_creation_tokens": 0,
        "total_cache_read_tokens": 0,
        "models": defaultdict(
            lambda: {
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
            }
        ),
        "projects": defaultdict(
            lambda: {
                "requests": 0,
                "tokens": 0,
            }
        ),
        "daily_trend": defaultdict(lambda: {"tokens": 0, "requests": 0}),
        "weekly_comparison": {
            "this_week_tokens": 0,
            "last_week_tokens": 0,
            "this_week_requests": 0,
            "last_week_requests": 0,
        },
        "sessions": set(),
        "first_message": None,
        "last_message": None,
    }

    now_utc = datetime.now(timezone.utc)

    for event in events:
        # Track session IDs
        if "sessionId" in event:
            usage_data["sessions"].add(event["sessionId"])

        # Track timestamps
        timestamp = event.get("timestamp")
        if timestamp:
            if not usage_data["first_message"] or timestamp < usage_data["first_message"]:
                usage_data["first_message"] = timestamp
            if not usage_data["last_message"] or timestamp > usage_data["last_message"]:
                usage_data["last_message"] = timestamp

        # Extract usage from API responses
        if event.get("type") == "assistant":
            usage_data["total_requests"] += 1

            # Extract usage information
            usage = event.get("message", {}).get("usage", {})
            model = event.get("message", {}).get("model", "unknown")

            if usage:
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                total_event_tokens = input_tokens + output_tokens + cache_creation + cache_read

                # Update totals
                usage_data["total_input_tokens"] += input_tokens
                usage_data["total_output_tokens"] += output_tokens
                usage_data["total_cache_creation_tokens"] += cache_creation
                usage_data["total_cache_read_tokens"] += cache_read

                # Update per-model stats
                usage_data["models"][model]["requests"] += 1
                usage_data["models"][model]["input_tokens"] += input_tokens
                usage_data["models"][model]["output_tokens"] += output_tokens
                usage_data["models"][model]["cache_creation_tokens"] += cache_creation
                usage_data["models"][model]["cache_read_tokens"] += cache_read

                # Project breakdown
                project_name = _infer_project_name(event)
                usage_data["projects"][project_name]["requests"] += 1
                usage_data["projects"][project_name]["tokens"] += total_event_tokens

                # Trends and historical comparison
                event_dt = _parse_timestamp_utc(event.get("timestamp"))
                if event_dt:
                    day_key = event_dt.date().isoformat()
                    usage_data["daily_trend"][day_key]["tokens"] += total_event_tokens
                    usage_data["daily_trend"][day_key]["requests"] += 1

                    age_days = (now_utc.date() - event_dt.date()).days
                    if 0 <= age_days <= 6:
                        usage_data["weekly_comparison"]["this_week_tokens"] += total_event_tokens
                        usage_data["weekly_comparison"]["this_week_requests"] += 1
                    elif 7 <= age_days <= 13:
                        usage_data["weekly_comparison"]["last_week_tokens"] += total_event_tokens
                        usage_data["weekly_comparison"]["last_week_requests"] += 1

    # Convert sets to counts
    usage_data["total_sessions"] = len(usage_data["sessions"])
    del usage_data["sessions"]

    # Convert defaultdict to regular dict
    usage_data["models"] = dict(usage_data["models"])
    usage_data["projects"] = dict(usage_data["projects"])

    # Normalize daily trend to last 7 days with explicit zeros
    trend_list: list[dict[str, Any]] = []
    for i in range(6, -1, -1):
        day = (now_utc - timedelta(days=i)).date().isoformat()
        day_data = usage_data["daily_trend"].get(day, {"tokens": 0, "requests": 0})
        trend_list.append(
            {
                "date": day,
                "tokens": day_data["tokens"],
                "requests": day_data["requests"],
            }
        )
    usage_data["daily_trend"] = trend_list

    # Add percentage deltas for week-over-week comparison
    this_week_tokens = usage_data["weekly_comparison"]["this_week_tokens"]
    last_week_tokens = usage_data["weekly_comparison"]["last_week_tokens"]
    if last_week_tokens > 0:
        token_delta_pct = ((this_week_tokens - last_week_tokens) / last_week_tokens) * 100
    elif this_week_tokens > 0:
        token_delta_pct = 100.0
    else:
        token_delta_pct = 0.0
    usage_data["weekly_comparison"]["token_delta_pct"] = token_delta_pct

    return usage_data


def fetch_usage() -> dict[str, Any]:
    """
    Fetch usage data from local Claude Code session files.

    Returns:
        Dictionary with usage statistics

    Raises:
        UsageDataError: If unable to read session data
    """
    try:
        events = read_session_files()

        if not events:
            raise UsageDataError(
                "No Claude Code session data found.\n"
                "Make sure you've used Claude Code and have active sessions."
            )

        usage_data = extract_usage_from_events(events)

        return usage_data

    except UsageDataError:
        raise
    except Exception as e:
        raise UsageDataError(f"Error reading session data: {str(e)}")


def format_usage_data(data: dict[str, Any]) -> dict[str, Any]:
    """
    Format usage data for display.

    Args:
        data: Raw usage data

    Returns:
        Formatted usage data with standardized keys
    """
    total_tokens = data.get("total_input_tokens", 0) + data.get("total_output_tokens", 0)

    formatted: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "total_tokens": total_tokens,
        "total_input_tokens": data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
        "total_cache_creation_tokens": data.get("total_cache_creation_tokens", 0),
        "total_cache_read_tokens": data.get("total_cache_read_tokens", 0),
        "total_requests": data.get("total_requests", 0),
        "total_sessions": data.get("total_sessions", 0),
        "models": {},
        "projects": {},
        "daily_trend": data.get("daily_trend", []),
        "weekly_comparison": data.get("weekly_comparison", {}),
        "period": None,
    }

    # Format model data
    for model, stats in data.get("models", {}).items():
        model_tokens = stats.get("input_tokens", 0) + stats.get("output_tokens", 0)
        formatted["models"][model] = {
            "tokens": model_tokens,
            "input_tokens": stats.get("input_tokens", 0),
            "output_tokens": stats.get("output_tokens", 0),
            "cache_creation_tokens": stats.get("cache_creation_tokens", 0),
            "cache_read_tokens": stats.get("cache_read_tokens", 0),
            "requests": stats.get("requests", 0),
        }

    # Format period if available
    if data.get("first_message") and data.get("last_message"):
        try:
            first = datetime.fromisoformat(data["first_message"].replace("Z", "+00:00"))
            last = datetime.fromisoformat(data["last_message"].replace("Z", "+00:00"))
            formatted["period"] = {
                "start": first.strftime("%Y-%m-%d %H:%M:%S"),
                "end": last.strftime("%Y-%m-%d %H:%M:%S"),
            }
        except (ValueError, AttributeError):
            pass

    # Project breakdown, sorted by total tokens
    projects = data.get("projects", {})
    if isinstance(projects, dict):
        formatted["projects"] = dict(
            sorted(
                projects.items(),
                key=lambda item: item[1].get("tokens", 0),
                reverse=True,
            )
        )

    # Derived insights (information-only metrics)
    total_requests = formatted.get("total_requests", 0)
    avg_tokens_per_request = total_tokens / (total_requests or 1)

    input_cost = (formatted["total_input_tokens"] / 1_000_000) * ESTIMATED_PRICING_USD_PER_MILLION[
        "input_tokens"
    ]
    output_cost = (
        formatted["total_output_tokens"] / 1_000_000
    ) * ESTIMATED_PRICING_USD_PER_MILLION["output_tokens"]
    cache_write_cost = (
        formatted["total_cache_creation_tokens"] / 1_000_000
    ) * ESTIMATED_PRICING_USD_PER_MILLION["cache_creation_tokens"]
    cache_read_cost = (
        formatted["total_cache_read_tokens"] / 1_000_000
    ) * ESTIMATED_PRICING_USD_PER_MILLION["cache_read_tokens"]

    formatted["insights"] = {
        "avg_tokens_per_request": avg_tokens_per_request,
        "cost_estimate_usd": input_cost + output_cost + cache_write_cost + cache_read_cost,
        "cost_breakdown_usd": {
            "input": input_cost,
            "output": output_cost,
            "cache_write": cache_write_cost,
            "cache_read": cache_read_cost,
        },
    }

    return formatted
