"""Tests for architecture abstraction layer."""

import pytest
from unittest.mock import AsyncMock, patch

from unconcealer.arch import (
    get_architecture,
    detect_architecture,
    list_architectures,
    ARCHITECTURES,
    TargetArchitecture,
    FaultState,
    ExceptionFrame,
    InterruptAnalysis,
    MemoryProtectionConfig,
)
from unconcealer.arch.cortex_m import CortexMTarget, CortexM0Target, CortexM33Target
from unconcealer.arch.riscv import RiscVTarget, RiscV32Target, RiscV64Target


class TestArchitectureRegistry:
    """Test architecture registry functions."""

    def test_get_architecture_cortex_m(self) -> None:
        """Test getting Cortex-M architecture."""
        arch = get_architecture("cortex-m")
        assert isinstance(arch, CortexMTarget)
        assert arch.name == "cortex-m"

    def test_get_architecture_cortex_m3(self) -> None:
        """Test getting Cortex-M3 architecture."""
        arch = get_architecture("cortex-m3")
        assert isinstance(arch, CortexMTarget)

    def test_get_architecture_cortex_m0(self) -> None:
        """Test getting Cortex-M0 architecture."""
        arch = get_architecture("cortex-m0")
        assert isinstance(arch, CortexM0Target)

    def test_get_architecture_cortex_m33(self) -> None:
        """Test getting Cortex-M33 architecture."""
        arch = get_architecture("cortex-m33")
        assert isinstance(arch, CortexM33Target)

    def test_get_architecture_riscv(self) -> None:
        """Test getting RISC-V architecture."""
        arch = get_architecture("riscv")
        assert isinstance(arch, RiscVTarget)

    def test_get_architecture_riscv32(self) -> None:
        """Test getting RISC-V 32-bit architecture."""
        arch = get_architecture("riscv32")
        assert isinstance(arch, RiscV32Target)
        assert arch.pointer_size == 4

    def test_get_architecture_riscv64(self) -> None:
        """Test getting RISC-V 64-bit architecture."""
        arch = get_architecture("riscv64")
        assert isinstance(arch, RiscV64Target)
        assert arch.pointer_size == 8

    def test_get_architecture_case_insensitive(self) -> None:
        """Test case-insensitive lookup."""
        arch = get_architecture("CORTEX-M4")
        assert isinstance(arch, CortexMTarget)

    def test_get_architecture_unknown(self) -> None:
        """Test unknown architecture raises error."""
        with pytest.raises(ValueError) as exc:
            get_architecture("unknown-arch")
        assert "Unknown architecture" in str(exc.value)

    def test_list_architectures(self) -> None:
        """Test listing architectures."""
        archs = list_architectures()
        assert "cortex-m" in archs
        assert "riscv" in archs
        assert "riscv32" in archs
        assert len(archs) > 5


class TestDetectArchitecture:
    """Test architecture auto-detection."""

    def test_detect_cortex_m3(self) -> None:
        """Test detecting Cortex-M3."""
        result = detect_architecture("cortex-m3", "lm3s6965evb")
        assert result == "cortex-m3"

    def test_detect_cortex_m4(self) -> None:
        """Test detecting Cortex-M4."""
        result = detect_architecture("cortex-m4", "netduinoplus2")
        assert result == "cortex-m4"

    def test_detect_cortex_m0(self) -> None:
        """Test detecting Cortex-M0."""
        result = detect_architecture("cortex-m0", "microbit")
        assert result == "cortex-m0"

    def test_detect_cortex_m33(self) -> None:
        """Test detecting Cortex-M33."""
        result = detect_architecture("cortex-m33", "mps2-an505")
        assert result == "cortex-m33"

    def test_detect_riscv32_from_cpu(self) -> None:
        """Test detecting RISC-V 32-bit from CPU."""
        result = detect_architecture("rv32", "virt")
        assert result == "riscv32"

    def test_detect_riscv64_from_cpu(self) -> None:
        """Test detecting RISC-V 64-bit from CPU."""
        result = detect_architecture("rv64", "virt")
        assert result == "riscv64"

    def test_detect_riscv_from_sifive_e(self) -> None:
        """Test detecting RISC-V from SiFive E machine."""
        result = detect_architecture("any", "sifive_e")
        assert result == "riscv32"

    def test_detect_riscv_from_sifive_u(self) -> None:
        """Test detecting RISC-V from SiFive U machine."""
        result = detect_architecture("any", "sifive_u")
        assert result == "riscv64"

    def test_detect_default_cortex_m(self) -> None:
        """Test default to Cortex-M for unknown."""
        result = detect_architecture("unknown", "unknown")
        assert result == "cortex-m"


