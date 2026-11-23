# Test Suite Documentation

This directory contains unit and integration tests for the ATmega2560 / ATmega1280 Python simulator.

The simulator is now organized as a small set of top-level modules composed by `sim.py`:

- `sim.py`: public emulator entry point and execute loop
- `sim_constants.py`: constants and device mapping
- `sim_alu.py`: ALU/flag helpers
- `sim_decode.py`: decode and disassembly helpers
- `sim_gpio.py`: GPIO and interrupt-edge helpers
- `sim_memory.py`: memory/I/O/stack/program loading helpers
- `sim_interrupts.py`: interrupt arbitration and ISR servicing
- `sim_peripherals_ctrl.py`: ADC/SPI/TWI/EEPROM/UART/peripheral control helpers

Most tests should continue importing `ATmega2560Emulator` from `sim`, not from the internal helper modules.

## Prerequisites

Run commands from the project root:

```bash
cd "./atmega2560 sim in python"
```

Use the project virtual environment Python:

```bash
.venv-pypy310/bin/python --version
```

## How To Run Tests

Run the full test suite:

```bash
.venv-pypy310/bin/python -m unittest discover -s tests -v
```

Equivalent `pytest` run, if `pytest` is installed in the virtual environment:

```bash
.venv-pypy310/bin/python -m pytest tests -q
```

Run one test module:

```bash
.venv-pypy310/bin/python -m unittest tests.test_timer0 -v
```

Run one specific test class:

```bash
.venv-pypy310/bin/python -m unittest tests.test_timer0.TestTimer0 -v
```

Run one specific test method:

```bash
.venv-pypy310/bin/python -m unittest tests.test_timer0.TestTimer0.test_normal_mode_overflow_and_interrupt -v
```

## Test Inventory

- `test_adc.py`: ADC controller behavior (`ADMUX`, `ADCSRA`, `ADCSRB`, result registers, conversion and interrupt behavior).
- `test_analog_comparator.py`: Analog comparator behavior (`ACSR`), flag/interrupt behavior, and Timer1 capture routing baseline.
- `test_atmega1280.py`: ATmega1280 model and `create_emulator`; 2-byte return addresses, and call/return/interrupt cycle counts on both MCUs (16-bit vs 22-bit PC).
- `test_core_invariants.py`: Emulator core invariants and sanity checks.
- `test_cycles.py`: AVR instruction cycle-count behavior checks.
- `test_eeprom.py`: EEPROM controller register behavior, read/write gating windows, completion, and ready interrupt behavior.
- `test_examples_firmware.py`: Compiled firmware integration regressions for UART-visible outputs (`fibonacci_uart`, `primes_uart`, `counter_uart`) to catch real compiler-generated arithmetic/control-flow issues.
- `test_external_interrupts.py`: External interrupt controller behavior for `INT0..INT7` (`EICRA/EICRB`, `EIFR/EIMSK`, dispatch behavior).
- `test_flags.py`: Arithmetic/logic flag semantics (`SREG` behavior), including carry/borrow chain behavior (`ADC/SBC/CPC/SBCI`) and shift/rotate flag behavior (`LSR/ASR/ROR/ROL`).
- `test_gpio.py`: GPIO read/write baseline behavior, pull-ups, toggle semantics, and external-drive release handling.
- `test_gpio_altfunc.py`: Alternate-function pin ownership and waveform-level pin behavior (UART TX, SPI SCK/MOSI, TWI SDA/SCL).
- `test_hex_loader.py`: Intel HEX loading and image mapping behavior.
- `test_hwcheck.py`: runs `examples/hwcheck/hwcheck.hex` and compares all 44 values with the output of a real ATmega2560.
- `test_int0.py`: Focused `INT0` behavior tests.
- `test_interrupts.py`: Generic ISR dispatch/priority and interrupt control flow tests.
- `test_isr_firmware.py`: ISR-driven firmware integration-style patterns.
- `test_opcode_tester.py`: Opcode matrix verification harness behavior and decode/execute coverage checks.
- `test_pcint.py`: Pin-change interrupt (`PCINT0..2`) mask/flag/dispatch behavior.
- `test_run_hex.py`: `run_hex.py` integration tests including UART TCP bridge behavior.
- `test_spi.py`: SPI controller (`SPCR`, `SPSR`, `SPDR`) transfer/flags/collision/interrupt behavior.
- `test_timer0.py`: Timer0 modes, counting, flags, and interrupt behavior.
- `test_timer1.py`: Timer1 counting/capture/compare/overflow behavior and interrupt behavior.
- `test_timer2.py`: Timer2 synchronous and async-baseline behavior with compare/overflow interrupts.
- `test_timer3.py`: Timer3 counting/capture/compare/overflow behavior and interrupt behavior.
- `test_timer4.py`: Timer4 counting/capture/compare/overflow behavior and interrupt behavior.
- `test_timer5.py`: Timer5 counting/capture/compare/overflow behavior and interrupt behavior.
- `test_twi.py`: TWI/I2C controller (`TWBR`, `TWSR`, `TWDR`, `TWCR`) start/address/data/status/interrupt behavior.
- `test_uart0.py`: USART0 TX/RX/flag/interrupt behavior.
- `test_uart_multi.py`: Additional UART instance coverage (`USART1..USART3`) and multi-UART behavior.
- `test_watchdog.py`: Watchdog configuration window, timeout, interrupt/reset/combined mode behavior.

## Useful Run Patterns

Run all tests matching a keyword (example: timer):

```bash
.venv-pypy310/bin/python -m unittest discover -s tests -p "test_*timer*.py" -v
```

Run only peripheral bus tests (example set):

```bash
.venv-pypy310/bin/python -m unittest tests.test_spi tests.test_twi tests.test_uart0 tests.test_uart_multi -v
```

Run firmware-output integration regressions:

```bash
.venv-pypy310/bin/python -m unittest tests.test_examples_firmware -v
```

## Notes

- The suite is `unittest`-based (no `pytest` required).
- If a single test fails, rerun that test method first, then rerun the full suite before committing changes.
- Refactors that move code between `sim_*.py` modules should not change the public import path used by tests unless the test is intentionally exercising internal structure.
