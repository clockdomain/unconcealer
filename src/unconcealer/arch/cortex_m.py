"""ARM Cortex-M architecture support.

Provides fault analysis, NVIC configuration checking, and MPU decoding
for ARM Cortex-M processors (M0, M0+, M3, M4, M7, M23, M33).
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from unconcealer.arch.base import (
    TargetArchitecture,
    FaultState,
    ExceptionFrame,
    InterruptAnalysis,
    InterruptInfo,
    MemoryProtectionConfig,
    MemoryRegion,
)

if TYPE_CHECKING:
    from unconcealer.core.session import DebugSession


class CortexMTarget(TargetArchitecture):
    """ARM Cortex-M architecture support.

    Supports Cortex-M0, M0+, M3, M4, M7, M23, M33 processors.
    Provides fault register decoding, NVIC analysis, and MPU configuration.

    Example:
        target = CortexMTarget()
        fault = await target.read_fault_state(session)
        print(f"Fault: {fault.fault_type}")
        for bit, msg in fault.decoded.items():
            print(f"  {bit}: {msg}")
    """

    name = "cortex-m"
    register_names = [
        "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
        "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc", "xpsr",
    ]
    pointer_size = 4

    # System Control Block (SCB) registers
    CFSR = 0xE000ED28   # Configurable Fault Status Register
    HFSR = 0xE000ED2C   # HardFault Status Register
    DFSR = 0xE000ED30   # Debug Fault Status Register
    MMFAR = 0xE000ED34  # MemManage Fault Address Register
    BFAR = 0xE000ED38   # BusFault Address Register
    AFSR = 0xE000ED3C   # Auxiliary Fault Status Register

    # System Handler Priority Registers
    SHPR1 = 0xE000ED18  # Priority 4-7 (MemManage, BusFault, UsageFault)
    SHPR2 = 0xE000ED1C  # Priority 8-11 (SVCall)
    SHPR3 = 0xE000ED20  # Priority 12-15 (PendSV, SysTick)

    # NVIC registers
    NVIC_ISER_BASE = 0xE000E100  # Interrupt Set Enable (8 regs)
    NVIC_ICER_BASE = 0xE000E180  # Interrupt Clear Enable (8 regs)
    NVIC_ISPR_BASE = 0xE000E200  # Interrupt Set Pending (8 regs)
    NVIC_ICPR_BASE = 0xE000E280  # Interrupt Clear Pending (8 regs)
    NVIC_IABR_BASE = 0xE000E300  # Interrupt Active Bit (8 regs)
    NVIC_IPR_BASE = 0xE000E400   # Interrupt Priority (60 regs)

    # MPU registers
    MPU_TYPE = 0xE000ED90
    MPU_CTRL = 0xE000ED94
    MPU_RNR = 0xE000ED98
    MPU_RBAR = 0xE000ED9C
    MPU_RASR = 0xE000EDA0

    def _decode_cfsr(self, value: int) -> Dict[str, str]:
        """Decode CFSR bits into human-readable messages."""
        decoded = {}

        # MemManage Fault Status (bits 0-7)
        if value & 0x01:
            decoded["IACCVIOL"] = "Instruction access violation"
        if value & 0x02:
            decoded["DACCVIOL"] = "Data access violation"
        if value & 0x08:
            decoded["MUNSTKERR"] = "MemManage fault on unstacking for return"
        if value & 0x10:
            decoded["MSTKERR"] = "MemManage fault on stacking for exception"
        if value & 0x20:
            decoded["MLSPERR"] = "MemManage fault during FP lazy state preservation"
        if value & 0x80:
            decoded["MMARVALID"] = "MMFAR holds valid fault address"

        # BusFault Status (bits 8-15)
        if value & 0x0100:
            decoded["IBUSERR"] = "Instruction bus error"
        if value & 0x0200:
            decoded["PRECISERR"] = "Precise data bus error"
        if value & 0x0400:
            decoded["IMPRECISERR"] = "Imprecise data bus error"
        if value & 0x0800:
            decoded["UNSTKERR"] = "BusFault on unstacking for return"
        if value & 0x1000:
            decoded["STKERR"] = "BusFault on stacking for exception"
        if value & 0x2000:
            decoded["LSPERR"] = "BusFault during FP lazy state preservation"
        if value & 0x8000:
            decoded["BFARVALID"] = "BFAR holds valid fault address"

        # UsageFault Status (bits 16-31)
        if value & 0x010000:
            decoded["UNDEFINSTR"] = "Undefined instruction"
        if value & 0x020000:
            decoded["INVSTATE"] = "Invalid state (Thumb bit)"
        if value & 0x040000:
            decoded["INVPC"] = "Invalid PC load (bad EXC_RETURN)"
        if value & 0x080000:
            decoded["NOCP"] = "No coprocessor (FPU disabled?)"
        if value & 0x100000:
            decoded["STKOF"] = "Stack overflow detected (ARMv8-M)"
        if value & 0x01000000:
            decoded["UNALIGNED"] = "Unaligned memory access"
        if value & 0x02000000:
            decoded["DIVBYZERO"] = "Divide by zero"

        return decoded

    def _decode_hfsr(self, value: int) -> Dict[str, str]:
        """Decode HFSR bits."""
        decoded = {}
        if value & 0x02:
            decoded["VECTTBL"] = "Vector table read error on exception"
        if value & 0x40000000:
            decoded["FORCED"] = "Forced HardFault (escalated from other fault)"
        if value & 0x80000000:
            decoded["DEBUGEVT"] = "Debug event triggered HardFault"
        return decoded

    def _determine_fault_type(
        self, cfsr: int, hfsr: int
    ) -> str:
        """Determine the high-level fault type."""
        # Check for specific fault types
        if cfsr & 0xFF:  # MemManage
            return "memory_protection_fault"
        if cfsr & 0xFF00:  # BusFault
            return "bus_fault"
        if cfsr & 0x010000:  # Undefined instruction
            return "undefined_instruction"
        if cfsr & 0x020000:  # Invalid state
            return "invalid_state"
        if cfsr & 0x040000:  # Invalid PC
            return "invalid_pc"
        if cfsr & 0x080000:  # No coprocessor
            return "coprocessor_fault"
        if cfsr & 0x01000000:  # Unaligned
            return "unaligned_access"
        if cfsr & 0x02000000:  # Divide by zero
            return "divide_by_zero"
        if hfsr & 0x40000000:  # Forced
            return "escalated_fault"
        if hfsr & 0x02:  # Vector table
            return "vector_table_fault"
        return "unknown_fault"

    async def read_fault_state(self, session: "DebugSession") -> FaultState:
        """Read and decode Cortex-M fault registers.

        Reads CFSR, HFSR, MMFAR, and BFAR to determine the cause
        of a HardFault or other fault exception.

        Args:
            session: Active debug session

        Returns:
            FaultState with decoded fault information
        """
        # Read fault registers
        cfsr_data = await session.read_memory(self.CFSR, 4)
        hfsr_data = await session.read_memory(self.HFSR, 4)
        mmfar_data = await session.read_memory(self.MMFAR, 4)
        bfar_data = await session.read_memory(self.BFAR, 4)

        cfsr = int.from_bytes(cfsr_data, "little")
        hfsr = int.from_bytes(hfsr_data, "little")
        mmfar = int.from_bytes(mmfar_data, "little")
        bfar = int.from_bytes(bfar_data, "little")

        # Decode registers
        decoded = {}
        decoded.update(self._decode_cfsr(cfsr))
        decoded.update(self._decode_hfsr(hfsr))

        # Determine fault address
        fault_address = None
        is_valid = False

        if cfsr & 0x80:  # MMARVALID
            fault_address = mmfar
            is_valid = True
        elif cfsr & 0x8000:  # BFARVALID
            fault_address = bfar
            is_valid = True

        return FaultState(
            fault_type=self._determine_fault_type(cfsr, hfsr),
            fault_address=fault_address,
            is_valid=is_valid,
            raw_registers={
                "CFSR": cfsr,
                "HFSR": hfsr,
                "MMFAR": mmfar,
                "BFAR": bfar,
            },
            decoded=decoded,
        )

    async def decode_exception_frame(
        self, session: "DebugSession", stack_pointer: Optional[int] = None
    ) -> ExceptionFrame:
        """Parse the Cortex-M exception frame from the stack.

        The Cortex-M exception frame contains 8 words:
        R0, R1, R2, R3, R12, LR, PC, xPSR

        For FPU-enabled cores with lazy stacking, there may be
        additional floating-point registers.

        Args:
            session: Active debug session
            stack_pointer: Stack pointer to read from

        Returns:
            ExceptionFrame with stacked registers
        """
        if stack_pointer is None:
            regs = await session.read_registers(["sp"])
            stack_pointer = regs.get("sp", 0)

        # Read 8 words (32 bytes) for basic frame
        frame_data = await session.read_memory(stack_pointer, 32)

        def read_word(offset: int) -> int:
            return int.from_bytes(frame_data[offset : offset + 4], "little")

        registers = {
            "r0": read_word(0),
            "r1": read_word(4),
            "r2": read_word(8),
            "r3": read_word(12),
            "r12": read_word(16),
            "lr": read_word(20),
            "pc": read_word(24),
            "xpsr": read_word(28),
        }

        # Check for extended frame (FPU)
        frame_type = "basic"
        lr = registers["lr"]
        if lr & 0x10 == 0:  # Bit 4 clear = FPU context stacked
            frame_type = "extended_fpu"

        return ExceptionFrame(
            registers=registers,
            return_address=registers["pc"],
            stack_pointer=stack_pointer,
            frame_type=frame_type,
        )

    async def check_interrupt_config(
        self, session: "DebugSession"
    ) -> InterruptAnalysis:
        """Analyze NVIC configuration for issues.

        Checks system handler priorities and detects common
        misconfigurations like PendSV having higher priority than SVCall.

        Args:
            session: Active debug session

        Returns:
            InterruptAnalysis with configuration and warnings
        """
        # Read system handler priorities
        shpr1_data = await session.read_memory(self.SHPR1, 4)
        shpr2_data = await session.read_memory(self.SHPR2, 4)
        shpr3_data = await session.read_memory(self.SHPR3, 4)

        shpr1 = int.from_bytes(shpr1_data, "little")
        shpr2 = int.from_bytes(shpr2_data, "little")
        shpr3 = int.from_bytes(shpr3_data, "little")

        # Extract priorities (higher byte positions, lower values = higher priority)
        priorities = {
            "MemManage": (shpr1 >> 0) & 0xFF,
            "BusFault": (shpr1 >> 8) & 0xFF,
            "UsageFault": (shpr1 >> 16) & 0xFF,
            "SVCall": (shpr2 >> 24) & 0xFF,
            "PendSV": (shpr3 >> 16) & 0xFF,
            "SysTick": (shpr3 >> 24) & 0xFF,
        }

        warnings = []

        # Check for priority inversion issues
        if priorities["PendSV"] < priorities["SVCall"]:
            warnings.append(
                f"PendSV priority ({priorities['PendSV']}) is higher than "
                f"SVCall ({priorities['SVCall']}). This can cause context "
                "switch issues in RTOS implementations."
            )

        if priorities["SysTick"] < priorities["SVCall"]:
            warnings.append(
                f"SysTick priority ({priorities['SysTick']}) is higher than "
                f"SVCall ({priorities['SVCall']}). Time-critical syscalls "
                "may be delayed."
            )

        # Read enabled external interrupts (first 32)
        iser_data = await session.read_memory(self.NVIC_ISER_BASE, 4)
        ispr_data = await session.read_memory(self.NVIC_ISPR_BASE, 4)

        iser = int.from_bytes(iser_data, "little")
        ispr = int.from_bytes(ispr_data, "little")

        enabled = []
        pending = []

        for i in range(32):
            if iser & (1 << i):
                enabled.append(
                    InterruptInfo(number=i, name=f"IRQ{i}", enabled=True)
                )
            if ispr & (1 << i):
                pending.append(
                    InterruptInfo(number=i, name=f"IRQ{i}", pending=True)
                )

        return InterruptAnalysis(
            enabled=enabled,
            pending=pending,
            priorities=priorities,
            warnings=warnings,
        )

    async def get_memory_protection(
        self, session: "DebugSession"
    ) -> MemoryProtectionConfig:
        """Read MPU configuration.

        Reads the Memory Protection Unit configuration to show
        protected regions and their permissions.

        Args:
            session: Active debug session

        Returns:
            MemoryProtectionConfig with region information
        """
        # Read MPU type to check if MPU exists
        mpu_type_data = await session.read_memory(self.MPU_TYPE, 4)
        mpu_type = int.from_bytes(mpu_type_data, "little")

        num_regions = (mpu_type >> 8) & 0xFF

        if num_regions == 0:
            return MemoryProtectionConfig(enabled=False, regions=[])

        # Read MPU control
        mpu_ctrl_data = await session.read_memory(self.MPU_CTRL, 4)
        mpu_ctrl = int.from_bytes(mpu_ctrl_data, "little")

        enabled = bool(mpu_ctrl & 0x01)
        privdefena = bool(mpu_ctrl & 0x04)

        regions = []

        # Read each region
        for i in range(min(num_regions, 16)):
            # Select region
            await session.write_memory(self.MPU_RNR, bytes([i, 0, 0, 0]))

            # Read region config
            rbar_data = await session.read_memory(self.MPU_RBAR, 4)
            rasr_data = await session.read_memory(self.MPU_RASR, 4)

            rbar = int.from_bytes(rbar_data, "little")
            rasr = int.from_bytes(rasr_data, "little")

            if not (rasr & 0x01):  # Region not enabled
                continue

            # Decode RASR
            size_bits = (rasr >> 1) & 0x1F
            size = 1 << (size_bits + 1) if size_bits >= 4 else 0

            ap = (rasr >> 24) & 0x07
            xn = bool(rasr & 0x10000000)

            # Decode access permissions
            ap_map = {
                0: "---",
                1: "RW-",  # Privileged RW
                2: "RW-",  # Both RW (user read-only in some configs)
                3: "RW-",  # Both full access
                5: "R--",  # Privileged read-only
                6: "R--",  # Both read-only
            }
            permissions = ap_map.get(ap, "???")
            if not xn and "X" not in permissions:
                permissions = permissions[:-1] + "X"

            base = rbar & 0xFFFFFFE0

            regions.append(
                MemoryRegion(
                    number=i,
                    base_address=base,
                    size=size,
                    permissions=permissions,
                    enabled=True,
                    attributes={
                        "tex": (rasr >> 19) & 0x07,
                        "shareable": bool(rasr & 0x40000),
                        "cacheable": bool(rasr & 0x20000),
                        "bufferable": bool(rasr & 0x10000),
                    },
                )
            )

        return MemoryProtectionConfig(
            enabled=enabled,
            regions=regions,
            default_permissions="RWX" if privdefena else "---",
        )


# Variants for specific Cortex-M cores
class CortexM0Target(CortexMTarget):
    """Cortex-M0/M0+ specific target.

    M0/M0+ have reduced fault handling (no CFSR, only HardFault).
    """

    name = "cortex-m0"

    async def read_fault_state(self, session: "DebugSession") -> FaultState:
        """Read fault state for M0 (limited fault info)."""
        # M0 only has HFSR, no CFSR
        hfsr_data = await session.read_memory(self.HFSR, 4)
        hfsr = int.from_bytes(hfsr_data, "little")

        decoded = self._decode_hfsr(hfsr)

        return FaultState(
            fault_type="hardfault",
            fault_address=None,
            is_valid=False,
            raw_registers={"HFSR": hfsr},
            decoded=decoded,
        )


class CortexM33Target(CortexMTarget):
    """Cortex-M33 (ARMv8-M) specific target.

    M33 has TrustZone support and additional security features.
    """

    name = "cortex-m33"

    # Additional security registers
    SAU_CTRL = 0xE000EDD0
    SAU_TYPE = 0xE000EDD4
    SAU_RNR = 0xE000EDD8
    SAU_RBAR = 0xE000EDDC
    SAU_RLAR = 0xE000EDE0
