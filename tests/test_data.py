"""Tests for data module."""

from claude_top import data


def test_format_usage_data():
    """Test usage data formatting."""
    raw_data = {
        "total_input_tokens": 1000,
        "total_output_tokens": 500,
        "total_cache_creation_tokens": 100,
        "total_cache_read_tokens": 200,
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
    }

    formatted = data.format_usage_data(raw_data)

    assert formatted["total_tokens"] == 1500
    assert formatted["total_input_tokens"] == 1000
    assert formatted["total_output_tokens"] == 500
    assert formatted["total_requests"] == 10
    assert formatted["total_sessions"] == 2
    assert "claude-sonnet-4-6" in formatted["models"]
    assert formatted["models"]["claude-sonnet-4-6"]["tokens"] == 1200


def test_extract_usage_from_events():
    """Test extracting usage from session events."""
    events = [
        {
            "type": "assistant",
            "sessionId": "test-session-1",
            "timestamp": "2024-01-01T10:00:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 10,
                    "cache_read_input_tokens": 20,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "test-session-1",
            "timestamp": "2024-01-01T11:00:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 200,
                    "output_tokens": 100,
                },
            },
        },
    ]

    usage = data.extract_usage_from_events(events)

    assert usage["total_requests"] == 2
    assert usage["total_input_tokens"] == 300
    assert usage["total_output_tokens"] == 150
    assert usage["total_cache_creation_tokens"] == 10
    assert usage["total_cache_read_tokens"] == 20
    assert usage["total_sessions"] == 1
    assert "claude-sonnet-4-6" in usage["models"]
    assert usage["models"]["claude-sonnet-4-6"]["requests"] == 2


def test_is_fable_model():
    """Fable models are matched by substring, case-insensitively."""
    assert data._is_fable_model("claude-fable-5")
    assert data._is_fable_model("Claude-Fable-5")
    assert not data._is_fable_model("claude-sonnet-4-6")


def test_slim_event_drops_message_content_keeps_usage_fields():
    """Only fields the aggregation code reads survive slimming; bulky message
    content (text/tool_use/tool_result payloads) must not be retained."""
    raw_event = {
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": "2024-01-01T10:00:00Z",
        "cwd": "/home/user/my-project",
        "uuid": "unused-field",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [{"type": "text", "text": "a" * 10_000}],
            "id": "unused-field",
        },
    }

    slim = data._slim_event(raw_event)

    assert slim == {
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": "2024-01-01T10:00:00Z",
        "cwd": "/home/user/my-project",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def test_slim_event_non_assistant_has_no_message_key():
    """Non-assistant events (user/tool_result/etc.) never carry a message
    field forward since only 'assistant' events are aggregated for usage."""
    raw_event = {
        "type": "user",
        "sessionId": "s1",
        "timestamp": "2024-01-01T10:00:00Z",
        "message": {"content": "large user prompt text"},
    }

    slim = data._slim_event(raw_event)

    assert "message" not in slim
    assert slim["type"] == "user"


def test_extract_usage_tracks_fable_tokens():
    """Fable events contribute to total_fable_tokens and this week's fable bucket."""
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = [
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": now_iso,
            "message": {
                "model": "claude-fable-5",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": now_iso,
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        },
    ]

    usage = data.extract_usage_from_events(events)

    assert usage["total_fable_tokens"] == 150
    assert usage["weekly_comparison"]["fable_this_week_tokens"] == 150
    assert usage["weekly_comparison"]["this_week_tokens"] == 450
