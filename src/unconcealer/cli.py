"""Command-line interface for Unconcealer."""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

app = typer.Typer(
    name="unconcealer",
    help="AI-powered embedded systems debugger using Claude and QEMU/GDB",
)
console = Console()


def _get_provider(
    provider_type: str,
    base_url: Optional[str],
    model: Optional[str],
    api_key: Optional[str],
):
    """Create a model provider based on configuration."""
    if provider_type == "openai":
        from unconcealer.agent.providers import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            base_url=base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            model=model or os.environ.get("OPENAI_MODEL", "gpt-4"),
        )
    # Default: use Claude (provider=None uses claude-agent-sdk)
    return None


async def _run_debug_session(
    elf_path: Path,
    machine: str,
    cpu: str,
    gdb_port: int,
    provider,
    model: Optional[str],
) -> None:
    """Run an interactive debug session."""
    from unconcealer.core.session import DebugSession
    from unconcealer.agent.orchestrator import AgentOrchestrator
    from unconcealer.tools.qemu_control import QEMUConfig

    config = QEMUConfig(
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
    )

    console.print(Panel(
        f"[bold]ELF:[/bold] {elf_path}\n"
        f"[bold]Machine:[/bold] {machine}\n"
        f"[bold]CPU:[/bold] {cpu}\n"
        f"[bold]GDB Port:[/bold] {gdb_port}",
        title="[bold blue]Unconcealer Debug Session[/bold blue]",
    ))

    try:
        async with DebugSession(
            elf_path=str(elf_path),
            qemu_config=config,
        ) as session:
            orchestrator = AgentOrchestrator(
                session=session,
                provider=provider,
                model=model,
            )

            console.print("[green]Session started. Type your questions or commands.[/green]")
            console.print("[dim]Type 'exit' or 'quit' to end the session.[/dim]\n")

            while True:
                try:
                    user_input = Prompt.ask("[bold cyan]>[/bold cyan]")
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Exiting...[/yellow]")
                    break

                if user_input.lower() in ("exit", "quit", "q"):
                    console.print("[yellow]Ending session...[/yellow]")
                    break

                if not user_input.strip():
                    continue

                # Special commands
                if user_input.startswith("/"):
                    await _handle_command(user_input, orchestrator, session)
                    continue

                # Stream response from LLM
                console.print()
                try:
                    response_text = []
                    async for chunk in orchestrator.query_stream(user_input):
                        console.print(chunk, end="")
                        response_text.append(chunk)
                    console.print("\n")

                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]\n")

    except Exception as e:
        console.print(f"[red]Failed to start session: {e}[/red]")
        raise typer.Exit(1)


async def _handle_command(cmd: str, orchestrator, session) -> None:
    """Handle special /commands."""
    parts = cmd[1:].split(maxsplit=1)
    command = parts[0].lower()

    if command == "help":
        console.print(Panel(
            "[bold]/help[/bold] - Show this help\n"
            "[bold]/regs[/bold] - Show all registers\n"
            "[bold]/mem <addr> [size][/bold] - Read memory\n"
            "[bold]/bt[/bold] - Show backtrace\n"
            "[bold]/snapshot <name>[/bold] - Save snapshot\n"
            "[bold]/restore <name>[/bold] - Restore snapshot\n"
            "[bold]/findings[/bold] - Show recorded findings\n"
            "[bold]/clear[/bold] - Clear conversation history",
            title="Commands",
        ))

    elif command == "regs":
        try:
            regs = await session.read_registers()
            console.print("[bold]Registers:[/bold]")
            for name, value in sorted(regs.items()):
                console.print(f"  {name:6} = 0x{value:08x}")
        except Exception as e:
            console.print(f"[red]Error reading registers: {e}[/red]")

    elif command == "bt":
        try:
            bt = await session.get_backtrace(10)
            console.print("[bold]Backtrace:[/bold]")
            for i, frame in enumerate(bt):
                func = frame.get("func", "??")
                addr = frame.get("addr", "??")
                console.print(f"  #{i} {addr} in {func}")
        except Exception as e:
            console.print(f"[red]Error getting backtrace: {e}[/red]")

    elif command == "mem":
        if len(parts) < 2:
            console.print("[red]Usage: /mem <address> [size][/red]")
            return
        args = parts[1].split()
        try:
            addr = int(args[0], 0)
            size = int(args[1], 0) if len(args) > 1 else 16
            data = await session.read_memory(addr, size)
            console.print(f"[bold]Memory at 0x{addr:08x}:[/bold]")
            console.print(f"  {data.hex()}")
        except Exception as e:
            console.print(f"[red]Error reading memory: {e}[/red]")

    elif command == "snapshot":
        if len(parts) < 2:
            console.print("[red]Usage: /snapshot <name>[/red]")
            return
        name = parts[1]
        try:
            await session.qemu.save_snapshot(name)
            orchestrator.record_snapshot(name)
            console.print(f"[green]Saved snapshot: {name}[/green]")
        except Exception as e:
            console.print(f"[red]Error saving snapshot: {e}[/red]")

    elif command == "restore":
        if len(parts) < 2:
            console.print("[red]Usage: /restore <name>[/red]")
            return
        name = parts[1]
        try:
            await session.qemu.load_snapshot(name)
            console.print(f"[green]Restored snapshot: {name}[/green]")
        except Exception as e:
            console.print(f"[red]Error restoring snapshot: {e}[/red]")

    elif command == "findings":
        findings = orchestrator.findings
        if not findings:
            console.print("[dim]No findings recorded yet.[/dim]")
        else:
            console.print("[bold]Findings:[/bold]")
            for f in findings:
                console.print(f"  [{f.severity}] {f.description}")

    elif command == "clear":
        orchestrator.clear_history()
        console.print("[green]Conversation history cleared.[/green]")

    else:
        console.print(f"[red]Unknown command: {command}. Type /help for help.[/red]")


