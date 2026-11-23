"""Sleep, pin-driven external interrupts, PCINT1 mapping, watchdog after reset,
timer modes and the shared prescaler."""

import unittest

from avr_encoding import ldi, out
from sim import ATmega2560Emulator

SLEEP = 0x9588
SEI = 0x9478
RETI = 0x9518
RJMP_SELF = 0xCFFF


class TestSleep(unittest.TestCase):
    def test_sleep_without_se_is_a_nop(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([SLEEP, 0x0000])
        emu.step()
        self.assertEqual(emu.pc, 1)
        self.assertFalse(emu.halted)

    def test_sleep_with_interrupts_disabled_halts(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([SLEEP, 0x0000])
        emu.data[emu.DATA_SMCR] = 0x01
        emu.step()
        self.assertTrue(emu.halted)

    def test_idle_sleep_wakes_on_timer_interrupt_and_continues(self) -> None:
        emu = ATmega2560Emulator()
        program = [SEI, SLEEP, ldi(16, 0x5A), RJMP_SELF] + [0x0000] * 60
        program[emu.VECTOR_TIMER0_OVF] = RETI
        emu.load_program_words(program)
        emu.data[emu.DATA_SMCR] = 0x01      # SE, idle mode
        emu.data[0x20 + 0x25] = 0x01        # TCCR0B clk/1: the timer runs during idle sleep
        emu.data[0x006E] = 0x01             # TIMSK0 TOIE0

        emu.step()  # SEI
        emu.step()  # SLEEP
        for _ in range(400):
            result = emu.step()
            if result.description != "SLEEP":
                break
        self.assertEqual(emu.pc, 2)         # RETI came back to the instruction after SLEEP
        self.assertEqual(emu.data[0x20 + 0x15] & 0x01, 0)  # TOV0 was served
        emu.step()
        self.assertEqual(emu.reg[16], 0x5A)

    def test_power_down_stops_the_timers(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([SEI, SLEEP, 0x0000])
        emu.data[emu.DATA_SMCR] = 0x05      # SE, power-down
        emu.data[0x20 + 0x25] = 0x01
        emu.step()
        emu.step()
        tcnt = emu.data[0x20 + 0x26]
        for _ in range(50):
            emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], tcnt)
        self.assertEqual(emu.pc, 2)


class TestExternalInterruptPins(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)
        emu._set_flag(emu.FLAG_I, 1)
        return emu

    def test_set_pin_level_on_pd2_triggers_int2(self) -> None:
        emu = self._new_emu()
        emu.data[emu.DATA_EICRA] = 0b11 << 4            # INT2 rising edge
        emu.data[0x20 + emu.IO_EIMSK] = 1 << 2
        emu.set_pin_level("D", 2, 1)
        emu.step()
        self.assertEqual(emu.pc, emu.VECTOR_INT2)

    def test_firmware_driving_the_pin_triggers_the_interrupt(self) -> None:
        emu = ATmega2560Emulator()
        # DDRE = PORTE = 0x10: PE4 (INT4) driven high by the firmware.
        emu.load_program_words([ldi(16, 0x10), out(0x0D, 16), out(0x0E, 16), 0x0000, 0x0000] + [0x0000] * 60)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[emu.DATA_EICRB] = 0b11                 # INT4 rising edge
        emu.data[0x20 + emu.IO_EIMSK] = 1 << 4
        for _ in range(5):
            emu.step()
            if emu.pc == emu.VECTOR_INT4:
                break
        self.assertEqual(emu.pc, emu.VECTOR_INT4)

    def test_low_level_interrupt_repeats_while_the_pin_is_low(self) -> None:
        emu = self._new_emu()
        program = [0x0000] * 64
        program[emu.VECTOR_INT0] = RETI
        emu.load_program_words(program)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x2B] = 0x01                           # pull-up on PD0: pin high
        emu._extint_dirty = True
        emu.data[0x20 + emu.IO_EIMSK] = 0x01            # INT0, low level (EICRA = 0)
        emu.step()
        self.assertEqual(emu.pc, 1)                     # high: nothing

        emu.set_pin_level("D", 0, 0)
        entries = 0
        for _ in range(12):
            emu.step()
            if emu.pc == emu.VECTOR_INT0:
                entries += 1
        self.assertGreaterEqual(entries, 3)
        self.assertEqual(emu.data[0x20 + emu.IO_EIFR] & 0x01, 0)  # a level interrupt has no flag

        emu.set_pin_level("D", 0, 1)
        emu.step()                                      # the RETI or NOP in progress
        emu.step()
        pc = emu.pc
        emu.step()
        self.assertEqual(emu.pc, pc + 1)                # no more entries


