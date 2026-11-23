# ATmega2560 Python Simulator

Python emulator for ATmega2560 and ATmega1280 firmware with instruction execution, peripheral models, a logic probe with an HD44780 LCD decoder, and test tooling.

Disclaimer: this project is experimental and a work in progress. AI tools were used in parts of its generation and ongoing development.

## Python Modules And Scripts In This Directory

This README documents the main top-level entry points plus the simulator support modules:

- `sim.py`
- `sim_constants.py`
- `sim_alu.py`
- `sim_decode.py`
- `sim_gpio.py`
- `sim_memory.py`
- `sim_interrupts.py`
- `sim_peripherals_ctrl.py`
- `sim_peripherals.py`
- `gui.py`
- `run_hex.py`
- `opcode_tester.py`
- `hex_loader.py`
- `avr_encoding.py`
- `sim_probe.py`
- `probe_agent.py`

## Setup

From project root:

```bash
cd "./atmega2560 sim in python"
```

Use the local virtual environment Python:

```bash
.venv-pypy310/bin/python --version
```

This project uses PyPy as the supported interpreter/runtime for simulator execution.

Why `.venv-pypy310`:

- The simulator is tuned and validated on PyPy 3.10.
- Keeping a dedicated virtual environment named `.venv-pypy310` ensures everyone runs the same interpreter family/version and avoids host-Python drift.

First-time setup (new machine/user):

0. Debian/Ubuntu prerequisite (install both interpreter and venv package):

```bash
sudo apt update
sudo apt install pypy3 pypy3-venv
```

1. Install PyPy 3.10 and verify it is available:

```bash
pypy3 --version
```

2. Create the project virtual environment:

```bash
cd "./atmega2560 sim in python"
pypy3 -m venv .venv-pypy310
```

3. Check the interpreter inside the venv:

```bash
.venv-pypy310/bin/python --version
```

4. Optional (if you run pytest-based commands):

```bash
.venv-pypy310/bin/python -m pip install -U pip pytest
```

5. Run the simulator tools with the venv interpreter (examples):

```bash
.venv-pypy310/bin/python sim.py
.venv-pypy310/bin/python gui.py
.venv-pypy310/bin/python run_hex.py --help
```

## Firmware Examples

- `examples/blink/blink.c`: timer-based LED blink on `PB7` using `Timer0` compare-match polling
- `examples/hello_world/hello_world.c`: sends `"Hello, world!"` on `USART0`
- `examples/fibonacci_uart/fibonacci_uart.c`: prints Fibonacci numbers over `USART0`
- `examples/primes_uart/primes_uart.c`: prints prime numbers over `USART0`
- `examples/counter_uart/counter_uart.c`: prints an incrementing 32-bit counter over `USART0`
- `examples/gpio_chaser/gpio_chaser.c`: walks one active bit across `PORTA`
- `examples/timer0_tick_uart/timer0_tick_uart.c`: prints timer ticks from `Timer0` compare-match events
- `examples/adc_poll/adc_poll.c`: polls ADC channels and prints sampled values
- `examples/spi_master_loop/spi_master_loop.c`: runs SPI master transfers and mirrors received byte to `PORTA`
- `examples/eeprom_rw/eeprom_rw.c`: writes/reads EEPROM byte `0x0010` and prints value over `USART0`
- `examples/uart_relay/uart_relay.c`: announces `uart N ready` on all UARTs; any full line received on one UART is broadcast to the other three as `Uart N sent: "..."`
- `examples/uart0_rx_isr/uart0_rx_isr.c`: enables `USART0_RX_vect` and prints `received {...}` for each byte received on `USART0`
- `examples/hwcheck/`: instruction, interrupt and timer checks whose output is compared with a real ATmega2560 (see section 11)
- `examples/Marlin/firmware.hex` (final firmware only): prebuilt Marlin final firmware image for large real-world emulator runs (paired with `examples/Marlin/firmware.elf` for symbols/disassembly labels)

Build example firmware:

```bash
make
make hello
make examples
```

These targets generate both `.elf` and `.hex` files under each `examples/*/` directory.

Run a UART-printing example with bridge (then connect with netcat/telnet):

```bash
.venv-pypy310/bin/python run_hex.py examples/fibonacci_uart/fibonacci_uart.hex --steps 300000 --uart 0 --uart-bridge-port 9000 --show-bridge-status
```

