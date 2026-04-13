import unittest

from avr_encoding import out as out_io
from avr_encoding import rjmp
from sim import ATmega2560Emulator


class TestTimer2(unittest.TestCase):
    def test_overflow_sets_tov2(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])  # two NOPs => 2 cycles

        emu.data[0x00B1] = 0x01  # TCCR2B CS=001
        emu.data[0x00B2] = 0xFE  # TCNT2

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x00B2], 0x00)
        self.assertEqual(emu.data[0x20 + 0x17] & 0x01, 0x01)  # TIFR2.TOV2

    def test_prescaler_64_counts_by_instruction_cycles(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)])  # each step uses 2 cycles in-place loop

        emu.data[0x00B1] = 0x04  # TCCR2B CS=100 => clk/64
        emu.data[0x00B2] = 0x00

        for _ in range(31):
            emu.step()
        self.assertEqual(emu.data[0x00B2], 0x00)

        emu.step()  # total 64 cycles reached
        self.assertEqual(emu.data[0x00B2], 0x01)

    def test_tifr2_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x17] = 0x01

        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x17, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x17] & 0x01, 0x00)

    def test_ctc_mode_clears_counter_on_ocr2a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 8)

        emu.data[0x00B0] = 0x02  # TCCR2A WGM21=1
        emu.data[0x00B1] = 0x01  # TCCR2B CS=clk/1, WGM22=0
        emu.data[0x00B3] = 0x03  # OCR2A
        emu.data[0x00B2] = 0x00  # TCNT2

        emu.step()  # 1
        emu.step()  # 2
        emu.step()  # compare at 3 -> clear to 0 in CTC

        self.assertEqual(emu.data[0x00B2], 0x00)
        self.assertEqual((emu.data[0x20 + 0x17] >> 1) & 1, 1)  # OCF2A
        self.assertEqual(emu.data[0x20 + 0x17] & 1, 0)         # no overflow here

    def test_compare_b_sets_ocf2b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00B1] = 0x01  # TCCR2B CS=clk/1
        emu.data[0x00B4] = 0x02  # OCR2B
        emu.data[0x00B2] = 0x00  # TCNT2

        emu.step()  # TCNT2=1
        emu.step()  # TCNT2=2 -> OCF2B

        self.assertEqual((emu.data[0x20 + 0x17] >> 2) & 1, 1)  # OCF2B

    def test_fast_pwm_wrap_sets_tov2(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00B0] = 0x03  # WGM21:0 = 0b11 (Fast PWM, TOP=0xFF)
        emu.data[0x00B1] = 0x01  # CS=clk/1
        emu.data[0x00B2] = 0xFE

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x00B2], 0x00)
        self.assertEqual(emu.data[0x20 + 0x17] & 0x01, 0x01)

    def test_phase_correct_pwm_sets_tov2_at_bottom(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 300)

        emu.data[0x00B0] = 0x01  # WGM20=1 (Phase Correct PWM, TOP=0xFF)
        emu.data[0x00B1] = 0x01  # CS=clk/1
        emu.data[0x00B2] = 0xFE

        emu.step()
        emu.step()
        for _ in range(254):
            emu.step()

        self.assertEqual(emu.data[0x00B2], 0x00)
        self.assertEqual(emu.data[0x20 + 0x17] & 0x01, 0x01)

    def test_async_mode_scales_timer2_tick_rate(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)])  # 2 CPU cycles per step

        emu.data[0x00B6] = 1 << 3  # ASSR.AS2 = 1
        emu.data[0x00B1] = 0x01    # CS=clk/1 (effective /128 in async baseline)
        emu.data[0x00B2] = 0x00

        for _ in range(63):
            emu.step()
        self.assertEqual(emu.data[0x00B2], 0x00)

        emu.step()  # 64 * 2 = 128 cycles
        self.assertEqual(emu.data[0x00B2], 0x01)


if __name__ == "__main__":
    unittest.main()
