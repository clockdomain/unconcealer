"""Command-line interface for Unconcealer."""

import typer
from rich.console import Console
from pathlib import Path
from typing import Optional

app = typer.Typer(
    name="unconcealer",
    help="AI-powered embedded systems debugger using Claude and QEMU/GDB",
)
console = Console()


@app.command()
def debug(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    target: str = typer.Option("cortex-m4", help="Target architecture"),
    qemu_args: Optional[str] = typer.Option(None, help="Additional QEMU arguments"),
) -> None:
    """Start an interactive debugging session."""
    console.print("[bold blue]Unconcealer v0.1.0[/bold blue]")
    console.print(f"Loading: {elf}")
    console.print(f"Target: {target}")
    # TODO: Initialize debug session


@app.command()
def analyze(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    fault: str = typer.Option("hardfault", help="Fault type to analyze"),
) -> None:
    """Analyze a crash dump or fault condition."""
    console.print(f"Analyzing {fault} in {elf}")
    # TODO: Implement fault analysis


@app.command()
def version() -> None:
    """Show version information."""
    from unconcealer import __version__
    console.print(f"Unconcealer v{__version__}")


if __name__ == "__main__":
    app()
