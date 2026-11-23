import unittest

from avr_encoding import out as out_io
from avr_encoding import rjmp
from sim import ATmega2560Emulator


class TestTimer0(unittest.TestCase):
    def test_overflow_sets_tov0(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])  # two NOPs => 2 cycles

        # Clock select clk/1, set counter close to overflow.
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B CS=001
        emu.data[0x20 + 0x26] = 0xFE  # TCNT0

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x26], 0x00)
        self.assertEqual(emu.data[0x20 + 0x15] & 0x01, 0x01)  # TIFR0.TOV0

    def test_prescaler_64_counts_by_instruction_cycles(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)])  # each step uses 2 cycles in-place loop

        emu.data[0x20 + 0x25] = 0x03  # TCCR0B CS=011 => clk/64
        emu.data[0x20 + 0x26] = 0x00

        for _ in range(31):
            emu.step()
        self.assertEqual(emu.data[0x20 + 0x26], 0x00)

        emu.step()  # total 64 cycles reached
        self.assertEqual(emu.data[0x20 + 0x26], 0x01)

    def test_tifr0_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x15] = 0x01

        # OUT 0x15, r16 where r16=0x01
        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x15, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x15] & 0x01, 0x00)

    def test_ctc_mode_clears_counter_on_ocr0a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 8)

        emu.data[0x20 + 0x24] = 0x02  # TCCR0A WGM01=1
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B CS=clk/1, WGM02=0
        emu.data[0x20 + 0x27] = 0x03  # OCR0A
        emu.data[0x20 + 0x26] = 0x00  # TCNT0

        emu.step()  # 1
        emu.step()  # 2
        emu.step()  # compare at 3 -> clear to 0 in CTC

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual(emu.data[0x20 + 0x26], 0x00)
        self.assertEqual((emu.data[0x20 + 0x15] >> 1) & 1, 1)  # OCF0A
        self.assertEqual(emu.data[0x20 + 0x15] & 1, 0)         # no overflow here

    def test_compare_b_sets_ocf0b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x20 + 0x25] = 0x01  # TCCR0B CS=clk/1
        emu.data[0x20 + 0x28] = 0x02  # OCR0B
        emu.data[0x20 + 0x26] = 0x00  # TCNT0

        emu.step()  # TCNT0=1
        emu.step()  # TCNT0=2 -> OCF0B

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x15] >> 2) & 1, 1)  # OCF0B

    def test_fast_pwm_wrap_sets_tov0(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x20 + 0x24] = 0x03  # WGM01:0 = 0b11 (Fast PWM, TOP=0xFF)
        emu.data[0x20 + 0x25] = 0x01  # CS=clk/1
        emu.data[0x20 + 0x26] = 0xFE

        emu.step()  # TCNT0 -> 0xFF
        emu.step()  # wrap to 0x00

        self.assertEqual(emu.data[0x20 + 0x26], 0x00)
        self.assertEqual(emu.data[0x20 + 0x15] & 0x01, 0x01)

    def test_phase_correct_pwm_sets_tov0_at_bottom(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 300)

        emu.data[0x20 + 0x24] = 0x01  # WGM00=1 (Phase Correct PWM, TOP=0xFF)
        emu.data[0x20 + 0x25] = 0x01  # CS=clk/1
        emu.data[0x20 + 0x26] = 0xFE

        emu.step()  # 0xFF (top)
        emu.step()  # 0xFE (counting down)
        for _ in range(254):
            emu.step()

        self.assertEqual(emu.data[0x20 + 0x26], 0x00)
        emu.step()  # TOV is set on the timer clock after BOTTOM is reached
        self.assertEqual(emu.data[0x20 + 0x15] & 0x01, 0x01)


if __name__ == "__main__":
    unittest.main()
