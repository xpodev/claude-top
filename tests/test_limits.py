"""Tests for limits module."""

import pytest
from claude_top import limits


def test_calculate_usage_percentage():
    """Test usage percentage calculation."""
    assert limits.calculate_usage_percentage(0, 100) == 0.0
    assert limits.calculate_usage_percentage(50, 100) == 50.0
    assert limits.calculate_usage_percentage(100, 100) == 100.0
    assert limits.calculate_usage_percentage(150, 100) == 100.0  # Capped at 100
    assert limits.calculate_usage_percentage(50, 0) == 0.0  # Handle division by zero


def test_get_usage_status():
    """Test usage status calculation."""
    usage_data = {
        "total_tokens": 1000000,
        "total_requests": 100,
    }

    status = limits.get_usage_status(usage_data)

    assert "tier_available" in status
    assert "daily_tokens_used" in status
    assert "weekly_tokens_used" in status
    assert status["daily_tokens_used"] == 1000000
    assert status["weekly_tokens_used"] == 1000000