class TestPCINT1Mapping(unittest.TestCase):
    def test_pcint8_is_pe0_and_pcint9_is_pj0(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 16)
        pcifr = 0x20 + emu.IO_PCIFR

        emu.data[emu.DATA_PCMSK1] = 1 << 0              # PCINT8
        emu.set_pin_level("J", 0, 1)
        emu.step()
        self.assertEqual(emu.data[pcifr] & 0x02, 0)
        emu.set_pin_level("E", 0, 1)
        emu.step()
        self.assertEqual(emu.data[pcifr] & 0x02, 0x02)

        emu.data[pcifr] = 0
        emu.data[emu.DATA_PCMSK1] = 1 << 1              # PCINT9 = PJ0
        emu.set_pin_level("J", 0, 0)
        emu.step()
        self.assertEqual(emu.data[pcifr] & 0x02, 0x02)


class TestWatchdogAfterReset(unittest.TestCase):
    def test_watchdog_stays_enabled_after_a_watchdog_reset(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([RJMP_SELF])
        wdt = emu.watchdog
        emu.data[wdt.DATA_WDTCSR] = 1 << wdt.WDE_BIT    # 16 ms reset mode
        wdt.kick(emu.data)
        for _ in range(130_000):
            emu.step()
            if emu.watchdog_reset_count:
                break
        self.assertEqual(emu.watchdog_reset_count, 1)
        self.assertEqual(emu.data[wdt.DATA_MCUSR] & (1 << wdt.WDRF_BIT), 1 << wdt.WDRF_BIT)
        self.assertEqual(emu.data[wdt.DATA_WDTCSR] & (1 << wdt.WDE_BIT), 1 << wdt.WDE_BIT)

        # Without clearing MCUSR the firmware can't switch it off, so it resets again.
        emu._data_write(wdt.DATA_WDTCSR, (1 << wdt.WDCE_BIT) | (1 << wdt.WDE_BIT))
        emu._data_write(wdt.DATA_WDTCSR, 0)
        self.assertEqual(emu.data[wdt.DATA_WDTCSR] & (1 << wdt.WDE_BIT), 1 << wdt.WDE_BIT)
        for _ in range(130_000):
            emu.step()
            if emu.watchdog_reset_count == 2:
                break
        self.assertEqual(emu.watchdog_reset_count, 2)


class TestTimer1Modes(unittest.TestCase):
    """Counting sequence of the ICR/OCR-TOP modes (flags are covered by examples/hwcheck)."""

    def _run(self, tccr1a: int, tccr1b_mode: int, top: int, cycles: int) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * (cycles + 4))
        emu.data[0x0080] = tccr1a
        emu.data[0x0086] = top & 0xFF                   # ICR1
        emu.data[0x0087] = top >> 8
        emu.data[0x0088] = top & 0xFF                   # OCR1A
        emu.data[0x0089] = top >> 8
        emu.data[0x0081] = tccr1b_mode | 0x01           # clk/1
        for _ in range(cycles):
            emu.step()
        return emu

    def test_ctc_with_icr_top(self) -> None:            # mode 12
        emu = self._run(0x00, 0x18, 99, 250)
        self.assertEqual(emu.data[0x0084], 50)          # period 100
        self.assertEqual(emu.data[0x20 + 0x16] & 0x21, 0x20)  # ICF1 at TOP, no TOV1

    def test_fast_pwm_with_icr_top(self) -> None:       # mode 14
        emu = self._run(0x02, 0x18, 99, 250)
        self.assertEqual(emu.data[0x0084], 50)
        self.assertEqual(emu.data[0x20 + 0x16] & 0x21, 0x21)

    def test_fast_pwm_with_ocr_top(self) -> None:       # mode 15
        emu = self._run(0x03, 0x18, 99, 250)
        self.assertEqual(emu.data[0x0084], 50)

    def test_phase_correct_with_icr_top(self) -> None:  # mode 10: 0..50..0 is 100 clocks
        emu = self._run(0x02, 0x10, 50, 70)
        self.assertEqual(emu.data[0x0084], 30)          # on the way down
        emu = self._run(0x02, 0x10, 50, 112)
        self.assertEqual(emu.data[0x0084], 12)          # second ramp up


