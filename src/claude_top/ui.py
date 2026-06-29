"""Textual TUI for displaying Claude usage statistics."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static

from . import auth, data, limits

_SETTINGS_FILE = Path.home() / ".claude" / "claude_top_settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(settings: dict) -> None:
    try:
        _SETTINGS_FILE.write_text(json.dumps(settings), encoding="utf-8")
    except Exception:
        pass


class UsageDisplay(Vertical):
    """Widget to display summary usage statistics."""

    usage_data: reactive[Optional[dict[str, Any]]] = reactive(None)

    def __init__(self, show_detailed: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.show_detailed = show_detailed

    def watch_usage_data(self, new_data: Optional[dict[str, Any]]) -> None:
        """React to usage data changes."""
        if new_data:
            self.refresh_display(new_data)

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Static("Loading...", id="usage-content")

    def refresh_display(self, usage: dict[str, Any]) -> None:
        """Update the display with new usage data."""

        lines = []

        # Token expiry warning (shown at the top when the OAuth token is stale)
        token_warning = usage.get("_token_warning", "")
        if token_warning == "open_claude":
            lines.append(
                Text(
                    "⚠ Token expired — launched Claude Code in the background to refresh.",
                    style="bold #E8A84D",
                )
            )
            lines.append(
                Text(
                    "  If rate limits are not showing, open Claude Code manually.",
                    style="dim #E8A84D",
                )
            )
            lines.append(Text(""))
        elif token_warning == "no_claude":
            lines.append(
                Text(
                    "⚠ Token expired — open Claude Code to refresh the OAuth token.",
                    style="bold #E8A84D",
                )
            )
            lines.append(
                Text(
                    "  Rate limit data is unavailable until the token is refreshed.",
                    style="dim #E8A84D",
                )
            )
            lines.append(Text(""))

        # Compute status early for alert coloring in all views.
        status = limits.get_usage_status(usage)
        total_color = "#E8956D"
        if status.get("tier_available"):
            daily_pct = status.get("daily_tokens_percentage", 0)
            total_color = (
                "#52A66A" if daily_pct < 70 else "#E8A84D" if daily_pct < 90 else "#D96B6B"
            )

        # Basic stats
        lines.append(
            Text.assemble(
                ("Total Tokens:   ", "bold #CC785C"),
                (f"{usage['total_tokens']:,}", total_color),
            )
        )
        lines.append(
            Text.assemble(
                ("Total Requests: ", "bold #CC785C"),
                (f"{usage['total_requests']:,}", total_color),
            )
        )

        # Token type breakdown (always visible)
        input_tokens = usage.get("total_input_tokens", 0)
        output_tokens = usage.get("total_output_tokens", 0)
        cache_creation = usage.get("total_cache_creation_tokens", 0)
        cache_read = usage.get("total_cache_read_tokens", 0)
        total_all = input_tokens + output_tokens + cache_creation + cache_read

        if total_all > 0:

            def _pct(n: int) -> str:
                return f"{n / total_all * 100:5.1f}%" if total_all > 0 else "  0.0%"

            lines.append(Text(""))
            lines.append(Text("Token Breakdown:", style="bold #CC785C"))
            lines.append(
                Text.assemble(
                    ("  Input        ", "dim"),
                    (f"{input_tokens:>10,}", "#E8956D"),
                    (f"  {_pct(input_tokens)}", "dim"),
                )
            )
            lines.append(
                Text.assemble(
                    ("  Output       ", "dim"),
                    (f"{output_tokens:>10,}", "#52A66A"),
                    (f"  {_pct(output_tokens)}", "dim"),
                )
            )
            if cache_read > 0:
                lines.append(
                    Text.assemble(
                        ("  Cache Reads  ", "dim"),
                        (f"{cache_read:>10,}", "#52A66A"),
                        (f"  {_pct(cache_read)}", "dim"),
                        ("  ← saved", "dim italic"),
                    )
                )
            if cache_creation > 0:
                lines.append(
                    Text.assemble(
                        ("  Cache Writes ", "dim"),
                        (f"{cache_creation:>10,}", "#E8A84D"),
                        (f"  {_pct(cache_creation)}", "dim"),
                    )
                )

        if status.get("tier_available"):
            daily_pct = status.get("daily_tokens_percentage", 0)
            weekly_pct = status.get("weekly_tokens_percentage", 0)
            if daily_pct >= 90 or weekly_pct >= 90:
                lines.append(
                    Text("ALERT: usage is above 90% of one or more limits.", style="bold #D96B6B")
                )
            elif daily_pct >= 80 or weekly_pct >= 80:
                lines.append(
                    Text("Warning: usage is above 80% of one or more limits.", style="bold #E8A84D")
                )
        # Cache statistics and extra details when in detailed view
        if self.show_detailed:
            cache_read = usage.get("total_cache_read_tokens", 0)
            cache_creation = usage.get("total_cache_creation_tokens", 0)
            if cache_read > 0 or cache_creation > 0:
                lines.append(Text(""))
                lines.append(Text("Cache Statistics:", style="bold #CC785C"))
                if cache_creation > 0:
                    lines.append(
                        Text.assemble(
                            ("  Cache Writes: ", "dim"),
                            (f"{cache_creation:,} tokens", "#E8A84D"),
                        )
                    )
                if cache_read > 0:
                    lines.append(
                        Text.assemble(
                            ("  Cache Reads:  ", "dim"),
                            (f"{cache_read:,} tokens", "#52A66A"),
                            (" (saved!)", "dim italic"),
                        )
                    )

            # Additional detailed stats: cache hit rate and average tokens/request
            total_cache_ops = cache_read + cache_creation
            if total_cache_ops > 0:
                hit_rate = (cache_read / total_cache_ops) * 100
                lines.append(
                    Text.assemble(
                        ("Cache hit rate: ", "bold #CC785C"), (f"{hit_rate:.1f}%", "#52A66A")
                    )
                )

            # Average tokens per request
            insights = usage.get("insights", {})
            total_reqs = usage.get("total_requests", 0) or 1
            avg_tokens = insights.get(
                "avg_tokens_per_request", usage.get("total_tokens", 0) / total_reqs
            )
            lines.append(
                Text.assemble(
                    ("Avg tokens/request: ", "bold #CC785C"), (f"{avg_tokens:.1f}", "#E8956D")
                )
            )

            # Cost estimate breakdown
            cost_total = insights.get("cost_estimate_usd", 0.0)
            cost_breakdown = insights.get("cost_breakdown_usd", {})
            lines.append(
                Text.assemble(
                    ("Estimated cost: ", "bold #CC785C"),
                    (f"${cost_total:.2f}", "#E8956D"),
                    (" (approx)", "dim"),
                )
            )
            if cost_breakdown:
                lines.append(
                    Text(
                        "  "
                        f"input ${cost_breakdown.get('input', 0.0):.2f} | "
                        f"output ${cost_breakdown.get('output', 0.0):.2f} | "
                        f"cache write ${cost_breakdown.get('cache_write', 0.0):.2f} | "
                        f"cache read ${cost_breakdown.get('cache_read', 0.0):.2f}",
                        style="dim",
                    )
                )

            # 7-day trend (ASCII sparkline)
            trend = usage.get("daily_trend", [])
            if trend:
                values = [int(day.get("tokens", 0)) for day in trend]
                levels = " .:-=+*#%@"
                max_val = max(values) if values else 0
                if max_val > 0:
                    line = "".join(levels[int((v / max_val) * (len(levels) - 1))] for v in values)
                else:
                    line = " " * len(values)
                lines.append(Text.assemble(("7-day trend: ", "bold #CC785C"), (line, "#E8956D")))

            # Historical comparison (this week vs last week)
            comparison = usage.get("weekly_comparison", {})
            if comparison:
                delta = comparison.get("token_delta_pct", 0.0)
                delta_color = "#52A66A" if delta <= 0 else "#E8A84D" if delta < 20 else "#D96B6B"
                lines.append(
                    Text.assemble(
                        ("Week-over-week: ", "bold #CC785C"),
                        (
                            f"{comparison.get('this_week_tokens', 0):,} vs {comparison.get('last_week_tokens', 0):,} tokens ",
                            "",
                        ),
                        (f"({delta:+.1f}%)", delta_color),
                    )
                )

            # Top projects by usage
            projects = usage.get("projects", {})
            if projects:
                lines.append(Text("Top projects:", style="bold #CC785C"))
                top_projects = sorted(
                    projects.items(), key=lambda it: it[1].get("tokens", 0), reverse=True
                )[:5]
                for project_name, project_stats in top_projects:
                    lines.append(
                        Text.assemble(
                            (f"  {project_name}", "#E8956D"),
                            (
                                f" - {project_stats.get('tokens', 0):,} tokens ({project_stats.get('requests', 0):,} req)",
                                "dim",
                            ),
                        )
                    )

            # Show top 3 models by tokens
            models = usage.get("models", {})
            if models:
                top = sorted(models.items(), key=lambda it: it[1].get("tokens", 0), reverse=True)[
                    :3
                ]
                lines.append(Text(""))
                lines.append(Text("Top models:", style="bold #CC785C"))
                for m, s in top:
                    lines.append(
                        Text.assemble(
                            (f"  {m}", "#E8956D"), (f" — {s.get('tokens',0):,} tokens", "dim")
                        )
                    )

        # Usage status with limits
        if status.get("tier_available"):
            lines.append(Text(""))
            lines.append(
                Text.assemble(
                    ("Tier: ", "bold #CC785C"),
                    (
                        f"{status['tier_name']} ({status['subscription_type']})",
                        "#E8956D",
                    ),
                )
            )

            # Session usage (5 hour window)
            lines.append(Text(""))
            lines.append(Text("─" * 60, style="dim"))
            daily_countdown = status.get("daily_reset_countdown", "unknown")
            if daily_countdown and daily_countdown != "unknown":
                lines.append(
                    Text.assemble(
                        ("Current Session (5hr)", "bold #CC785C"),
                        (" (resets in ", "dim"),
                        (daily_countdown, "dim italic"),
                        (")", "dim"),
                    )
                )
            else:
                lines.append(Text("Current Session (5hr)", style="bold #CC785C"))
            lines.append(Text(""))

            daily_pct = status["daily_tokens_percentage"]
            daily_color = (
                "#52A66A" if daily_pct < 70 else "#E8A84D" if daily_pct < 90 else "#D96B6B"
            )

            bar_width = 50
            filled = int(bar_width * daily_pct / 100)
            bar = "█" * filled + "░" * (bar_width - filled)

            lines.append(Text.assemble((bar, daily_color), (f" {daily_pct:.1f}%", "bold")))

            # Weekly usage
            lines.append(Text(""))
            lines.append(Text("─" * 60, style="dim"))
            weekly_countdown = status.get("weekly_reset_countdown", "unknown")
            if weekly_countdown and weekly_countdown != "unknown":
                lines.append(
                    Text.assemble(
                        ("Weekly Session", "bold #CC785C"),
                        (" (resets in ", "dim"),
                        (weekly_countdown, "dim italic"),
                        (")", "dim"),
                    )
                )
            else:
                lines.append(Text("Weekly Session", style="bold #CC785C"))
            lines.append(Text(""))

            weekly_pct = status["weekly_tokens_percentage"]
            weekly_color = (
                "#52A66A" if weekly_pct < 70 else "#E8A84D" if weekly_pct < 90 else "#D96B6B"
            )

            filled = int(bar_width * weekly_pct / 100)
            bar = "█" * filled + "░" * (bar_width - filled)

            lines.append(Text.assemble((bar, weekly_color), (f" {weekly_pct:.1f}%", "bold")))

        # Period info
        if usage.get("period"):
            period = usage["period"]
            if isinstance(period, dict):
                lines.append(Text(""))
                lines.append(Text("─" * 60, style="dim"))

                # Convert UTC to local time
                start_str = period.get("start", "N/A")
                end_str = period.get("end", "N/A")

                try:
                    from dateutil import parser

                    start_dt = parser.parse(start_str)
                    end_dt = parser.parse(end_str)

                    # Convert to local timezone
                    start_local = start_dt.astimezone()
                    end_local = end_dt.astimezone()

                    lines.append(
                        Text.assemble(
                            ("Period: ", "bold #CC785C"),
                            (
                                f"{start_local.strftime('%Y-%m-%d %H:%M:%S')} to {end_local.strftime('%Y-%m-%d %H:%M:%S')}",
                                "dim",
                            ),
                        )
                    )
                except Exception:
                    # Fallback if timezone conversion fails
                    lines.append(
                        Text.assemble(
                            ("Period: ", "bold #CC785C"),
                            (f"{start_str} to {end_str}", "dim"),
                        )
                    )

        lines.append(Text(""))
        lines.append(
            Text(
                f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                style="dim italic",
            )
        )

        # Combine all lines
        combined = Text("\n").join(lines)

        # Update the content widget
        content = self.query_one("#usage-content", Static)
        content.update(combined)


class ClaudeTop(App):
    """Textual app for Claude usage statistics."""

    TITLE = "Claude Top"

    CSS = """
    Screen {
        background: $surface;
    }

    #main-content {
        height: 1fr;
        padding: 0 1;
    }

    #summary {
        width: 60%;
        height: 100%;
        padding: 1 2;
        margin: 1;
        border: round #CC785C;
        background: $panel;
        overflow-y: auto;
    }

    #models-container {
        width: 40%;
        height: 100%;
        padding: 1 2;
        margin: 1;
        border: round #CC785C;
        background: $panel;
        overflow-y: auto;
    }

    #models-title {
        margin-bottom: 1;
        text-align: center;
    }

    #models-table {
        height: auto;
        min-height: 5;
    }

    DataTable > .datatable--header {
        background: #CC785C;
        color: $text;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #E8956D;
    }

    #error {
        color: $error;
        padding: 1;
        margin: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        watch_interval: Optional[int] = 1,
        api_refresh_minutes: int = 1,
        show_detailed: bool = False,
    ):
        super().__init__()
        self.watch_interval = watch_interval
        self.api_refresh_minutes = api_refresh_minutes
        self.show_detailed = show_detailed
        self.usage_data: Optional[dict[str, Any]] = None
        self._saved_theme: Optional[str] = _load_settings().get("theme")
        self._token_warning: str = ""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
        yield Horizontal(
            UsageDisplay(show_detailed=self.show_detailed, id="summary"),
            Container(id="models-container"),
            id="main-content",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize app on mount."""
        if self._saved_theme:
            self.theme = self._saved_theme

        # Initial load: fetch API data then local files
        await self._refresh_api_and_display()

        # Local refresh timer: only reads session files, uses cached API data
        if self.watch_interval:
            self.set_interval(self.watch_interval, self._refresh_local)

        # API refresh timer: re-fetches utilization percentages from the API
        if self.api_refresh_minutes:
            self.set_interval(self.api_refresh_minutes * 60, self._refresh_api_and_display)

    async def _refresh_local(self) -> None:
        """Read local session files and update display using cached API data."""
        summary_widget = self.query_one("#summary", UsageDisplay)

        try:
            loop = asyncio.get_event_loop()
            raw_data = await loop.run_in_executor(None, data.fetch_usage)
            self.usage_data = data.format_usage_data(raw_data)
            if self._token_warning:
                self.usage_data["_token_warning"] = self._token_warning
            summary_widget.usage_data = self.usage_data
            self._update_models_table()

        except data.UsageDataError as e:
            error_msg = f"[bold red]Error:[/bold red] {str(e)}"
            if self._token_warning:
                hint = (
                    "Launched Claude Code in the background to refresh the token."
                    if self._token_warning == "open_claude"
                    else "Open Claude Code to refresh the OAuth token."
                )
                error_msg = f"[bold #E8A84D]⚠ Token expired.[/bold #E8A84D] {hint}\n\n{error_msg}"
            content = summary_widget.query_one("#usage-content", Static)
            content.update(error_msg)

    async def _refresh_api_and_display(self) -> None:
        """Fetch fresh API utilization data, then refresh the local display."""
        loop = asyncio.get_event_loop()

        if auth.is_token_expired():
            # Try to revive the token by running claude in the background
            launched = await loop.run_in_executor(None, auth.try_launch_claude_for_refresh)
            if launched:
                # Give the process time to refresh credentials
                await asyncio.sleep(5)
                self._token_warning = "" if not auth.is_token_expired() else "open_claude"
            else:
                self._token_warning = "no_claude"

            if not self._token_warning:
                # Token was successfully refreshed — proceed normally
                await loop.run_in_executor(None, data.fetch_api_data_fresh)
        else:
            self._token_warning = ""
            await loop.run_in_executor(None, data.fetch_api_data_fresh)

        await self._refresh_local()

    def _update_models_table(self) -> None:
        """Update the models usage table."""
        if not self.usage_data:
            return

        container = self.query_one("#models-container")

        # Try to get existing widgets, or create new ones
        try:
            title = container.query_one("#models-title", Static)
            table = container.query_one("#models-table", DataTable)
            table.clear()
        except Exception:
            # Widgets don't exist yet, create them
            container.remove_children()
            title = Static("[bold #CC785C]Usage by Model[/bold #CC785C]", id="models-title")
            table = DataTable(id="models-table", show_header=True, zebra_stripes=True)
            container.mount(title)
            container.mount(table)

        # Update table columns if needed
        if not table.columns:
            table.add_columns("Model", "Input", "Output", "Requests")

        # Add rows
        models = self.usage_data.get("models", {})
        if models:
            for model, stats in models.items():
                table.add_row(
                    model,
                    f"{stats.get('input_tokens', 0):,}",
                    f"{stats.get('output_tokens', 0):,}",
                    f"{stats.get('requests', 0):,}",
                )

    def watch_theme(self, theme: str) -> None:
        """Persist the theme whenever it changes."""
        settings = _load_settings()
        settings["theme"] = theme
        _save_settings(settings)

    def action_refresh(self) -> None:
        """Refresh both API data and local session files on 'r' key."""
        self.run_worker(self._refresh_api_and_display())

    def action_quit(self) -> None:
        """Quit the app."""
        self.exit()
