"""Base architecture definitions and protocols.

This module defines the TargetArchitecture protocol that all architecture
implementations must follow, along with common data structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from unconcealer.core.session import DebugSession


@dataclass
class FaultState:
    """Architecture-agnostic fault/exception information.

    This captures the essential fault information in a way that's
    comparable across architectures.

    Attributes:
        fault_type: High-level fault category
        fault_address: Address that caused the fault (if applicable)
        is_valid: Whether the fault address is valid
        raw_registers: Raw fault register values
        decoded: Human-readable explanations of fault bits
    """

    fault_type: str  # "access_violation", "illegal_instruction", etc.
    fault_address: Optional[int] = None
    is_valid: bool = False
    raw_registers: Dict[str, int] = field(default_factory=dict)
    decoded: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "fault_type": self.fault_type,
            "fault_address": (
                f"0x{self.fault_address:08x}" if self.fault_address else None
            ),
            "is_valid": self.is_valid,
            "raw_registers": {
                k: f"0x{v:08x}" for k, v in self.raw_registers.items()
            },
            "decoded": self.decoded,
        }


@dataclass
class ExceptionFrame:
    """Stacked exception/trap frame.

    When an exception occurs, processors typically push registers
    onto the stack. This captures that information.

    Attributes:
        registers: Register values from the frame
        return_address: Address to return to after handling
        stack_pointer: Stack pointer at time of exception
        frame_type: Architecture-specific frame type info
    """

    registers: Dict[str, int] = field(default_factory=dict)
    return_address: int = 0
    stack_pointer: int = 0
    frame_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "registers": {k: f"0x{v:08x}" for k, v in self.registers.items()},
            "return_address": f"0x{self.return_address:08x}",
            "stack_pointer": f"0x{self.stack_pointer:08x}",
            "frame_type": self.frame_type,
        }


@dataclass
class InterruptInfo:
    """Information about a single interrupt."""

    number: int
    name: str
    priority: Optional[int] = None
    enabled: bool = False
    pending: bool = False
    active: bool = False


@dataclass
class InterruptAnalysis:
    """Interrupt controller analysis result.

    Attributes:
        enabled: List of enabled interrupts
        pending: List of pending interrupts
        priorities: Priority values for key handlers
        warnings: Detected configuration issues
    """

    enabled: List[InterruptInfo] = field(default_factory=list)
    pending: List[InterruptInfo] = field(default_factory=list)
    priorities: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": [
                {"number": i.number, "name": i.name, "priority": i.priority}
                for i in self.enabled
            ],
            "pending": [{"number": i.number, "name": i.name} for i in self.pending],
            "priorities": self.priorities,
            "warnings": self.warnings,
        }


@dataclass
class MemoryRegion:
    """A memory protection region."""

    number: int
    base_address: int
    size: int
    permissions: str  # e.g., "RWX", "R--", etc.
    enabled: bool = True
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryProtectionConfig:
    """Memory protection unit configuration.

    Attributes:
        enabled: Whether protection is globally enabled
        regions: List of configured regions
        default_permissions: Permissions for unmapped memory
    """

    enabled: bool = False
    regions: List[MemoryRegion] = field(default_factory=list)
    default_permissions: str = "---"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "enabled": self.enabled,
            "regions": [
                {
                    "number": r.number,
                    "base": f"0x{r.base_address:08x}",
                    "size": r.size,
                    "permissions": r.permissions,
                    "enabled": r.enabled,
                    "attributes": r.attributes,
                }
                for r in self.regions
            ],
            "default_permissions": self.default_permissions,
        }


class TargetArchitecture(ABC):
    """Abstract base class for architecture-specific debugging support.

    Each supported architecture implements this class to provide
    architecture-specific fault analysis, interrupt configuration
    checking, and memory protection decoding.

    Example:
        class CortexMTarget(TargetArchitecture):
            name = "cortex-m"
            register_names = ["r0", "r1", ..., "pc"]
            pointer_size = 4

            async def read_fault_state(self, session):
                # Read CFSR, HFSR, etc.
                ...
    """

    # Class attributes to be defined by subclasses
    name: str = ""
    register_names: List[str] = []
    pointer_size: int = 4  # 4 for 32-bit, 8 for 64-bit

    @abstractmethod
    async def read_fault_state(self, session: "DebugSession") -> FaultState:
        """Read and decode fault/exception state.

        Args:
            session: Active debug session

        Returns:
            FaultState with decoded fault information
        """
        ...

    @abstractmethod
    async def decode_exception_frame(
        self, session: "DebugSession", stack_pointer: Optional[int] = None
    ) -> ExceptionFrame:
        """Parse the stacked exception/trap frame.

        Args:
            session: Active debug session
            stack_pointer: Stack pointer to read from (uses current SP if None)

        Returns:
            ExceptionFrame with stacked register values
        """
        ...

    @abstractmethod
    async def check_interrupt_config(
        self, session: "DebugSession"
    ) -> InterruptAnalysis:
        """Analyze interrupt controller configuration.

        Args:
            session: Active debug session

        Returns:
            InterruptAnalysis with configuration and warnings
        """
        ...

    @abstractmethod
    async def get_memory_protection(
        self, session: "DebugSession"
    ) -> MemoryProtectionConfig:
        """Read memory protection configuration.

        Args:
            session: Active debug session

        Returns:
            MemoryProtectionConfig with region information
        """
        ...

    async def analyze_crash(self, session: "DebugSession") -> Dict[str, Any]:
        """Perform architecture-specific crash analysis.

        Default implementation gathers fault state, exception frame,
        and interrupt config. Subclasses can override for additional
        architecture-specific analysis.

        Args:
            session: Active debug session

        Returns:
            Dictionary with crash analysis results
        """
        fault = await self.read_fault_state(session)
        frame = await self.decode_exception_frame(session)
        interrupts = await self.check_interrupt_config(session)

        return {
            "architecture": self.name,
            "fault": fault.to_dict(),
            "exception_frame": frame.to_dict(),
            "interrupts": interrupts.to_dict(),
        }

    def _read_memory_word(self, data: bytes) -> int:
        """Read a word from bytes in little-endian format."""
        if self.pointer_size == 8:
            return int.from_bytes(data[:8], "little")
        return int.from_bytes(data[:4], "little")