class TestFaultState:
    """Test FaultState dataclass."""

    def test_create_fault_state(self) -> None:
        """Test creating FaultState."""
        fault = FaultState(
            fault_type="access_violation",
            fault_address=0x20000000,
            is_valid=True,
            raw_registers={"CFSR": 0x82},
            decoded={"DACCVIOL": "Data access violation"},
        )
        assert fault.fault_type == "access_violation"
        assert fault.fault_address == 0x20000000

    def test_fault_state_to_dict(self) -> None:
        """Test FaultState serialization."""
        fault = FaultState(
            fault_type="illegal_instruction",
            fault_address=0x08001234,
            is_valid=True,
            raw_registers={"CFSR": 0x010000},
            decoded={"UNDEFINSTR": "Undefined instruction"},
        )
        d = fault.to_dict()
        assert d["fault_type"] == "illegal_instruction"
        assert d["fault_address"] == "0x08001234"
        assert "CFSR" in d["raw_registers"]


class TestExceptionFrame:
    """Test ExceptionFrame dataclass."""

    def test_create_exception_frame(self) -> None:
        """Test creating ExceptionFrame."""
        frame = ExceptionFrame(
            registers={"r0": 0, "r1": 1, "pc": 0x08001000},
            return_address=0x08001000,
            stack_pointer=0x20001000,
            frame_type="basic",
        )
        assert frame.return_address == 0x08001000
        assert frame.frame_type == "basic"

    def test_exception_frame_to_dict(self) -> None:
        """Test ExceptionFrame serialization."""
        frame = ExceptionFrame(
            registers={"pc": 0x08001234},
            return_address=0x08001234,
            stack_pointer=0x20001000,
        )
        d = frame.to_dict()
        assert "0x08001234" in d["return_address"]


class TestCortexMTarget:
    """Test CortexMTarget implementation."""

    def test_attributes(self) -> None:
        """Test CortexMTarget attributes."""
        target = CortexMTarget()
        assert target.name == "cortex-m"
        assert target.pointer_size == 4
        assert "r0" in target.register_names
        assert "pc" in target.register_names

    def test_decode_cfsr_memmanage(self) -> None:
        """Test CFSR decoding for MemManage faults."""
        target = CortexMTarget()
        decoded = target._decode_cfsr(0x82)  # DACCVIOL + MMARVALID
        assert "DACCVIOL" in decoded
        assert "MMARVALID" in decoded

    def test_decode_cfsr_busfault(self) -> None:
        """Test CFSR decoding for BusFault."""
        target = CortexMTarget()
        decoded = target._decode_cfsr(0x0200)  # PRECISERR
        assert "PRECISERR" in decoded

    def test_decode_cfsr_usagefault(self) -> None:
        """Test CFSR decoding for UsageFault."""
        target = CortexMTarget()
        decoded = target._decode_cfsr(0x010000)  # UNDEFINSTR
        assert "UNDEFINSTR" in decoded

    def test_decode_cfsr_divbyzero(self) -> None:
        """Test CFSR decoding for divide by zero."""
        target = CortexMTarget()
        decoded = target._decode_cfsr(0x02000000)
        assert "DIVBYZERO" in decoded

    def test_decode_hfsr_forced(self) -> None:
        """Test HFSR decoding for forced fault."""
        target = CortexMTarget()
        decoded = target._decode_hfsr(0x40000000)
        assert "FORCED" in decoded

    def test_determine_fault_type(self) -> None:
        """Test fault type determination."""
        target = CortexMTarget()

        # MemManage fault
        assert target._determine_fault_type(0x02, 0) == "memory_protection_fault"

        # Divide by zero
        assert target._determine_fault_type(0x02000000, 0) == "divide_by_zero"

        # Invalid PC
        assert target._determine_fault_type(0x040000, 0) == "invalid_pc"

        # Escalated
        assert target._determine_fault_type(0, 0x40000000) == "escalated_fault"

    @pytest.mark.asyncio
    async def test_read_fault_state(self) -> None:
        """Test reading fault state."""
        target = CortexMTarget()
        session = AsyncMock()

        # Mock memory reads for fault registers
        session.read_memory = AsyncMock(
            side_effect=[
                bytes([0x02, 0x00, 0x00, 0x00]),  # CFSR = DACCVIOL
                bytes([0x00, 0x00, 0x00, 0x00]),  # HFSR
                bytes([0x00, 0x00, 0x00, 0x20]),  # MMFAR = 0x20000000
                bytes([0x00, 0x00, 0x00, 0x00]),  # BFAR
            ]
        )

        fault = await target.read_fault_state(session)

        # Note: MMARVALID bit (0x80) not set, so address won't be valid
        assert fault.fault_type == "memory_protection_fault"
        assert "DACCVIOL" in fault.decoded

    @pytest.mark.asyncio
    async def test_decode_exception_frame(self) -> None:
        """Test decoding exception frame."""
        target = CortexMTarget()
        session = AsyncMock()

        # Mock register read for SP
        session.read_registers = AsyncMock(return_value={"sp": 0x20001000})

        # Mock memory read for frame (32 bytes)
        frame_data = (
            b"\x00\x00\x00\x00"  # R0
            b"\x01\x00\x00\x00"  # R1
            b"\x02\x00\x00\x00"  # R2
            b"\x03\x00\x00\x00"  # R3
            b"\x0c\x00\x00\x00"  # R12
            b"\x00\x10\x00\x08"  # LR = 0x08001000
            b"\x34\x12\x00\x08"  # PC = 0x08001234
            b"\x00\x00\x00\x01"  # xPSR
        )
        session.read_memory = AsyncMock(return_value=frame_data)

        frame = await target.decode_exception_frame(session)

        assert frame.registers["pc"] == 0x08001234
        assert frame.registers["lr"] == 0x08001000
        assert frame.return_address == 0x08001234


