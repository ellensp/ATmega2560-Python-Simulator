"""Compare outputs (OCnx pins), the pin-read delay and the logic probe on PWM pins."""

import unittest

from avr_encoding import ldi, out
from sim import ATmega2560Emulator
from sim_probe import PinProbe

IN_R16_PINB = 0xB103  # in r16, PINB (I/O 0x03)
NOP = 0x0000


class TestPinReadDelay(unittest.TestCase):
    def test_pin_read_needs_a_cycle_after_the_port_write(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([ldi(17, 0x80), out(0x04, 17), out(0x05, 17), IN_R16_PINB, IN_R16_PINB])
        for _ in range(4):                               # LDI, OUT DDRB, OUT PORTB, IN PINB
            emu.step()
        self.assertEqual(emu.reg[16] & 0x80, 0x00)       # still the old level
        emu.step()
        self.assertEqual(emu.reg[16] & 0x80, 0x80)


class TestCompareOutputs(unittest.TestCase):
    def _timer1(self, tccr1a: int, tccr1b_mode: int, top: int, ocr1c: int) -> ATmega2560Emulator:
        """Timer1 at clk/1 with OC1C on PB7 (an output), ICR1 = top."""
        emu = ATmega2560Emulator()
        emu.load_program_words([NOP] * 400)
        emu.data[0x24] = 0x80                            # DDRB7
        emu._data_write(0x008D, 0)                       # OCR1C
        emu._data_write(0x008C, ocr1c)
        emu._data_write(0x0080, tccr1a)
        emu._data_write(0x0081, tccr1b_mode)
        emu._data_write(0x0087, 0)                       # ICR1
        emu._data_write(0x0086, top)
        emu._data_write(0x0081, tccr1b_mode | 0x01)
        return emu

    def _levels(self, emu: ATmega2560Emulator, cycles: int) -> str:
        out_ = []
        for _ in range(cycles):
            emu.step()
            out_.append(str(emu.output_pin_level("B", 7)))
        return "".join(out_)

    def test_fast_pwm_non_inverting(self) -> None:
        emu = self._timer1(0x0A, 0x18, 20, 6)            # mode 14, COM1C = 2
        levels = self._levels(emu, 63)
        # After the first wrap: high for OCR + 1 = 7 clocks out of TOP + 1 = 21.
        self.assertEqual(levels[20:62], ("1" * 7 + "0" * 14) * 2)

    def test_fast_pwm_inverting_and_extremes(self) -> None:
        self.assertEqual(self._levels(self._timer1(0x0E, 0x18, 20, 6), 63)[20:62], ("0" * 7 + "1" * 14) * 2)
        self.assertEqual(self._levels(self._timer1(0x0A, 0x18, 20, 20), 63)[20:], "1" * 43)          # OCR = TOP: always high
        self.assertEqual(self._levels(self._timer1(0x0A, 0x18, 20, 0), 63)[20:62], ("1" + "0" * 20) * 2)  # OCR = BOTTOM: one clock

    def test_phase_correct_non_inverting_is_symmetric_around_bottom(self) -> None:
        emu = self._timer1(0x0A, 0x10, 20, 6)            # mode 10, COM1C = 2
        levels = self._levels(emu, 100)
        # Set on the match counting down (clock 35), cleared on the match counting up (clock 47).
        self.assertEqual(levels[30:50], "0000" + "1" * 12 + "0000")
        self.assertEqual(levels[70:90], "0000" + "1" * 12 + "0000")

    def test_ctc_toggle_clear_and_set(self) -> None:
        self.assertEqual(self._levels(self._timer1(0x04, 0x18, 20, 6), 49)[5:49], "0" + "1" * 21 + "0" * 21 + "1")
        emu = self._timer1(0x0C, 0x18, 20, 6)            # set on match
        self.assertEqual(self._levels(emu, 10), "0000001111")
        emu._data_write(0x0080, 0x08)                    # clear on match: the state is kept until then
        self.assertEqual(emu.output_pin_level("B", 7), 1)
        self.assertEqual(self._levels(emu, 21)[-3:], "000")

    def test_disconnected_output_shows_portx_and_keeps_its_state(self) -> None:
        emu = self._timer1(0x0C, 0x18, 20, 6)
        self._levels(emu, 10)                            # OC1C is now high
        emu._data_write(0x0080, 0x00)                    # disconnect
        self.assertEqual(emu.output_pin_level("B", 7), 0)   # PORTB7
        emu._data_write(0x0080, 0x0C)
        self.assertEqual(emu.output_pin_level("B", 7), 1)

    def test_force_output_compare(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([NOP] * 8)
        emu.data[0x24] = 0x80
        emu._data_write(0x0080, 0x04)                    # normal mode, toggle OC1C
        emu._data_write(0x0082, 0x20)                    # FOC1C
        self.assertEqual(emu.output_pin_level("B", 7), 1)
        self.assertEqual(emu.data[0x0082], 0)            # reads back as zero
        self.assertEqual(emu.data[0x20 + 0x16], 0)       # no flag
        emu._data_write(0x0082, 0x20)
        self.assertEqual(emu.output_pin_level("B", 7), 0)

    def test_oc0a_and_oc1c_share_pb7(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([NOP] * 8)
        emu.data[0x24] = 0x80
        emu._data_write(0x44, 0x40)                      # Timer0 normal, toggle OC0A
        emu._data_write(0x0080, 0x04)                    # Timer1 normal, toggle OC1C
        emu._data_write(0x45, 0x80)                      # FOC0A: OC0A high, OC1C low
        self.assertEqual(emu.output_pin_level("B", 7), 0)   # PORTB7 = 0: AND
        emu._data_write(0x25, 0x80)
        self.assertEqual(emu.output_pin_level("B", 7), 1)   # PORTB7 = 1: OR

    def test_timer0_oc0b_on_pg5_and_pin_reads_follow(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([NOP] * 600)
        emu.data[0x33] = 0x20                            # DDRG5
        emu._data_write(0x48, 99)                        # OCR0B
        emu._data_write(0x44, 0x23)                      # fast PWM, COM0B = 2
        emu._data_write(0x45, 0x01)
        high = 0
        for _ in range(512):
            emu.step()
            high += (emu._data_read(0x32) >> 5) & 1      # PING5
        # The output goes high at the first wrap (clock 256): 100 clocks high in the
        # second period, plus the first clock of the third.
        self.assertEqual(high, 100 + 1)

    def test_logic_probe_sees_pwm_edges(self) -> None:
        emu = self._timer1(0x0A, 0x18, 20, 6)
        probe = PinProbe(emu, ["PB7"])
        for _ in range(64):
            emu.step()
        edges = [(e.cycle, e.level) for e in probe.edges]
        # Timer clock k is at cycle k: set at the wraps (21, 42, 63), cleared after each match (28, 49).
        self.assertEqual(edges, [(21, 1), (28, 0), (42, 1), (49, 0), (63, 1)])


if __name__ == "__main__":
    unittest.main()
