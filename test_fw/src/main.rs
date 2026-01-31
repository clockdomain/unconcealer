//! Minimal Cortex-M3 test firmware for unconcealer
//!
//! This firmware is designed to test the GDB bridge functionality.
//! It runs on QEMU's lm3s6965evb machine.

#![no_std]
#![no_main]

use cortex_m::asm;
use cortex_m_rt::entry;
use panic_halt as _;

/// A simple counter for debugging
static mut COUNTER: u32 = 0;

/// A test variable in RAM
static mut TEST_VALUE: u32 = 0xDEADBEEF;

#[entry]
fn main() -> ! {
    // Initialize test value
    unsafe {
        TEST_VALUE = 0x12345678;
    }

    loop {
        // Increment counter
        unsafe {
            COUNTER = COUNTER.wrapping_add(1);
        }

        // Small delay loop
        for _ in 0..1000 {
            asm::nop();
        }

        // Trigger a breakpoint for testing (optional)
        // Uncomment to test breakpoint handling:
        // asm::bkpt();
    }
}

/// Function to trigger a HardFault for testing
#[allow(dead_code)]
fn trigger_hardfault() {
    // Read from invalid address to cause HardFault
    unsafe {
        let invalid_ptr: *const u32 = 0xFFFF_FFFF as *const u32;
        core::ptr::read_volatile(invalid_ptr);
    }
}

/// Test function for setting breakpoints
#[no_mangle]
pub fn test_function() -> u32 {
    unsafe { COUNTER }
}
