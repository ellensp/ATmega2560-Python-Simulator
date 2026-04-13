import unittest

from avr_encoding import out as out_io
from sim import ATmega2560Emulator


class TestTimer5(unittest.TestCase):
    def test_overflow_sets_tov5(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])

        emu.data[0x0121] = 0x01  # TCCR5B CS=001
        emu.data[0x0124] = 0xFE  # TCNT5L
        emu.data[0x0125] = 0xFF  # TCNT5H

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0124], 0x00)
        self.assertEqual(emu.data[0x0125], 0x00)
        self.assertEqual(emu.data[0x20 + 0x1A] & 0x01, 0x01)  # TIFR5.TOV5

    def test_compare_a_sets_ocf5a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0121] = 0x01
        emu.data[0x0128] = 0x02
        emu.data[0x0129] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00

        emu.step()
        emu.step()

        self.assertEqual((emu.data[0x20 + 0x1A] >> 1) & 1, 1)

    def test_tifr5_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x1A] = 0x01

        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x1A, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x1A] & 0x01, 0x00)

    def test_compare_b_sets_ocf5b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0121] = 0x01
        emu.data[0x012A] = 0x02
        emu.data[0x012B] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00

        emu.step()
        emu.step()

        self.assertEqual((emu.data[0x20 + 0x1A] >> 2) & 1, 1)

    def test_compare_c_sets_ocf5c(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0121] = 0x01
        emu.data[0x012C] = 0x02
        emu.data[0x012D] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00

        emu.step()
        emu.step()

        self.assertEqual((emu.data[0x20 + 0x1A] >> 3) & 1, 1)

    def test_trigger_timer5_capture_latches_icr_and_sets_icf5(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x0124] = 0x78
        emu.data[0x0125] = 0x56

        emu.trigger_timer5_capture()

        self.assertEqual(emu.data[0x0126], 0x78)
        self.assertEqual(emu.data[0x0127], 0x56)
        self.assertEqual((emu.data[0x20 + 0x1A] >> 5) & 1, 1)

    def test_fast_pwm_8bit_wrap_sets_tov5(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0120] = 0x01  # WGM50=1
        emu.data[0x0121] = 0x09  # WGM52=1 + CS=001
        emu.data[0x0124] = 0xFE
        emu.data[0x0125] = 0x00

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0124], 0x00)
        self.assertEqual(emu.data[0x20 + 0x1A] & 0x01, 0x01)


if __name__ == "__main__":
    unittest.main()