@app.command()
def debug(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    machine: str = typer.Option("lm3s6965evb", help="QEMU machine type"),
    cpu: str = typer.Option("cortex-m3", help="CPU type"),
    gdb_port: int = typer.Option(1234, help="GDB server port"),
    provider: str = typer.Option("claude", help="LLM provider (claude, openai)"),
    model: Optional[str] = typer.Option(None, help="Model name"),
    base_url: Optional[str] = typer.Option(None, envvar="OPENAI_BASE_URL", help="API base URL (for openai provider)"),
    api_key: Optional[str] = typer.Option(None, envvar="OPENAI_API_KEY", help="API key (for openai provider)"),
) -> None:
    """Start an interactive debugging session with AI assistance."""
    if not elf.exists():
        console.print(f"[red]Error: ELF file not found: {elf}[/red]")
        raise typer.Exit(1)

    llm_provider = _get_provider(provider, base_url, model, api_key)

    asyncio.run(_run_debug_session(
        elf_path=elf,
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
        provider=llm_provider,
        model=model,
    ))


@app.command()
def analyze(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    fault: str = typer.Option("hardfault", help="Fault type to analyze"),
    provider: str = typer.Option("claude", help="LLM provider (claude, openai)"),
    model: Optional[str] = typer.Option(None, help="Model name"),
) -> None:
    """Analyze a crash dump or fault condition."""
    if not elf.exists():
        console.print(f"[red]Error: ELF file not found: {elf}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]ELF:[/bold] {elf}\n"
        f"[bold]Fault Type:[/bold] {fault}",
        title="[bold blue]Fault Analysis[/bold blue]",
    ))

    # Build the analysis prompt
    prompts = {
        "hardfault": "Analyze this firmware for a HardFault. Check the fault status registers (CFSR, HFSR, MMFAR, BFAR) and determine the cause.",
        "busfault": "Analyze this firmware for a BusFault. Check memory access patterns and the BFAR register.",
        "memfault": "Analyze this firmware for a MemManage fault. Check the MPU configuration and MMFAR.",
        "usagefault": "Analyze this firmware for a UsageFault. Check for undefined instructions, unaligned access, or division by zero.",
        "stackoverflow": "Analyze this firmware for stack overflow. Check SP against stack boundaries and look for deep recursion.",
    }

    prompt = prompts.get(fault.lower(), f"Analyze this firmware for: {fault}")

    async def run_analysis():
        from unconcealer.core.session import DebugSession
        from unconcealer.agent.orchestrator import AgentOrchestrator

        llm_provider = _get_provider(provider, None, model, None)

        async with DebugSession(elf_path=str(elf)) as session:
            orchestrator = AgentOrchestrator(
                session=session,
                provider=llm_provider,
                model=model,
            )

            console.print("[bold]Analysis:[/bold]\n")
            async for chunk in orchestrator.query_stream(prompt):
                console.print(chunk, end="")
            console.print("\n")

            if orchestrator.findings:
                console.print("[bold]Findings:[/bold]")
                for f in orchestrator.findings:
                    console.print(f"  [{f.severity}] {f.description}")

    try:
        asyncio.run(run_analysis())
    except Exception as e:
        console.print(f"[red]Analysis failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from unconcealer import __version__
    console.print(f"[bold blue]Unconcealer[/bold blue] v{__version__}")


if __name__ == "__main__":
    app()
