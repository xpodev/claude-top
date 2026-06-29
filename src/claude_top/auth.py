"""Authentication and credential management using system keyring."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import keyring

SERVICE_NAME = "claude-top"
USERNAME = "api-key"


def get_claude_code_credentials() -> Optional[dict[str, Any]]:
    """
    Read credentials from Claude Code's .credentials.json file.

    Returns:
        Dictionary with OAuth credentials if found, None otherwise
    """
    # Try common locations for .claude directory
    possible_paths = [
        Path.home() / ".claude" / ".credentials.json",
        Path("~/.claude/.credentials.json").expanduser(),
    ]

    for creds_path in possible_paths:
        if creds_path.exists():
            try:
                with open(creds_path) as f:
                    data = json.load(f)

                if "claudeAiOauth" in data:
                    oauth = data["claudeAiOauth"]

                    # Check if token is expired
                    expires_at = oauth.get("expiresAt", 0)
                    if expires_at > datetime.now().timestamp() * 1000:
                        return {
                            "access_token": oauth.get("accessToken"),
                            "refresh_token": oauth.get("refreshToken"),
                            "expires_at": expires_at,
                            "source": "claude_code",
                        }
            except (OSError, json.JSONDecodeError):
                continue

    return None


def get_api_key() -> Optional[str]:
    """
    Retrieve API key/token with the following priority:
    1. Claude Code OAuth token (if available and not expired)
    2. Manually stored API key in keyring

    Returns:
        API key or OAuth access token
    """
    # First, try Claude Code credentials
    claude_creds = get_claude_code_credentials()
    if claude_creds and claude_creds.get("access_token"):
        return claude_creds["access_token"]

    # Fall back to keyring
    return keyring.get_password(SERVICE_NAME, USERNAME)


def save_api_key(api_key: str) -> None:
    """Save API key to system keyring."""
    keyring.set_password(SERVICE_NAME, USERNAME, api_key)


def delete_api_key() -> None:
    """Remove API key from system keyring."""
    try:
        keyring.delete_password(SERVICE_NAME, USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def is_authenticated() -> bool:
    """Check if user is authenticated (via Claude Code or keyring)."""
    return get_api_key() is not None


def get_auth_source() -> str:
    """
    Determine the source of authentication.

    Returns:
        "claude_code", "keyring", or "none"
    """
    claude_creds = get_claude_code_credentials()
    if claude_creds and claude_creds.get("access_token"):
        return "claude_code"

    if keyring.get_password(SERVICE_NAME, USERNAME):
        return "keyring"

    return "none"


def is_token_expired() -> bool:
    """Return True if the Claude OAuth access token is missing or expired."""
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if not creds_path.exists():
        return True
    try:
        with open(creds_path) as f:
            creds = json.load(f)
        oauth = creds.get("claudeAiOauth", {})
        if not oauth.get("accessToken"):
            return True
        expires_at = oauth.get("expiresAt", 0)
        return expires_at <= datetime.now().timestamp() * 1000
    except Exception:
        return True


def try_launch_claude_for_refresh() -> bool:
    """
    Launch the claude CLI in the background so it can refresh the OAuth token.

    Claude Code handles the refresh-token flow internally on startup; running
    it briefly updates ~/.claude/.credentials.json so claude-top can read the
    new access token.

    Returns True if the process was launched, False if claude was not found.
    """
    import shutil

    claude_path = shutil.which("claude")
    if not claude_path:
        return False

    try:
        popen_kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # Prevent a console window from flashing up on Windows
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            popen_kwargs["shell"] = True
            cmd: Any = "claude --no-ui --once"
        else:
            cmd = [claude_path, "--no-ui", "--once"]

        proc = subprocess.Popen(cmd, **popen_kwargs)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
        return True
    except Exception:
        return False