## 1) `run_hex.py`

Runs an Intel HEX firmware image in the emulator, with optional trace output, visual I/O display, and UART TCP bridge.

Basic run:

```bash
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --steps 100000
```

Verbose instruction trace:

```bash
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --steps 2000 --verbose
```

Visual mode:

```bash
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --steps 50000 --visual --visual-every 20 --visual-clear
```

Enable UART bridge on `USART0` port 9000:

```bash
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --uart 0 --uart-bridge-port 9000 --show-bridge-status
```

One-line launch + connect with `nc`:

```bash
(.venv-pypy310/bin/python run_hex.py examples/fibonacci_uart/fibonacci_uart.hex --steps 300000 --uart 0 --uart-bridge-port 9000 --show-bridge-status &) && sleep 1 && nc 127.0.0.1 9000
```

Inject data into UART RX before run:

```bash
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --inject-text "hello\n" --steps 200000
.venv-pypy310/bin/python run_hex.py examples/blink/blink.hex --inject-file ./payload.bin --steps 200000
```

Run an ATmega1280 image (default is `--mcu atmega2560`):

```bash
.venv-pypy310/bin/python run_hex.py firmware.hex --mcu atmega1280 --steps 100000
```

Show all options:

```bash
.venv-pypy310/bin/python run_hex.py --help
```

## 2) `gui.py`

Desktop GUI runner (Tkinter) with:

- Top control bar: `Load .hex/.hx/.bin`, `Run`/`Stop` toggle, `Step`, `Restart`, `Profile` toggle, and `GUI Update` rate slider
- Left pane modes: `FLASH` (`Disassembly` or `Raw`), `RAM`, `EEPROM`, and `Profile`
- Profile mode: RAM/FLASH/EEPROM access heatmap (reads+writes), selectable by space, hover tooltip (`total/reads/writes`), and click-through navigation to the corresponding disassembly/hex row
- Right pane modes: `Registers + Flags`, `UART` (selectable `USART0..USART3` panel), and `ADC`
- Bottom bar: cycle counters and reset counters

Start GUI:

```bash
.venv-pypy310/bin/python gui.py
```

Preload firmware and seed ADC slider values at startup:

```bash
.venv-pypy310/bin/python gui.py --load examples/adc_poll/adc_poll.hex --adc 0=512 --adc ADC3=900
```

Short form is also accepted:

```bash
.venv-pypy310/bin/python gui.py --load examples/adc_poll/adc_poll.hex --adc 0=512,ADC3=900,7=1023
```

Emulate an ATmega1280 instead of the default ATmega2560:

```bash
.venv-pypy310/bin/python gui.py --load firmware.hex --mcu atmega1280
```

`--adc` may be repeated, accepts `0..15` or `ADC0..ADC15`, and each occurrence may contain one or more comma-separated assignments. The slider value is stored even if that channel is currently disabled; the emulator starts using it automatically when ADC/pin mode allows it.

Profile click-through behavior:

- Clicking a FLASH profile cell opens FLASH disassembly at that address.
- Clicking a RAM/EEPROM profile cell opens the corresponding hex view at that address.
- Pressing `Profile` again returns to profile view at the remembered address.
- The destination row keeps the same heatmap color until `Profile` is pressed.

## 3) `opcode_tester.py`

Command-line opcode validation harness. Runs raw opcode words with controlled initial state and assertions on final state.

Simple example:

```bash
.venv-pypy310/bin/python opcode_tester.py --opcodes 0xE005 0xE013 0x0F01 --steps 3
```

Example with setup and expectations:

```bash
.venv-pypy310/bin/python opcode_tester.py \
  --opcodes 0xE005 0xE013 0x0F01 \
  --steps 3 \
  --set-flag C=0 \
  --expect-reg r16=0x08 \
  --expect-cycles 3
```

The command exits non-zero if expectations fail.

Show all options:

```bash
.venv-pypy310/bin/python opcode_tester.py --help
```

## 4) `sim.py`

Primary emulator entry point. It exports `ATmega2560Emulator`, `ATmega1280Emulator`, `create_emulator`, `EMULATORS`, `StepResult`, and `DisassemblyLine`, and composes the simulator from smaller logical modules.

Current simulator module layout:

