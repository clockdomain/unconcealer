"""Shared data types for the unconcealer debugger."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class DebugConfig:
    """Configuration for a debug session."""
    elf_path: Path
    target: str = "cortex-m4"
    qemu_machine: str = "lm3s6965evb"
    gdb_path: str = "arm-none-eabi-gdb"
    qemu_path: str = "qemu-system-arm"
    gdb_port: int = 1234
    qmp_port: int = 4444
    extra_qemu_args: List[str] = field(default_factory=list)


@dataclass
class DebugContext:
    """Current debugging context."""
    pc: int = 0
    registers: Dict[str, int] = field(default_factory=dict)
    stack_frames: List[Dict[str, Any]] = field(default_factory=list)
    current_function: Optional[str] = None
    source_file: Optional[str] = None
    source_line: Optional[int] = None
