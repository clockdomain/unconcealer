"""Command-line interface for Unconcealer."""

import asyncio
import os
import shutil
import subprocess
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


# ============================================================================
# MCP Server Command (for Claude Desktop integration)
# ============================================================================


@app.command(name="mcp-server")
def mcp_server(
    gdb_path: Optional[str] = typer.Option(
        None,
        "--gdb-path",
        help="Path to GDB executable",
        envvar="DEBUGGER_GDB_PATH",
    ),
    qemu_arm_path: Optional[str] = typer.Option(
        None,
        "--qemu-arm-path",
        help="Path to qemu-system-arm",
        envvar="DEBUGGER_QEMU_ARM_PATH",
    ),
    qemu_riscv32_path: Optional[str] = typer.Option(
        None,
        "--qemu-riscv32-path",
        help="Path to qemu-system-riscv32",
        envvar="DEBUGGER_QEMU_RISCV32_PATH",
    ),
    qemu_riscv64_path: Optional[str] = typer.Option(
        None,
        "--qemu-riscv64-path",
        help="Path to qemu-system-riscv64",
        envvar="DEBUGGER_QEMU_RISCV64_PATH",
    ),
    snapshot_dir: Optional[str] = typer.Option(
        None,
        "--snapshot-dir",
        help="Directory for storing snapshots",
        envvar="DEBUGGER_SNAPSHOT_DIR",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Run MCP server for Claude Desktop integration.

    This command starts an MCP server that communicates over stdin/stdout,
    allowing Claude Desktop to use the debugger tools.

    Configure in Claude Desktop's config file:

        {
          "mcpServers": {
            "embedded-debugger": {
              "command": "unconcealer",
              "args": ["mcp-server"]
            }
          }
        }
    """
    from unconcealer.mcp import run_stdio_server

    asyncio.run(
        run_stdio_server(
            gdb_path=gdb_path,
            qemu_arm_path=qemu_arm_path,
            qemu_riscv32_path=qemu_riscv32_path,
            qemu_riscv64_path=qemu_riscv64_path,
            snapshot_dir=snapshot_dir,
            verbose=verbose,
        )
    )


# ============================================================================
# Provider Configuration
# ============================================================================


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


# ============================================================================
# Shell Command (headless interactive mode)
# ============================================================================


async def _handle_shell_command(cmd: str, session) -> bool:
    """Handle shell commands. Returns False if should exit."""
    cmd = cmd.strip()

    if not cmd:
        return True

    if cmd in ("exit", "quit", "q"):
        return False

    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    args_str = parts[1] if len(parts) > 1 else ""

    try:
        if command in ("help", "?"):
            console.print(Panel(
                "[bold]Session:[/bold]\n"
                "  exit, quit, q     - Exit shell\n\n"
                "[bold]Registers:[/bold]\n"
                "  regs              - Show all registers\n"
                "  reg <name>        - Show single register\n\n"
                "[bold]Memory:[/bold]\n"
                "  mem <addr> [len]  - Read memory (hex or symbol)\n"
                "  write <addr> <hex> - Write memory\n\n"
                "[bold]Execution:[/bold]\n"
                "  c, continue       - Continue execution\n"
                "  s, step           - Single step\n"
                "  n, next           - Step over\n"
                "  halt              - Halt execution\n"
                "  reset             - Reset target\n\n"
                "[bold]Breakpoints:[/bold]\n"
                "  b, break <loc>    - Set breakpoint\n"
                "  del <num>         - Delete breakpoint\n\n"
                "[bold]Analysis:[/bold]\n"
                "  bt                - Backtrace\n"
                "  p, print <expr>   - Evaluate expression\n"
                "  fault             - Show fault registers\n\n"
                "[bold]Snapshots:[/bold]\n"
                "  snap <name>       - Save snapshot\n"
                "  restore <name>    - Load snapshot",
                title="Commands",
            ))

        elif command == "regs":
            regs = await session.read_registers()
            for name, value in sorted(regs.items()):
                console.print(f"  {name:6} = 0x{value:08x}")

        elif command == "reg":
            if not args_str:
                console.print("[red]Usage: reg <name>[/red]")
            else:
                value = await session.read_register(args_str)
                console.print(f"  {args_str} = 0x{value:08x}")

        elif command == "mem":
            if not args_str:
                console.print("[red]Usage: mem <address> [length][/red]")
            else:
                mem_args = args_str.split()
                addr_str = mem_args[0]
                length = int(mem_args[1], 0) if len(mem_args) > 1 else 64

                if addr_str.startswith("0x") or addr_str.startswith("0X"):
                    addr = int(addr_str, 16)
                else:
                    result = await session.evaluate(f"&{addr_str}")
                    addr = int(result.split()[0], 0)

                data = await session.read_memory(addr, length)
                for i in range(0, len(data), 16):
                    chunk = data[i:i + 16]
                    hex_part = " ".join(f"{b:02x}" for b in chunk)
                    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                    console.print(f"  0x{addr + i:08x}: {hex_part:<48} {ascii_part}")

        elif command == "write":
            write_args = args_str.split(maxsplit=1)
            if len(write_args) < 2:
                console.print("[red]Usage: write <address> <hex_data>[/red]")
            else:
                addr_str, hex_data = write_args
                addr = int(addr_str, 0)
                data = bytes.fromhex(hex_data.replace(" ", ""))
                success = await session.write_memory(addr, data)
                if success:
                    console.print(f"[green]Wrote {len(data)} bytes to 0x{addr:08x}[/green]")
                else:
                    console.print("[red]Write failed[/red]")

        elif command in ("c", "continue"):
            console.print("[dim]Continuing...[/dim]")
            stop = await session.continue_execution()
            console.print(f"Stopped: {stop.reason.value} at 0x{stop.address:08x}")
            if stop.signal_name:
                console.print(f"  Signal: {stop.signal_name}")

        elif command in ("s", "step"):
            stop = await session.step()
            console.print(f"Stepped to 0x{stop.address:08x}")

        elif command in ("n", "next"):
            stop = await session.step_over()
            console.print(f"Stepped to 0x{stop.address:08x}")

        elif command == "halt":
            await session.halt()
            console.print("Halted")

        elif command == "reset":
            success = await session.reset()
            if success:
                console.print("Target reset")
            else:
                console.print("[red]Reset failed[/red]")

        elif command in ("b", "break"):
            if not args_str:
                console.print("[red]Usage: break <location>[/red]")
            else:
                bp = await session.set_breakpoint(args_str)
                console.print(f"Breakpoint {bp.number} at 0x{bp.address:08x}")

        elif command == "del":
            if not args_str:
                console.print("[red]Usage: del <breakpoint_number>[/red]")
            else:
                num = int(args_str)
                success = await session.delete_breakpoint(num)
                if success:
                    console.print(f"Deleted breakpoint {num}")
                else:
                    console.print(f"[red]Failed to delete breakpoint {num}[/red]")

        elif command == "bt":
            frames = await session.get_backtrace(20)
            for frame in frames:
                level = frame.get("level", 0)
                addr = frame.get("addr", 0)
                func = frame.get("func", "??")
                console.print(f"  #{level:<2} 0x{addr:08x} in {func}")

        elif command in ("p", "print"):
            if not args_str:
                console.print("[red]Usage: print <expression>[/red]")
            else:
                result = await session.evaluate(args_str)
                console.print(f"  {args_str} = {result}")

        elif command == "fault":
            # Read fault registers directly
            from unconcealer.arch import get_architecture
            arch = get_architecture("cortex-m")
            if arch:
                fault = await arch.read_fault_state(session)
                console.print(f"[bold]Fault Type:[/bold] {fault.fault_type}")
                if fault.fault_address is not None:
                    console.print(f"[bold]Fault Address:[/bold] 0x{fault.fault_address:08x}")
                for reg, val in fault.raw_registers.items():
                    console.print(f"  {reg}: 0x{val:08x}")
                if fault.decoded:
                    console.print("[bold]Decoded:[/bold]")
                    for bit, msg in fault.decoded.items():
                        console.print(f"  {bit}: {msg}")
            else:
                console.print("[yellow]Fault register decoding not available[/yellow]")

        elif command == "snap":
            if not args_str:
                console.print("[red]Usage: snap <name>[/red]")
            else:
                success = await session.save_snapshot(args_str)
                if success:
                    console.print(f"[green]Saved snapshot: {args_str}[/green]")
                else:
                    console.print("[red]Failed to save snapshot[/red]")

        elif command == "restore":
            if not args_str:
                console.print("[red]Usage: restore <name>[/red]")
            else:
                success = await session.load_snapshot(args_str)
                if success:
                    console.print(f"[green]Restored snapshot: {args_str}[/green]")
                else:
                    console.print(f"[red]Failed to restore snapshot: {args_str}[/red]")

        else:
            console.print(f"[red]Unknown command: {command}. Type 'help' for help.[/red]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")

    return True


async def _run_shell_session(
    elf_path: Path,
    machine: str,
    cpu: str,
    gdb_port: int,
    gdb_path: str,
) -> None:
    """Run a headless interactive shell session."""
    from unconcealer.core.session import DebugSession
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
        title="[bold blue]Unconcealer Shell[/bold blue]",
    ))

    try:
        async with DebugSession(
            elf_path=str(elf_path),
            qemu_config=config,
            gdb_path=gdb_path,
        ) as session:
            console.print("[green]Session started. Type 'help' for commands.[/green]\n")

            while True:
                try:
                    user_input = Prompt.ask("[bold cyan]unc>[/bold cyan]")
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Exiting...[/yellow]")
                    break

                should_continue = await _handle_shell_command(user_input, session)
                if not should_continue:
                    console.print("[yellow]Ending session...[/yellow]")
                    break

    except Exception as e:
        console.print(f"[red]Failed to start session: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def shell(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    machine: str = typer.Option("lm3s6965evb", help="QEMU machine type"),
    cpu: str = typer.Option("cortex-m3", help="CPU type"),
    gdb_port: int = typer.Option(1234, help="GDB server port"),
    gdb_path: str = typer.Option("gdb-multiarch", help="Path to GDB executable"),
) -> None:
    """Start a headless interactive debugging shell (no LLM required)."""
    if not elf.exists():
        console.print(f"[red]Error: ELF file not found: {elf}[/red]")
        raise typer.Exit(1)

    asyncio.run(_run_shell_session(
        elf_path=elf,
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
        gdb_path=gdb_path,
    ))


# ============================================================================
# Test Command (automated non-interactive testing)
# ============================================================================


async def _run_test_session(
    elf_path: Path,
    machine: str,
    cpu: str,
    gdb_port: int,
    gdb_path: str,
    quick: bool,
    verbose: bool,
) -> bool:
    """Run automated test session. Returns True if all tests pass."""
    from unconcealer.core.session import DebugSession
    from unconcealer.tools.qemu_control import QEMUConfig
    from unconcealer.arch import get_architecture, detect_architecture
    from unconcealer.tools.gdb_bridge import StopReason

    config = QEMUConfig(
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
    )

    tests_passed = 0
    tests_failed = 0

    def pass_test(name: str, detail: str = "") -> None:
        nonlocal tests_passed
        tests_passed += 1
        if verbose:
            console.print(f"[green]✓[/green] {name}: {detail}")
        else:
            console.print(f"[green]✓[/green] {name}")

    def fail_test(name: str, error: str) -> None:
        nonlocal tests_failed
        tests_failed += 1
        console.print(f"[red]✗[/red] {name}: {error}")

    async def report_crash(session, arch_name: str) -> None:
        """Report fault details using architecture-specific registers."""
        console.print()

        # Get fault analysis - this is the primary source of truth
        try:
            arch = get_architecture(arch_name)
            fault = await arch.read_fault_state(session)

            # Build fault summary
            fault_info = f"[bold]Fault Type:[/bold] {fault.fault_type}"
            if fault.fault_address is not None:
                fault_info += f"\n[bold]Fault Address:[/bold] 0x{fault.fault_address:08x}"

            console.print(Panel(
                fault_info,
                title=f"[red]{fault.fault_type.upper()}[/red]",
                border_style="red",
            ))

            if fault.raw_registers:
                console.print("\n[bold]Fault Registers:[/bold]")
                for reg, val in fault.raw_registers.items():
                    console.print(f"  {reg}: 0x{val:08x}")

            if fault.decoded:
                console.print("\n[bold]Decoded Fault Bits:[/bold]")
                for bit, msg in fault.decoded.items():
                    console.print(f"  [yellow]{bit}[/yellow]: {msg}")

        except Exception as e:
            console.print(Panel(
                "[bold red]Firmware Fault[/bold red]",
                title="[red]FAULT[/red]",
                border_style="red",
            ))
            console.print(f"[dim]Could not read fault registers: {e}[/dim]")

        # Backtrace
        try:
            bt = await session.get_backtrace(5)
            if bt:
                console.print("\n[bold]Backtrace:[/bold]")
                for frame in bt:
                    level = frame.get("level", 0)
                    addr = frame.get("addr", 0)
                    func = frame.get("func", "??")
                    console.print(f"  #{level} 0x{addr:08x} in {func}")
        except Exception:
            pass

        # Key registers (PC, SP, LR)
        try:
            regs = await session.read_registers(["pc", "sp", "lr"])
            console.print("\n[bold]Registers:[/bold]")
            for name, value in regs.items():
                console.print(f"  {name:4} = 0x{value:08x}")
        except Exception:
            pass

        console.print()

    try:
        async with DebugSession(
            elf_path=str(elf_path),
            qemu_config=config,
            gdb_path=gdb_path,
        ) as session:
            pass_test("Session start", "QEMU + GDB connected")

            # Test 1: Read registers
            try:
                regs = await session.read_registers()
                if regs:
                    pc = regs.get("pc", 0)
                    sp = regs.get("sp", 0)
                    pass_test("Read registers", f"PC=0x{pc:08x} SP=0x{sp:08x}")
                else:
                    fail_test("Read registers", "Empty register set")
            except Exception as e:
                fail_test("Read registers", str(e))

            # Test 2: Read single register
            try:
                pc = await session.read_register("pc")
                pass_test("Read single register", f"PC=0x{pc:08x}")
            except Exception as e:
                fail_test("Read single register", str(e))

            # Test 3: Read memory
            try:
                # Read from a typical ARM Cortex-M code region
                data = await session.read_memory(0x00000000, 16)
                if len(data) == 16:
                    pass_test("Read memory", f"{data[:8].hex()}...")
                else:
                    fail_test("Read memory", f"Expected 16 bytes, got {len(data)}")
            except Exception as e:
                fail_test("Read memory", str(e))

            # Test 4: Get backtrace
            try:
                bt = await session.get_backtrace(5)
                if bt:
                    func = bt[0].get("func", "??")
                    pass_test("Get backtrace", f"Top frame: {func}")
                else:
                    pass_test("Get backtrace", "(empty - target at entry)")
            except Exception as e:
                fail_test("Get backtrace", str(e))

            if not quick:
                # Test 5: Set breakpoint
                try:
                    bp = await session.set_breakpoint("main")
                    pass_test("Set breakpoint", f"Breakpoint #{bp.number} at 0x{bp.address:08x}")

                    # Test 6: Continue to breakpoint
                    try:
                        stop = await session.continue_execution()
                        if stop.reason == StopReason.SIGNAL:
                            # Firmware faulted
                            arch_name = detect_architecture(cpu, machine)
                            arch = get_architecture(arch_name)
                            fault = await arch.read_fault_state(session)
                            fail_test("Continue execution", f"FAULT: {fault.fault_type}")
                            await report_crash(session, arch_name)
                        elif stop.reason == StopReason.BREAKPOINT:
                            pass_test("Continue execution", f"Hit breakpoint at 0x{stop.address:08x}")
                        else:
                            pass_test("Continue execution", f"Stopped ({stop.reason.value}) at 0x{stop.address:08x}")
                    except Exception as e:
                        fail_test("Continue execution", str(e))

                    # Test 7: Single step (skip if we crashed above)
                    if stop.reason != StopReason.SIGNAL:
                        try:
                            stop = await session.step()
                            if stop.reason == StopReason.SIGNAL:
                                arch_name = detect_architecture(cpu, machine)
                                arch = get_architecture(arch_name)
                                fault = await arch.read_fault_state(session)
                                fail_test("Single step", f"FAULT: {fault.fault_type}")
                                await report_crash(session, arch_name)
                            else:
                                pass_test("Single step", f"Stepped to 0x{stop.address:08x}")
                        except Exception as e:
                            fail_test("Single step", str(e))

                    # Test 8: Delete breakpoint (skip if we crashed)
                    if stop.reason != StopReason.SIGNAL:
                        try:
                            success = await session.delete_breakpoint(bp.number)
                            if success:
                                pass_test("Delete breakpoint", f"Removed #{bp.number}")
                            else:
                                fail_test("Delete breakpoint", "delete returned False")
                        except Exception as e:
                            fail_test("Delete breakpoint", str(e))

                except Exception as e:
                    fail_test("Set breakpoint", str(e))

                # Test 9: Fault register read (architecture-specific)
                try:
                    arch_name = detect_architecture(cpu, machine)
                    arch = get_architecture(arch_name)
                    fault = await arch.read_fault_state(session)
                    pass_test("Read fault state", f"Type: {fault.fault_type}")
                except Exception as e:
                    fail_test("Read fault state", str(e))

                # Test 10: Evaluate expression
                try:
                    result = await session.evaluate("1 + 1")
                    pass_test("Evaluate expression", f"1 + 1 = {result}")
                except Exception as e:
                    fail_test("Evaluate expression", str(e))

    except Exception as e:
        fail_test("Session start", str(e))
        return False

    # Summary
    console.print()
    total = tests_passed + tests_failed
    if tests_failed == 0:
        console.print(f"[bold green]All {tests_passed} tests passed![/bold green]")
        return True
    else:
        console.print(f"[bold yellow]{tests_passed}/{total} tests passed, {tests_failed} failed[/bold yellow]")
        return False


@app.command()
def test(
    elf: Path = typer.Argument(..., help="Path to ELF binary"),
    machine: str = typer.Option("lm3s6965evb", help="QEMU machine type"),
    cpu: str = typer.Option("cortex-m3", help="CPU type"),
    gdb_port: int = typer.Option(1234, help="GDB server port"),
    gdb_path: str = typer.Option("gdb-multiarch", help="Path to GDB executable"),
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick test (skip execution tests)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show test details"),
) -> None:
    """Run automated tests on firmware (non-interactive).

    Starts QEMU + GDB, runs diagnostic checks, and exits with status code.
    Suitable for CI/CD pipelines and quick verification.

    Examples:
        unconcealer test firmware.elf
        unconcealer test firmware.elf --quick
        unconcealer test firmware.elf --verbose
    """
    if not elf.exists():
        console.print(f"[red]Error: ELF file not found: {elf}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]ELF:[/bold] {elf}\n"
        f"[bold]Machine:[/bold] {machine}\n"
        f"[bold]CPU:[/bold] {cpu}\n"
        f"[bold]Mode:[/bold] {'Quick' if quick else 'Full'}",
        title="[bold blue]Unconcealer Test[/bold blue]",
    ))

    success = asyncio.run(_run_test_session(
        elf_path=elf,
        machine=machine,
        cpu=cpu,
        gdb_port=gdb_port,
        gdb_path=gdb_path,
        quick=quick,
        verbose=verbose,
    ))

    if not success:
        raise typer.Exit(1)


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
def doctor() -> None:
    """Check system dependencies and installation health."""
    from unconcealer import __version__

    console.print(Panel(
        "[bold]Checking dependencies...[/bold]",
        title="[bold blue]Unconcealer Doctor[/bold blue]",
    ))

    all_ok = True

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        console.print(f"[green]✓[/green] Python {py_version}")
    else:
        console.print(f"[red]✗[/red] Python {py_version} (requires >= 3.10)")
        all_ok = False

    # QEMU (ARM)
    qemu_arm = shutil.which("qemu-system-arm")
    if qemu_arm:
        try:
            result = subprocess.run(
                [qemu_arm, "--version"],
                capture_output=True, text=True, timeout=5
            )
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            console.print(f"[green]✓[/green] qemu-system-arm ({version_line})")
        except Exception:
            console.print(f"[green]✓[/green] qemu-system-arm (at {qemu_arm})")
    else:
        console.print("[yellow]![/yellow] qemu-system-arm not found")
        console.print("    [dim]Install: sudo apt install qemu-system-arm[/dim]")

    # QEMU (RISC-V)
    qemu_riscv = shutil.which("qemu-system-riscv32") or shutil.which("qemu-system-riscv64")
    if qemu_riscv:
        console.print(f"[green]✓[/green] QEMU RISC-V (at {qemu_riscv})")
    else:
        console.print("[dim]-[/dim] qemu-system-riscv32/64 not found (optional)")

    # GDB
    gdb_options = ["gdb-multiarch", "arm-none-eabi-gdb", "riscv64-unknown-elf-gdb", "gdb"]
    gdb_found = None
    for gdb_name in gdb_options:
        gdb_path = shutil.which(gdb_name)
        if gdb_path:
            gdb_found = gdb_name
            break

    if gdb_found:
        try:
            result = subprocess.run(
                [gdb_found, "--version"],
                capture_output=True, text=True, timeout=5
            )
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            console.print(f"[green]✓[/green] GDB: {gdb_found} ({version_line})")
        except Exception:
            console.print(f"[green]✓[/green] GDB: {gdb_found}")
    else:
        console.print("[red]✗[/red] GDB not found")
        console.print("    [dim]Install: sudo apt install gdb-multiarch[/dim]")
        all_ok = False

    # Test firmware
    test_fw_path = Path(__file__).parent.parent.parent / "test_fw"
    elf_path = test_fw_path / "target" / "thumbv7m-none-eabi" / "release" / "test_fw"
    if elf_path.exists():
        console.print(f"[green]✓[/green] Test firmware built ({elf_path.name})")
    elif test_fw_path.exists():
        console.print("[yellow]![/yellow] Test firmware not built")
        console.print("    [dim]Run: cd test_fw && cargo build --release[/dim]")
    else:
        console.print("[dim]-[/dim] Test firmware directory not found (optional)")

    # Required Python packages
    required_packages = [
        ("pygdbmi", "pygdbmi"),
        ("typer", "typer"),
        ("rich", "rich"),
        ("pydantic", "pydantic"),
    ]
    missing_packages = []
    for import_name, package_name in required_packages:
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)

    if not missing_packages:
        console.print("[green]✓[/green] Python dependencies installed")
    else:
        console.print(f"[red]✗[/red] Missing packages: {', '.join(missing_packages)}")
        console.print(f"    [dim]Install: pip install {' '.join(missing_packages)}[/dim]")
        all_ok = False

    # Summary
    console.print()
    if all_ok:
        console.print("[bold green]All required checks passed![/bold green]")
    else:
        console.print("[bold yellow]Some checks failed. See above for details.[/bold yellow]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from unconcealer import __version__
    console.print(f"[bold blue]Unconcealer[/bold blue] v{__version__}")


if __name__ == "__main__":
    app()