- `sim.py`: top-level emulator class, runtime reset/init, fetch, execute loop, smoke-test `__main__`
- `sim_constants.py`: AVR/device constants and vector/data-address definitions
- `sim_alu.py`: flag helpers and ALU flag-write logic
- `sim_decode.py`: instruction decode helpers and disassembly support
- `sim_gpio.py`: GPIO, pin-change interrupt, and external interrupt helpers
- `sim_memory.py`: SRAM/I/O memory access, stack, pointers, program loading, snapshots
- `sim_interrupts.py`: interrupt arbitration and ISR entry servicing
- `sim_peripherals_ctrl.py`: ADC, analog comparator, SPI, TWI, EEPROM, UART, and timer-capture helpers

### As a script

`sim.py` contains a built-in smoke demo in `__main__`:

```bash
.venv-pypy310/bin/python sim.py
```

### As a module (normal usage)

```python
from sim import ATmega2560Emulator

emu = ATmega2560Emulator()
emu.load_program_hex("examples/blink/blink.hex")
for _ in range(1000):
    if emu.halted:
        break
    emu.step()
print(emu.pc, emu.cycles)
```

`create_emulator("atmega1280")` (or `"1280"`) returns the emulator for an MCU name.

## 5) `hex_loader.py`

Intel HEX parsing utilities used by the emulator.

Primary API:

- `load_hex_bytes(path: str) -> bytes`

Example:

```python
from hex_loader import load_hex_bytes

image = load_hex_bytes("examples/blink/blink.hex")
print(len(image))
```

Notes:

- Supports HEX record types `00` (data), `01` (EOF), `02` (extended segment address), `04` (extended linear address); start address records `03` and `05` are ignored
- Raises `ValueError` for malformed/unsupported records

## 6) `avr_encoding.py`

Helpers for encoding AVR instructions into opcode words for fixtures and small generated programs.

Example:

```python
from avr_encoding import ldi, add, rjmp

program = [
    ldi(16, 0x05),
    ldi(17, 0x03),
    add(16, 17),
    rjmp(-1),
]
```

Common helpers include `ldi`, `mov`, `add`, `cpi`, `rjmp`, `rcall`, `brbs`, `brbc`, `push`, `pop`, `in_`, `out`, plus multiword helpers like `jmp`, `call`, `lds`, and `sts`.

## 7) `sim_constants.py`, `sim_alu.py`, `sim_decode.py`, `sim_gpio.py`, `sim_memory.py`, `sim_interrupts.py`, `sim_peripherals_ctrl.py`

Internal simulator support modules used by `sim.py`.

Typical usage is through `from sim import ATmega2560Emulator`; these files keep the emulator implementation maintainable and logically separated.

## 8) `sim_peripherals.py`

Peripheral component models used by `sim.py` (timers, UART models, watchdog, etc.).

Typical usage is through `ATmega2560Emulator`; direct import is mainly for development and unit tests.

Example:

```python
from sim_peripherals import UART0

# Usually managed by sim.py; direct use is advanced/test-focused.
uart = UART0()
```

## 9) ATmega1280

`ATmega1280Emulator` (in `sim.py`) is the ATmega2560 model with 128 KiB of flash. Select it with `--mcu atmega1280` in `run_hex.py`, `gui.py` and `probe_agent.py`, or `create_emulator("atmega1280")` from Python.

The two differ in program counter width, which changes the stack and the timing of calls, returns and interrupts:

| | ATmega1280 (16-bit PC) | ATmega2560 (22-bit PC) |
|---|---|---|
| Return address on the stack | 2 bytes | 3 bytes |
| `CALL` | 4 cycles | 5 cycles |
| `RCALL`, `ICALL` | 3 cycles | 4 cycles |
| `EICALL` | — | 4 cycles |
| `RET`, `RETI` | 4 cycles | 5 cycles |
| Interrupt entry | 4 cycles | 4 cycles |

## 10) `sim_probe.py` and `probe_agent.py`

A logic probe and LCD protocol decoder:

- `PinProbe` records every level change of chosen pins (or of every port pin) with its CPU cycle.
- `ShiftRegisterDecoder` turns data/clock/latch pins into 74HC595 outputs and checks its timing.
- `HD44780Decoder` runs a 4-bit HD44780 from those outputs, renders the screen and checks the datasheet bus, execution and initialization timings.
- `LCD_PRESETS["mightyboard_revg"]` is the MakerBot MightyBoard Rev G/H (Replicator 2/2X) interface board, including the input levels the board puts on the MCU (interface detect and buttons).

