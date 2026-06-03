# claude-top

![Claude Top screenshot](images/claude-top.png)

A CLI + TUI utility for inspecting Claude Code usage from local session files.

`claude-top` reads your local Claude history (`~/.claude/projects/**/*.jsonl`), aggregates token/request metrics, and presents them in either:

- an interactive Textual dashboard (default),
- a Rich terminal table (`--no-ui`), or
- JSON (`--json`).

## What it shows

- Total input/output tokens and request count
- Per-model usage breakdown
- Optional detailed stats (`--detailed`):
   - cache reads/writes and hit rate
   - average tokens per request
   - estimated cost (informational)
   - 7-day trend sparkline
   - week-over-week comparison
   - top projects by token usage
- Tier-aware usage bars and warnings (80%/90%) when tier metadata is available

## Requirements

- Python 3.9+
- Existing Claude Code data in `~/.claude/projects`

Notes:
- No setup is required to read local usage files.
- If `~/.claude/.credentials.json` is present with a valid OAuth token, `claude-top` also tries to fetch usage window reset metadata from Anthropic OAuth usage API for better countdowns.

## Installation

### Run without install (uvx)

```bash
uvx claude-top
```

### Install globally (uv)

```bash
uv tool install claude-top
```

### Install with pip

```bash
pip install claude-top
```

### From source

```bash
git clone https://github.com/xpodev/claude-top.git
cd claude-top
uv pip install -e .
```

## Usage

```bash
# Launch TUI (auto-refresh by default)
claude-top

# Print terminal table once and exit
claude-top --no-ui --once

# Print terminal table with refresh
claude-top --no-ui --watch 5

# Print JSON once and exit
claude-top --json

# Include detailed analytics
claude-top --detailed
```

### CLI options

- `--once`: Display once and exit.
- `--no-ui`: Use table output instead of the TUI.
- `--json`: Print JSON output and exit.
- `--detailed`: Include detailed analytics.
- `--watch N`: Refresh interval in seconds (default: 1 when not using `--once`).

### TUI keybindings

- `r`: Refresh now
- `q`: Quit

## How data is calculated

- Scans all JSONL events in `~/.claude/projects` recursively.
- Counts each `assistant` event as one request.
- Aggregates token fields from each assistant message usage payload:
   - `input_tokens`
   - `output_tokens`
   - `cache_creation_input_tokens`
   - `cache_read_input_tokens`
- Derives project names from common event path/project fields.
- Builds last-7-day trend and week-over-week token comparison from timestamps.

## Troubleshooting

### "No Claude Code session data found"

`claude-top` only reads local Claude session files. Make sure:

1. Claude Code has been used on this machine.
2. `~/.claude/projects` exists and contains `.jsonl` files.

### Tier/reset countdown is missing

Tier and reset countdown information depends on OAuth metadata. If unavailable:

- ensure `~/.claude/.credentials.json` exists,
- ensure the OAuth token is valid,
- check network access to Anthropic API.

The tool still works with local usage data even if tier/reset metadata cannot be fetched.

## Development

```bash
# Clone repository
git clone https://github.com/xpodev/claude-top.git
cd claude-top

# Install with development dependencies
uv pip install -e ".[dev]"

# Run tests
uv run pytest -q
```

## License

MIT