class TestRiscVTarget:
    """Test RiscVTarget implementation."""

    def test_attributes(self) -> None:
        """Test RiscVTarget attributes."""
        target = RiscVTarget()
        assert target.name == "riscv"
        assert target.pointer_size == 4
        assert "ra" in target.register_names
        assert "sp" in target.register_names

    def test_decode_mcause_exception(self) -> None:
        """Test mcause decoding for exceptions."""
        target = RiscVTarget()

        # Illegal instruction (code 2)
        info = target._decode_mcause(2)
        assert info["type"] == "exception"
        assert "Illegal instruction" in info["name"]

        # Load access fault (code 5)
        info = target._decode_mcause(5)
        assert info["type"] == "exception"
        assert "Load access fault" in info["name"]

    def test_decode_mcause_interrupt(self) -> None:
        """Test mcause decoding for interrupts."""
        target = RiscVTarget()

        # Machine timer interrupt (bit 31 set + code 7)
        mcause = 0x80000007
        info = target._decode_mcause(mcause)
        assert info["type"] == "interrupt"
        assert "timer" in info["name"].lower()

    def test_determine_fault_type(self) -> None:
        """Test fault type determination."""
        target = RiscVTarget()

        info = {"type": "exception", "code": 2}
        assert target._determine_fault_type(info) == "illegal_instruction"

        info = {"type": "exception", "code": 5}
        assert target._determine_fault_type(info) == "load_access_fault"

        info = {"type": "interrupt", "code": 7}
        assert target._determine_fault_type(info) == "interrupt"

    @pytest.mark.asyncio
    async def test_read_fault_state(self) -> None:
        """Test reading fault state."""
        target = RiscVTarget()
        session = AsyncMock()

        # Mock CSR reads
        async def mock_evaluate(expr):
            if "mcause" in expr:
                return "2"  # Illegal instruction
            elif "mtval" in expr:
                return "0x12345678"
            elif "mepc" in expr:
                return "0x80001000"
            return "0"

        session.evaluate = mock_evaluate

        fault = await target.read_fault_state(session)

        assert fault.fault_type == "illegal_instruction"
        assert fault.raw_registers["mcause"] == 2


class TestRiscV32Target:
    """Test RiscV32Target implementation."""

    def test_attributes(self) -> None:
        """Test RiscV32Target attributes."""
        target = RiscV32Target()
        assert target.name == "riscv32"
        assert target.pointer_size == 4


class TestRiscV64Target:
    """Test RiscV64Target implementation."""

    def test_attributes(self) -> None:
        """Test RiscV64Target attributes."""
        target = RiscV64Target()
        assert target.name == "riscv64"
        assert target.pointer_size == 8


class TestInterruptAnalysis:
    """Test InterruptAnalysis dataclass."""

    def test_to_dict(self) -> None:
        """Test InterruptAnalysis serialization."""
        from unconcealer.arch.base import InterruptInfo

        analysis = InterruptAnalysis(
            enabled=[InterruptInfo(number=0, name="IRQ0", enabled=True)],
            pending=[],
            priorities={"SVCall": 0, "PendSV": 255},
            warnings=["Test warning"],
        )
        d = analysis.to_dict()
        assert len(d["enabled"]) == 1
        assert d["priorities"]["SVCall"] == 0
        assert "Test warning" in d["warnings"]


class TestMemoryProtectionConfig:
    """Test MemoryProtectionConfig dataclass."""

    def test_to_dict(self) -> None:
        """Test MemoryProtectionConfig serialization."""
        from unconcealer.arch.base import MemoryRegion

        config = MemoryProtectionConfig(
            enabled=True,
            regions=[
                MemoryRegion(
                    number=0,
                    base_address=0x20000000,
                    size=0x10000,
                    permissions="RW-",
                )
            ],
            default_permissions="---",
        )
        d = config.to_dict()
        assert d["enabled"] is True
        assert len(d["regions"]) == 1
        assert d["regions"][0]["permissions"] == "RW-"