One run with a JSON report (screen, timing minimums and violations, init sequence):

```bash
.venv-pypy310/bin/python probe_agent.py run firmware.hex --mcu atmega1280 --ms 3000 --out report.json
```

`--lcd` picks the preset (default `mightyboard_revg`, `''` for none), `--until-text` stops once the LCD shows that text, and `--log N` adds the first N decoded LCD instructions to the report. The screen reads `(LCD not powered)` until the firmware switches the panel's power pin on, so run long enough for the firmware to get there.

`--all-pins` probes every pin of every port and adds edge counts per pin, to see which port bits a firmware really drives.

Agent interface (one JSON request per line over TCP; commands are listed in the `probe_agent.py` docstring):

```bash
.venv-pypy310/bin/python probe_agent.py serve --port 9100
printf '%s\n' '{"cmd":"load","hex":"fw.hex","mcu":"atmega1280"}' '{"cmd":"run","ms":3000}' '{"cmd":"lcd"}' | nc 127.0.0.1 9100
```

## 11) Timing model and hardware comparison

The timing below was measured on a real ATmega2560 (Arduino Mega 2560 R3) with `examples/hwcheck`, and `tests/test_hwcheck.py` keeps the simulator in step with that chip's recorded output:

- An I/O register write takes effect at the end of its instruction. A read samples at the start of the instruction's last cycle.
- An interrupt is taken at the end of an instruction if it was already pending and enabled one cycle before that end, and the entry takes 4 cycles. So `SEI`, `RETI` and unmasking let one more instruction run first, and a flag set in the last cycle of an instruction waits for the next one.
- Interrupts are served in vector order (Timer2, Timer1, Timer0, SPI, USART0, ... USART3). TXC, ADIF and SPIF are cleared when their vector is entered.
- A timer compare flag is set on the timer clock after the match, so a period is TOP + 1 clocks in every mode (2 x TOP in the phase-correct modes). A TCNT write blocks the match on the next clock.
- The 16-bit timers implement all sixteen waveform modes (counting and the TOV/OCF/ICF flags; not the OCnx pins or the OCR double buffering of the PWM modes).
- Timer0, 1, 3, 4 and 5 share one prescaler. It only runs while at least one of them has a clock selected, and `GTCCR.PSRSYNC` resets it.
- 16-bit timer registers go through the timer's TEMP high byte: write high then low, read low then high.
- `SLEEP` needs `SMCR.SE`. In idle mode the peripherals keep running, and a wake-up interrupt is entered 7 cycles after it becomes pending (1 when awake). The deeper modes stop everything but the watchdog and the pin interrupts.
- `EECR.EERE` halts the CPU for 4 cycles and `EEPE` for 2. A write takes 3.3 ms (1.8 ms for erase-only or write-only).
- `SBI` / `CBI` on PINx or on an interrupt flag register (TIFR0-5, EIFR, PCIFR) act on the named bit only.
- An SPI byte takes 8 SCK periods plus 1 cycle (measured at f/2, f/4, f/8, f/16 and f/64).
- A USART frame takes its real time: the start bit begins on the next baud-generator tick (period UBRR + 1 cycles) and each bit lasts 16 ticks, or 8 with U2X. A second byte waits in UDR and follows without a gap. Frame length and tick alignment match the chip; the exact cycle on which a polled write lands after earlier output is not always reproduced.

Not measured, from the datasheet: INT0-7 follow their pins (PD0-3, PE4-7), including a low level that keeps interrupting; PCINT8 is PE0 and PCINT9-15 are PJ0-6; the watchdog stays enabled after a watchdog reset until `MCUSR.WDRF` is cleared; the first ADC conversion takes 25 ADC clocks and later ones 13, with free-running mode and the ADCL/ADCH read lock; TWI bytes take nine SCL periods, and `set_twi_devices([...])` makes other addresses answer with NACK.

See `examples/hwcheck/README.md` to run the comparison on a board.

## Running Tests

Run full suite:

```bash
.venv-pypy310/bin/python -m unittest discover -s tests -v
```

For detailed test docs, see:

- `tests/README.md`

## Typical Workflow

1. Build or obtain a HEX file (for example `make examples` to build the full example suite).
2. Run it with `run_hex.py`.
3. Use `opcode_tester.py` for targeted opcode-level checks.
4. Run the full `unittest` suite before committing changes.
