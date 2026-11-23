# hwcheck: simulator against a real ATmega2560

`hwcheck.hex` runs 125 small checks of instruction timing, interrupt behaviour, timers, sleep, EEPROM, SPI, USART and register access, and prints one `name=value` line (hex) per check on USART0 at 115200 baud. The same image runs on a real chip and in the simulator, so the two outputs can be compared line by line.

`atmega2560_hardware.txt` is the output of an Arduino Mega 2560 R3 (16 MHz). `tests/test_hwcheck.py` runs the image in the simulator and requires every value to match it.

The firmware drives no pins as outputs except USART0 TX. It briefly enables pull-ups on PA0-PA2 and PB0, so leave those unconnected. Each run writes one EEPROM cell (the last one, 0x0FFF).

Build:

```bash
avr-gcc -mmcu=atmega2560 -DF_CPU=16000000UL -Os -o hwcheck.elf main.c tests.S
avr-objcopy -O ihex -R .eeprom hwcheck.elf hwcheck.hex
```

Run on a Mega 2560 (this overwrites the sketch on the board), then read the port at 115200:

```bash
avrdude -p atmega2560 -c wiring -P /dev/ttyACM0 -b 115200 -D -U flash:w:hwcheck.hex:i
```

Run in the simulator:

```bash
.venv-pypy310/bin/python run_hex.py examples/hwcheck/hwcheck.hex --steps 900000
```

What the checks cover:

| Check | Meaning |
|---|---|
| `base`, `nop`, `rcall_ret`, `call_ret`, `icall_ret`, `eicall_ret` | cycles of the sequence, counted by Timer1 at clk/1 |
| `irq_latency`, `irq_lat2_*`, `irq_lat3_*` | cycles from a Timer1 compare value to the first sample in its ISR, with 1-, 2- and 3-cycle instructions running |
| `irq_sei`, `irq_mask` | the same from `SEI` and from unmasking with the flag already set |
| `reti_gap` | main-program instructions run between `RETI` and the next pending interrupt |
| `prio_t0/t1/t2` | order in which three pending timer interrupts are served |
| `tifr_before`, `tifr_sbi`, `tifr_cbi` | TIFR0 after `SBI` / `CBI` on one flag |
| `ctc0_*`, `ctc1_*` | TCNT after a fixed delay in CTC mode (period OCR + 1) |
| `start_read0`, `start_read1` | TCNT read by the instruction after the one that starts the timer |
| `temp` | 16-bit timer TEMP high-byte latch |
| `spi_polls`, `spif` | SPI byte time at f/4; SPIF cleared by its interrupt |
| `adif`, `txc` | ADIF and TXC0 cleared by their interrupts |
| `fmul*` | C and Z after FMUL / FMULS / FMULSU |
| `pin_sbi`, `pin_cbi` | PORTA after `SBI` / `CBI` on PINA |
| `sreg_mem`, `reg_mem` | SREG and a register read through data-space addresses |
| `ucsr0a_u2x` | U2X0 read back from UCSR0A |
| `sleep_idle`, `sleep_nose` | interrupt latency out of idle sleep; `SLEEP` without `SMCR.SE` |
| `m4`, `m12`, `m14`, `m15`, `m8`, `m10`, `m11`, `m1`, `m5` + `a`/`b`/`f` | Timer1 in that waveform mode: TCNT1L after two delays, and TIFR1 |
| `icr_normal` | ICR1 written and read back in normal mode |
| `irq_lat_pc` | compare interrupt latency in phase-correct PWM |
| `presc_*`, `prescb_*`, `prescd_*`, `presce_*`, `pf`, `ph`, `pi`, `gtccr` | phase of clk/8 ticks after a prescaler reset, a start, a stop/restart and with all timers stopped |
| `spi_f2` ... `spi_f64` | first cycle (plus one) after the SPDR write at which SPIF reads as set |
| `uart_udre_*` | cycles from a UDR0 write on an idle transmitter to the data-register-empty interrupt |
| `eere`, `eepe`, `eeread_val` | cycles of the EEPROM read and write strobes; the value read back |
