"""Architecture abstraction layer.

This module provides a pluggable architecture system that enables
multi-architecture support for debugging different embedded targets.

Supported architectures:
- ARM Cortex-M (M0, M0+, M3, M4, M7, M23, M33)
- RISC-V (RV32, RV64)

Example:
    from unconcealer.arch import get_architecture, detect_architecture

    # Auto-detect from QEMU settings
    arch_name = detect_architecture(cpu="cortex-m3", machine="lm3s6965evb")
    arch = get_architecture(arch_name)

    # Read fault state
    fault = await arch.read_fault_state(session)
    print(f"Fault: {fault.fault_type}")

Adding a new architecture:
    1. Create a new module (e.g., xtensa.py)
    2. Implement TargetArchitecture base class
    3. Register in ARCHITECTURES dict below
"""

from typing import Dict, Type

from unconcealer.arch.base import (
    TargetArchitecture,
    FaultState,
    ExceptionFrame,
    InterruptAnalysis,
    InterruptInfo,
    MemoryProtectionConfig,
    MemoryRegion,
)
from unconcealer.arch.cortex_m import (
    CortexMTarget,
    CortexM0Target,
    CortexM33Target,
)
from unconcealer.arch.riscv import (
    RiscVTarget,
    RiscV32Target,
    RiscV64Target,
)

# Architecture registry
# Maps architecture names to their implementation classes
ARCHITECTURES: Dict[str, Type[TargetArchitecture]] = {
    # ARM Cortex-M variants
    "cortex-m": CortexMTarget,
    "cortex-m0": CortexM0Target,
    "cortex-m0+": CortexM0Target,
    "cortex-m3": CortexMTarget,
    "cortex-m4": CortexMTarget,
    "cortex-m7": CortexMTarget,
    "cortex-m23": CortexM33Target,
    "cortex-m33": CortexM33Target,
    # RISC-V variants
    "riscv": RiscVTarget,
    "riscv32": RiscV32Target,
    "riscv64": RiscV64Target,
    "rv32": RiscV32Target,
    "rv64": RiscV64Target,
}


def get_architecture(name: str) -> TargetArchitecture:
    """Get an architecture handler by name.

    Args:
        name: Architecture name (e.g., "cortex-m3", "riscv32")

    Returns:
        TargetArchitecture instance

    Raises:
        ValueError: If architecture is not supported

    Example:
        arch = get_architecture("cortex-m4")
        fault = await arch.read_fault_state(session)
    """
    arch_class = ARCHITECTURES.get(name.lower())
    if arch_class is None:
        supported = sorted(set(ARCHITECTURES.keys()))
        raise ValueError(
            f"Unknown architecture: {name}. "
            f"Supported architectures: {', '.join(supported)}"
        )
    return arch_class()


def detect_architecture(cpu: str, machine: str) -> str:
    """Auto-detect architecture from QEMU cpu/machine.

    Args:
        cpu: QEMU CPU type (e.g., "cortex-m3", "rv32")
        machine: QEMU machine type (e.g., "lm3s6965evb", "sifive_e")

    Returns:
        Architecture name suitable for get_architecture()

    Example:
        arch_name = detect_architecture("cortex-m3", "mps2-an385")
        # Returns "cortex-m3"

        arch_name = detect_architecture("rv32", "sifive_e")
        # Returns "riscv32"
    """
    cpu_lower = cpu.lower()
    machine_lower = machine.lower()

    # ARM Cortex-M detection
    if "cortex-m0+" in cpu_lower:
        return "cortex-m0+"
    if "cortex-m0" in cpu_lower:
        return "cortex-m0"
    if "cortex-m33" in cpu_lower:
        return "cortex-m33"
    if "cortex-m23" in cpu_lower:
        return "cortex-m23"
    if "cortex-m7" in cpu_lower:
        return "cortex-m7"
    if "cortex-m4" in cpu_lower:
        return "cortex-m4"
    if "cortex-m3" in cpu_lower:
        return "cortex-m3"
    if "cortex" in cpu_lower:
        return "cortex-m"

    # RISC-V detection
    if "rv64" in cpu_lower or "riscv64" in machine_lower:
        return "riscv64"
    if "rv32" in cpu_lower or "riscv32" in machine_lower:
        return "riscv32"
    if "sifive" in machine_lower:
        # SiFive machines - check for E (32-bit) vs U (64-bit)
        if "sifive_u" in machine_lower:
            return "riscv64"
        return "riscv32"
    if "riscv" in cpu_lower or "riscv" in machine_lower:
        return "riscv"

    # Default to Cortex-M (most common embedded target)
    return "cortex-m"


def list_architectures() -> list[str]:
    """List all supported architecture names.

    Returns:
        Sorted list of architecture names
    """
    return sorted(set(ARCHITECTURES.keys()))


__all__ = [
    # Base classes
    "TargetArchitecture",
    "FaultState",
    "ExceptionFrame",
    "InterruptAnalysis",
    "InterruptInfo",
    "MemoryProtectionConfig",
    "MemoryRegion",
    # Implementations
    "CortexMTarget",
    "CortexM0Target",
    "CortexM33Target",
    "RiscVTarget",
    "RiscV32Target",
    "RiscV64Target",
    # Registry functions
    "get_architecture",
    "detect_architecture",
    "list_architectures",
    "ARCHITECTURES",
]
