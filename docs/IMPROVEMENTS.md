# Unconcealer: Usability Improvements

Based on testing the tool, here are the key issues and suggested improvements.

---

## 1. No Standalone/Headless Mode

**Problem:** The tool is tightly coupled to Claude Desktop via MCP. There's no way to:
- Test the debugger without Claude Desktop
- Use it programmatically without an LLM
- Run a quick smoke test to verify installation

**Current state:**
- `unconcealer debug` requires an LLM API key
- `unconcealer mcp-server` only works with MCP protocol over stdin/stdout
- No simple CLI to just "connect to firmware and poke around"

**Suggested improvements:**

```bash
# Add a headless interactive mode
unconcealer shell firmware.elf

# Add a smoke test command
unconcealer test firmware.elf --quick

# Add a scripted mode
unconcealer run script.txt firmware.elf
```

---

## 2. MCP Server Testing is Difficult

**Problem:** Testing the MCP server manually is awkward because:
- It expects newline-delimited JSON-RPC over stdin
- Shell piping doesn't handle the async responses well
- No way to send commands interactively

**Suggested improvements:**

```bash
# Add a REPL mode for MCP testing
unconcealer mcp-server --repl

# Add a test mode that runs predefined commands
unconcealer mcp-server --self-test

# Better error messages when JSON is malformed
```

---

## 3. Documentation Lists Non-Existent Tools

**Problem:** `CLAUDE-DESKTOP.md` mentions tools that aren't implemented in `stdio_server.py`:

| Documented Tool | Status |
|-----------------|--------|
| `set_watchpoint` | Missing |
| `list_breakpoints` | Missing |
| `show_source` | Missing |
| `search_source` | Missing |
| `disassemble` | Missing |
| `list_locals` | Missing |
| `show_nvic` | Missing (have `check_interrupt_priorities`) |
| `show_mpu` | Missing (have `show_memory_protection`) |
| `build_causal_chain` | Missing |
| `validate_fix_hypothesis` | Missing |
| `test_fix_removal` | Missing |
| `find_corruption_iteration` | Missing |
| `track_register_changes` | Missing |
| `check_barrier_usage` | Missing |
| `add_comparison_target` | Missing |
| `compare_execution` | Missing |
| `list_snapshots` | Missing |
| `delete_snapshot` | Missing |

**Suggested fix:** Either implement the missing tools or update the documentation to reflect what's actually available.

---

## 4. No Simple "Does It Work?" Verification

**Problem:** After installation, there's no quick way to verify everything works.

**Suggested improvements:**

```bash
# Verify all dependencies
unconcealer doctor

# Expected output:
# ✓ Python 3.10.12
# ✓ QEMU qemu-system-arm 8.0.0
# ✓ GDB gdb-multiarch 12.1
# ✓ Test firmware found
# ✓ MCP server starts correctly
# ✓ Can launch QEMU and connect GDB
# All checks passed!
```

---

## 5. Error Messages Need Context

**Problem:** When things fail, the error messages don't help diagnose the issue.

**Example:** If GDB isn't found, the error should say:
```
Error: GDB not found at 'gdb-multiarch'
Try: --gdb-path /path/to/arm-none-eabi-gdb
Or install: sudo apt install gdb-multiarch
```

Not just:
```
Error: Failed to start session
```

---

## 6. Missing Integration Test for the Full Flow

**Problem:** The pytest tests mock everything. There's no test that actually:
1. Starts QEMU with real firmware
2. Connects GDB
3. Reads registers
4. Sets breakpoints
5. Steps through code

**Suggested improvement:** Add an integration test that runs with real QEMU:

```bash
pytest tests/ -m integration --run-integration
```

This already exists in the README but requires manual QEMU setup. It should be automated.

---

## 7. Session Management UX

**Problem:** Multi-session support is implemented but the UX is unclear:
- How do I switch between sessions?
- How do I see which session is "current"?
- What happens if I start a second session without stopping the first?

**Suggested improvements:**
- Add `switch_session` tool
- Show current session in `list_sessions` output (done, but with `*` which is subtle)
- Add a `session_status` tool for detailed info

---

## 8. Snapshot Reliability

**Problem:** Snapshots require QEMU to support them, which depends on the machine type and QEMU version. This isn't clear to users.

**Suggested improvement:** Document which QEMU machines support snapshots, and give a clear error when they don't:
```
Error: Snapshots not supported on machine 'lm3s6965evb'
Hint: Use 'mps2-an385' for snapshot support
```

---

## Summary: Priority Improvements

1. **High:** Add `unconcealer doctor` command to verify installation
2. **High:** Add `unconcealer shell` for headless interactive debugging
3. **High:** Sync documentation with actual implemented tools
4. **Medium:** Add automated integration tests
5. **Medium:** Improve error messages with actionable hints
6. **Low:** Add MCP REPL mode for testing
