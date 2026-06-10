"""CLI entry point using Typer."""

import time
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from . import data, limits
from .ui import ClaudeTop

app = typer.Typer(
    name="claude-top",
    help="View Claude Code usage statistics from local session files",
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


def print_usage_table(usage_data: dict, show_detailed: bool = False) -> None:
    """Print usage data as a Rich table."""
    from rich.progress import BarColumn, Progress, TextColumn

    def compact_trend(values: list[int]) -> str:
        """Create a compact ASCII trend line."""
        if not values:
            return ""
        levels = " .:-=+*#%@"
        max_val = max(values)
        if max_val <= 0:
            return " " * len(values)
        chars = []
        for value in values:
            idx = int((value / max_val) * (len(levels) - 1))
            chars.append(levels[idx])
        return "".join(chars)

    # Determine usage status early so we can color alerts in normal view
    status = limits.get_usage_status(usage_data)
    total_color = "#E8956D"
    if status.get("tier_available"):
        daily_pct = status.get("daily_tokens_percentage", 0)
        total_color = "#52A66A" if daily_pct < 70 else "#E8A84D" if daily_pct < 90 else "#D96B6B"

    # Summary (color total metrics by usage)
    console.print(
        f"\n[bold #CC785C]Total Tokens:[/bold #CC785C] [{total_color}]{usage_data['total_tokens']:,}[/{total_color}]"
    )
    console.print(
        f"[bold #CC785C]Total Requests:[/bold #CC785C] [{total_color}]{usage_data['total_requests']:,}[/{total_color}]"
    )

    # Explicit alerts in normal view for threshold visibility.
    if status.get("tier_available"):
        daily_pct = status.get("daily_tokens_percentage", 0)
        weekly_pct = status.get("weekly_tokens_percentage", 0)
        if daily_pct >= 90 or weekly_pct >= 90:
            console.print(
                "[bold #D96B6B]ALERT:[/bold #D96B6B] Usage is above 90% of one or more limits."
            )
        elif daily_pct >= 80 or weekly_pct >= 80:
            console.print(
                "[bold #E8A84D]Warning:[/bold #E8A84D] Usage is above 80% of one or more limits."
            )

    # Cache stats and extra details when in detailed view
    if show_detailed:
        cache_read = usage_data.get("total_cache_read_tokens", 0)
        cache_creation = usage_data.get("total_cache_creation_tokens", 0)
        if cache_read > 0 or cache_creation > 0:
            console.print("\n[bold #CC785C]Cache Statistics:[/bold #CC785C]")
            if cache_creation > 0:
                console.print(
                    f"  [dim]Cache Writes:[/dim] [#E8A84D]{cache_creation:,}[/#E8A84D] tokens"
                )
            if cache_read > 0:
                console.print(
                    f"  [dim]Cache Reads:[/dim]  [#52A66A]{cache_read:,}[/#52A66A] tokens [dim italic](saved!)[/dim italic]"
                )

        total_cache_ops = cache_read + cache_creation
        if total_cache_ops > 0:
            hit_rate = (cache_read / total_cache_ops) * 100
            console.print(
                f"[bold #CC785C]Cache hit rate:[/bold #CC785C] [#52A66A]{hit_rate:.1f}%[/#52A66A]"
            )

        insights = usage_data.get("insights", {})
        total_reqs = usage_data.get("total_requests", 0) or 1
        avg_tokens = insights.get(
            "avg_tokens_per_request", usage_data.get("total_tokens", 0) / total_reqs
        )
        console.print(
            f"[bold #CC785C]Avg tokens/request:[/bold #CC785C] [#E8956D]{avg_tokens:.1f}[/#E8956D]"
        )

        # Informational cost estimate
        total_cost = insights.get("cost_estimate_usd", 0.0)
        cost_breakdown = insights.get("cost_breakdown_usd", {})
        console.print(
            f"[bold #CC785C]Estimated cost:[/bold #CC785C] [#E8956D]${total_cost:.2f}[/#E8956D] [dim](approx)[/dim]"
        )
        if cost_breakdown:
            console.print(
                f"  [dim]input ${cost_breakdown.get('input', 0.0):.2f} | output ${cost_breakdown.get('output', 0.0):.2f} | cache write ${cost_breakdown.get('cache_write', 0.0):.2f} | cache read ${cost_breakdown.get('cache_read', 0.0):.2f}[/dim]"
            )

        # Usage trends over last 7 days
        trend = usage_data.get("daily_trend", [])
        if trend:
            token_values = [int(day.get("tokens", 0)) for day in trend]
            trend_line = compact_trend(token_values)
            console.print(
                f"[bold #CC785C]7-day trend:[/bold #CC785C] [#E8956D]{trend_line}[/#E8956D]"
            )

        # Historical comparison: this week vs last week
        comparison = usage_data.get("weekly_comparison", {})
        if comparison:
            delta = comparison.get("token_delta_pct", 0.0)
            delta_color = "#52A66A" if delta <= 0 else "#E8A84D" if delta < 20 else "#D96B6B"
            console.print(
                "[bold #CC785C]Week-over-week:[/bold #CC785C] "
                f"{comparison.get('this_week_tokens', 0):,} vs {comparison.get('last_week_tokens', 0):,} tokens "
                f"([{delta_color}]{delta:+.1f}%[/{delta_color}])"
            )

        # Breakdown by project (top 5)
        projects = usage_data.get("projects", {})
        if projects:
            console.print("[bold #CC785C]Top projects:[/bold #CC785C]")
            top_projects = sorted(
                projects.items(), key=lambda it: it[1].get("tokens", 0), reverse=True
            )[:5]
            for project_name, project_stats in top_projects:
                console.print(
                    f"  [#E8956D]{project_name}[/#E8956D] - {project_stats.get('tokens', 0):,} tokens ({project_stats.get('requests', 0):,} req)"
                )

        # Top 3 models
        models = usage_data.get("models", {})
        if models:
            top = sorted(models.items(), key=lambda it: it[1].get("tokens", 0), reverse=True)[:3]
            console.print()
            for m, s in top:
                console.print(f"  [#E8956D]{m}[/#E8956D] — {s.get('tokens',0):,} tokens")

    # At this point 'status' was computed earlier
    if status.get("tier_available"):
        console.print(
            f"\n[bold #E8956D]Tier:[/bold #E8956D] {status['tier_name']} ({status['subscription_type']})"
        )

        # Session usage (5 hour window)
        daily_countdown = status.get("daily_reset_countdown", "unknown")
        if daily_countdown and daily_countdown != "unknown":
            console.print(
                f"\n[bold #CC785C]Current Session (5hr)[/bold #CC785C] [dim](resets in [italic]{daily_countdown}[/italic])[/dim]"
            )
        else:
            console.print("\n[bold #CC785C]Current Session (5hr)[/bold #CC785C]")
        daily_pct = status["daily_tokens_percentage"]
        daily_color = "#52A66A" if daily_pct < 70 else "#E8A84D" if daily_pct < 90 else "#D96B6B"

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(complete_style=daily_color, finished_style=daily_color),
            TextColumn("{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            progress.add_task(
                f"Tokens: {status['daily_tokens_used']:,} / {status['daily_tokens_limit']:,}",
                total=100,
                completed=daily_pct,
            )

        console.print(
            f"  {status['daily_tokens_used']:,} / {status['daily_tokens_limit']:,} tokens [dim]({status['daily_tokens_remaining']:,} remaining)[/dim]"
        )

        # Weekly usage
        weekly_countdown = status.get("weekly_reset_countdown", "unknown")
        if weekly_countdown and weekly_countdown != "unknown":
            console.print(
                f"\n[bold #CC785C]Weekly Session[/bold #CC785C] [dim](resets in [italic]{weekly_countdown}[/italic])[/dim]"
            )
        else:
            console.print("\n[bold #CC785C]Weekly Session[/bold #CC785C]")
        weekly_pct = status["weekly_tokens_percentage"]
        weekly_color = "#52A66A" if weekly_pct < 70 else "#E8A84D" if weekly_pct < 90 else "#D96B6B"

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(complete_style=weekly_color, finished_style=weekly_color),
            TextColumn("{task.percentage:>3.0f}%"),
            console=console,
        ) as progress:
            progress.add_task(
                f"Tokens: {status['weekly_tokens_used']:,} / {status['weekly_tokens_limit']:,}",
                total=100,
                completed=weekly_pct,
            )

        console.print(
            f"  {status['weekly_tokens_used']:,} / {status['weekly_tokens_limit']:,} tokens [dim]({status['weekly_tokens_remaining']:,} remaining)[/dim]"
        )

    if usage_data.get("period"):
        period = usage_data["period"]
        if isinstance(period, dict):
            start_str = period.get("start", "N/A")
            end_str = period.get("end", "N/A")

            try:
                from dateutil import parser

                start_dt = parser.parse(start_str)
                end_dt = parser.parse(end_str)

                # Convert to local timezone
                start_local = start_dt.astimezone()
                end_local = end_dt.astimezone()

                console.print(
                    f"\n[bold #CC785C]Period:[/bold #CC785C] {start_local.strftime('%Y-%m-%d %H:%M:%S')} to {end_local.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            except Exception:
                # Fallback if timezone conversion fails
                console.print(f"\n[bold #CC785C]Period:[/bold #CC785C] {start_str} to {end_str}")

    # Models table
    if usage_data.get("models"):
        console.print()
        table = Table(title="Usage by Model", border_style="#CC785C")
        table.add_column("Model", style="#E8956D")
        table.add_column("Tokens", justify="right", style="#CC785C")
        table.add_column("Requests", justify="right", style="#52A66A")

        for model, stats in usage_data["models"].items():
            table.add_row(
                model,
                f"{stats.get('tokens', 0):,}",
                f"{stats.get('requests', 0):,}",
            )

        console.print(table)
        console.print()


@app.command()
def main(
    once: Annotated[
        bool, typer.Option("--once", help="Display usage once and exit (default is to watch)")
    ] = False,
    no_ui: Annotated[
        bool, typer.Option("--no-ui", help="Print usage table instead of TUI")
    ] = False,
    json: Annotated[bool, typer.Option("--json", help="Print raw JSON and exit")] = False,
    detailed: Annotated[
        bool, typer.Option("--detailed", help="Show detailed information (cache & model stats)")
    ] = False,
    watch: Annotated[
        Optional[int],
        typer.Option(
            "--watch",
            help="Local refresh interval in seconds (reads session files only, default: 1)",
            metavar="N",
        ),
    ] = None,
    api_refresh: Annotated[
        Optional[int],
        typer.Option(
            "--api-refresh",
            help="How often to fetch utilization percentages from the API, in minutes (default: 1)",
            metavar="MINUTES",
        ),
    ] = None,
) -> None:
    """
    View Claude Code usage statistics from local session files.

    By default, launches an interactive TUI with auto-refresh.
    """
    # Determine watch interval
    if once:
        watch_interval = None
    elif watch is not None:
        watch_interval = watch
    else:
        watch_interval = 1  # Default 1 second

    api_refresh_minutes = api_refresh if api_refresh is not None else 1

    # Launch TUI if no flags
    if not no_ui and not json:
        app_instance = ClaudeTop(
            watch_interval=watch_interval,
            api_refresh_minutes=api_refresh_minutes,
            show_detailed=detailed,
        )
        app_instance.run()
        return

    # Fetch data for --no-ui or --json modes
    try:
        # Always fetch fresh API data on startup
        data.fetch_api_data_fresh()
        raw_data = data.fetch_usage()
        usage_data = data.format_usage_data(raw_data)

        # Handle --json output
        if json:
            console.print_json(data=usage_data)
            return

        # Handle --no-ui output
        if watch_interval:
            # Live refresh mode — local reads every watch_interval, API every api_refresh_minutes
            api_refresh_secs = api_refresh_minutes * 60
            last_api_refresh = time.time()

            with Live(console=console, refresh_per_second=0.5) as live:
                while True:
                    try:
                        now = time.time()
                        if now - last_api_refresh >= api_refresh_secs:
                            data.fetch_api_data_fresh()
                            last_api_refresh = now
                        raw_data = data.fetch_usage()
                        usage_data = data.format_usage_data(raw_data)
                        live.console.clear()
                        print_usage_table(usage_data, show_detailed=detailed)
                        time.sleep(watch_interval)
                    except KeyboardInterrupt:
                        break
        else:
            # Single display
            print_usage_table(usage_data, show_detailed=detailed)

    except data.UsageDataError as e:
        err_console.print(f"[bold red]Error:[/bold red] {str(e)}")
        raise typer.Exit(1)


def cli() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    cli()
