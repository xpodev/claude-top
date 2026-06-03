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