class TestSharedPrescaler(unittest.TestCase):
    def test_prescaler_phase_is_shared_and_pauses_with_all_timers_stopped(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)
        emu.data[0x0081] = 0x02                         # Timer1 clk/8
        for _ in range(5):
            emu.step()
        emu.data[0x20 + 0x25] = 0x02                    # Timer0 clk/8, 5 cycles later
        for _ in range(3):
            emu.step()
        # Both count the same prescaler edge, 8 cycles after Timer1 started.
        self.assertEqual(emu.data[0x0084], 1)
        self.assertEqual(emu.data[0x20 + 0x26], 1)

        emu.data[0x0081] = 0
        emu.data[0x20 + 0x25] = 0
        for _ in range(21):                             # all stopped: the prescaler holds its count
            emu.step()
        emu.data[0x20 + 0x25] = 0x02
        for _ in range(7):
            emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], 1)
        emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], 2)

    def test_gtccr_psrsync_resets_the_prescaler(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)
        emu.data[0x20 + 0x25] = 0x02
        for _ in range(5):
            emu.step()
        emu._data_write(emu.DATA_GTCCR, 0x01)
        self.assertEqual(emu.data[emu.DATA_GTCCR], 0)   # reads back as 0
        for _ in range(7):
            emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], 0)
        emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], 1)


class TestUARTFrameTiming(unittest.TestCase):
    def test_frame_time_follows_ubrr_u2x_and_format(self) -> None:
        emu = ATmega2560Emulator()
        uart = emu.uart0
        emu.data[uart.DATA_UBRRL] = 16
        emu.data[uart.DATA_UCSRA] |= 0x02               # U2X
        self.assertEqual(uart.frame_cycles(emu.data), 10 * 8 * 17)   # 8N1 at 115200 / 16 MHz
        emu.data[uart.DATA_UCSRA] &= ~0x02
        emu.data[uart.DATA_UCSRC] = 0x2E                # 8 data bits, even parity, 2 stop bits
        self.assertEqual(uart.frame_cycles(emu.data), 12 * 16 * 17)

    def test_second_byte_waits_in_udr_until_the_first_frame_ends(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([RJMP_SELF])
        uart = emu.uart0
        emu._data_write(uart.DATA_UCSRB, 1 << uart.TXEN_BIT)
        emu._data_write(uart.DATA_UDR, 0x41)
        self.assertEqual((emu.data[uart.DATA_UCSRA] >> uart.UDRE_BIT) & 1, 1)
        emu._data_write(uart.DATA_UDR, 0x42)
        self.assertEqual((emu.data[uart.DATA_UCSRA] >> uart.UDRE_BIT) & 1, 0)
        for _ in range(85):                             # one frame
            emu.step()
        self.assertEqual(uart.tx_log, [0x41])
        self.assertEqual((emu.data[uart.DATA_UCSRA] >> uart.UDRE_BIT) & 1, 1)
        self.assertEqual((emu.data[uart.DATA_UCSRA] >> uart.TXC_BIT) & 1, 0)
        for _ in range(80):
            emu.step()
        self.assertEqual(uart.tx_log, [0x41, 0x42])
        self.assertEqual((emu.data[uart.DATA_UCSRA] >> uart.TXC_BIT) & 1, 1)


if __name__ == "__main__":
    unittest.main()
