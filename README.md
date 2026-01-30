# Unconcealer

AI-powered embedded systems debugger using Claude and QEMU/GDB.

## Installation

### From GitHub

```bash
pip install git+https://github.com/clockdomain/unconcealer.git
```

### From source

```bash
git clone https://github.com/clockdomain/unconcealer.git
cd unconcealer
pip install -e .
```

## Usage

```bash
unconcealer debug firmware.elf --target cortex-m4
unconcealer analyze firmware.elf --fault hardfault
unconcealer version
```

## Development

```bash
git clone https://github.com/clockdomain/unconcealer.git
cd unconcealer
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```
