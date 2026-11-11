"""Command-line interface for agent-rewind."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

try:
    from src.storage.engine import SnapshotEngine
    from src.watcher.daemon import RewindWatcher
except ImportError:
    from storage.engine import SnapshotEngine  # type: ignore[no-redef]
    from watcher.daemon import RewindWatcher  # type: ignore[no-redef]

app = typer.Typer(
    name="agent-rewind",
    help="Git-less time-machine and sandbox for AI agents.",
    no_args_is_help=True,
)
console = Console(highlight=False)


def format_size(bytes_num: int) -> str:
    """Format bytes into human-readable size."""
    size = float(bytes_num)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} TB"


@app.command(name="snap", help="Create a manual checkpoint snapshot.")
def snap(
    message: str = typer.Argument("auto snapshot", help="Snapshot description or message"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project root directory"),
) -> None:
    """Create a manual checkpoint snapshot."""
    engine = SnapshotEngine(root_dir=path)
    snap_id = engine.create_snapshot(message=message)
    snap_data = engine.get_snapshot(snap_id)

    files_count = snap_data["total_files"] if snap_data else 0
    total_size = snap_data["total_size"] if snap_data else 0

    console.print(
        f"[bold green]✓ Snapshot created:[/bold green] [bold cyan]{snap_id}[/bold cyan] "
        f"[dim]({files_count} files, {format_size(total_size)})[/dim]"
    )
    console.print(f"  [dim]Message:[/dim] {message}")


@app.command(name="list", help="List all recorded snapshots.")
def list_snapshots(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project root directory"),
) -> None:
    """Show history table of snapshots."""
    engine = SnapshotEngine(root_dir=path)
    snapshots = engine.list_snapshots()

    if not snapshots:
        console.print("[yellow]No snapshots found. Run [bold]agent-rewind snap[/bold] to create one.[/yellow]")
        return

    table = Table(
        title="📦 agent-rewind snapshot history",
        box=box.ROUNDED,
        header_style="bold magenta",
        title_style="bold cyan",
    )
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Timestamp", style="dim")
    table.add_column("Message", style="white")
    table.add_column("Files", justify="right", style="green")
    table.add_column("Affected", justify="right", style="yellow")
    table.add_column("Size", justify="right", style="blue")

    for s in snapshots:
        created_at = s.get("created_at", "")[:19].replace("T", " ")
        table.add_row(
            s.get("id", ""),
            created_at,
            s.get("message", ""),
            str(s.get("total_files", 0)),
            str(s.get("affected_files", 0)),
            format_size(s.get("total_size", 0)),
        )

    console.print(table)


@app.command(name="rollback", help="Safely roll back codebase to a snapshot.")
def rollback(
    snapshot_id: str = typer.Argument(..., help="Snapshot ID or unique prefix to restore"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project root directory"),
) -> None:
    """Safe rollback of the codebase with confirmation."""
    engine = SnapshotEngine(root_dir=path)
    snap = engine.get_snapshot(snapshot_id)

    if not snap:
        console.print(f"[bold red]Error:[/bold red] Snapshot '[cyan]{snapshot_id}[/cyan]' not found.")
        raise typer.Exit(code=1)

    target_id = snap["id"]
    if not yes:
        confirm = typer.confirm(
            f"⚠️  Roll back to snapshot '{target_id}' ({snap.get('message', '')})? "
            "Modified files will be overwritten and untracked files deleted."
        )
        if not confirm:
            console.print("[yellow]Rollback aborted.[/yellow]")
            raise typer.Exit(code=0)

    try:
        success = engine.restore_snapshot(target_id)
    except Exception as e:
        console.print(f"[bold red]Rollback error:[/bold red] {e}")
        raise typer.Exit(code=1)

    if success:
        console.print(
            f"[bold green]✓ Successfully restored workspace to snapshot [cyan]{target_id}[/cyan]![/bold green]"
        )
    else:
        console.print(f"[bold red]✗ Failed to restore snapshot [cyan]{target_id}[/cyan][/bold red]")
        raise typer.Exit(code=1)


@app.command(name="diff", help="Colorized line-by-line diff against snapshot.")
def diff(
    snapshot_id: str = typer.Argument(..., help="Snapshot ID or prefix to compare against"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project root directory"),
) -> None:
    """Show colored line-by-line diff between current workspace and snapshot."""
    engine = SnapshotEngine(root_dir=path)
    snap = engine.get_snapshot(snapshot_id)

    if not snap:
        console.print(f"[bold red]Error:[/bold red] Snapshot '[cyan]{snapshot_id}[/cyan]' not found.")
        raise typer.Exit(code=1)

    diffs = engine.compute_diff(snap["id"])
    if not diffs:
        console.print(
            f"[bold green]✓ Current workspace is identical to snapshot [cyan]{snap['id']}[/cyan].[/bold green]"
        )
        return

    console.print(
        f"[bold cyan]Showing changes between workspace and snapshot [magenta]{snap['id']}[/magenta]:[/bold cyan]\n"
    )

    for file_path, lines in diffs.items():
        console.rule(f"[bold blue]{file_path}[/bold blue]", align="left")
        for line in lines:
            if line.startswith("+++"):
                console.print(f"[bold green]{line}[/bold green]")
            elif line.startswith("---"):
                console.print(f"[bold red]{line}[/bold red]")
            elif line.startswith("+"):
                console.print(f"[green]{line}[/green]")
            elif line.startswith("-"):
                console.print(f"[red]{line}[/red]")
            elif line.startswith("@@"):
                console.print(f"[cyan]{line}[/cyan]")
            else:
                console.print(f"[dim]{line}[/dim]")
        console.print()


@app.command(name="watch", help="Run background daemon monitoring agent edits.")
def watch(
    debounce: float = typer.Option(1.5, "--debounce", "-d", help="Debounce pause in seconds (1.0 - 2.0s)"),
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project root directory"),
) -> None:
    """Run daemon monitoring project changes with debouncing."""
    engine = SnapshotEngine(root_dir=path)
    debounce_ms = int(debounce * 1000)

    console.print(
        Panel(
            f"[bold green]👁 agent-rewind daemon active[/bold green]\n"
            f"[dim]Watching workspace: [bold]{engine.root_dir}[/bold]\n"
            f"Debounce: {debounce:.1f}s | Press [bold red]Ctrl+C[/bold red] to stop[/dim]",
            box=box.ROUNDED,
        )
    )

    def on_snapshot(snap_id: str, message: str, count: int) -> None:
        console.print(
            f"[bold green]📸 Snapshot captured:[/bold green] [bold cyan]{snap_id}[/bold cyan] "
            f"[dim]({message})[/dim]"
        )

    watcher = RewindWatcher(
        engine=engine,
        debounce_ms=debounce_ms,
        on_snapshot=on_snapshot,
    )

    try:
        asyncio.run(watcher.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Watcher stopped.[/yellow]")


def main() -> None:
    """Entry point for CLI script."""
    app()


if __name__ == "__main__":
    main()
