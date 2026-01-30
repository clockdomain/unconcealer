"""Pytest fixtures for Unconcealer tests."""

import pytest
from pathlib import Path


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
