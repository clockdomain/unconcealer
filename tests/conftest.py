"""Pytest fixtures for Unconcealer tests."""

import pytest
import subprocess
from pathlib import Path

# Path to test firmware (relative to repo root)
TEST_FW_DIR = Path(__file__).parent.parent / "test_fw"
TEST_FW_ELF = TEST_FW_DIR / "target/thumbv7m-none-eabi/release/test_fw"


def _build_test_firmware() -> bool:
    """Attempt to build the test firmware. Returns True if successful."""
    try:
        result = subprocess.run(
            ["cargo", "build", "--release"],
            cwd=TEST_FW_DIR,
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture(scope="session")
def test_firmware_path() -> Path:
    """Get path to test firmware, building if necessary.

    Skips the test if firmware cannot be built.
    """
    if TEST_FW_ELF.exists():
        return TEST_FW_ELF

    # Try to build it
    if _build_test_firmware() and TEST_FW_ELF.exists():
        return TEST_FW_ELF

    pytest.skip(
        f"Test firmware not found at {TEST_FW_ELF}. "
        f"Build it with: cd {TEST_FW_DIR} && cargo build --release"
    )


@pytest.fixture
def sample_elf_path(tmp_path: Path) -> Path:
    """Return a path for test ELF files."""
    return tmp_path / "test.elf"


@pytest.fixture
def debug_config():
    """Return a default debug configuration for testing."""
    from unconcealer.core.types import DebugConfig
    return DebugConfig(
        elf_path=Path("/tmp/test.elf"),
        target="cortex-m4",
    )
