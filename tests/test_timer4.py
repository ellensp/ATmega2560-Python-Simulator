import unittest

from avr_encoding import out as out_io
from sim import ATmega2560Emulator


class TestTimer4(unittest.TestCase):
    def test_overflow_sets_tov4(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])

        emu.data[0x00A1] = 0x01  # TCCR4B CS=001
        emu.data[0x00A4] = 0xFE  # TCNT4L
        emu.data[0x00A5] = 0xFF  # TCNT4H

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x00A4], 0x00)
        self.assertEqual(emu.data[0x00A5], 0x00)
        self.assertEqual(emu.data[0x20 + 0x19] & 0x01, 0x01)  # TIFR4.TOV4

    def test_compare_a_sets_ocf4a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00A1] = 0x01
        emu.data[0x00A8] = 0x02
        emu.data[0x00A9] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x19] >> 1) & 1, 1)

    def test_tifr4_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x19] = 0x01

        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x19, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x19] & 0x01, 0x00)

    def test_compare_b_sets_ocf4b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00A1] = 0x01
        emu.data[0x00AA] = 0x02
        emu.data[0x00AB] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x19] >> 2) & 1, 1)

    def test_compare_c_sets_ocf4c(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00A1] = 0x01
        emu.data[0x00AC] = 0x02
        emu.data[0x00AD] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x19] >> 3) & 1, 1)

    def test_trigger_timer4_capture_latches_icr_and_sets_icf4(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x00A4] = 0x78
        emu.data[0x00A5] = 0x56

        emu.trigger_timer4_capture()

        self.assertEqual(emu.data[0x00A6], 0x78)
        self.assertEqual(emu.data[0x00A7], 0x56)
        self.assertEqual((emu.data[0x20 + 0x19] >> 5) & 1, 1)

    def test_fast_pwm_8bit_wrap_sets_tov4(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x00A0] = 0x01  # WGM40=1
        emu.data[0x00A1] = 0x09  # WGM42=1 + CS=001
        emu.data[0x00A4] = 0xFE
        emu.data[0x00A5] = 0x00

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x00A4], 0x00)
        self.assertEqual(emu.data[0x20 + 0x19] & 0x01, 0x01)


if __name__ == "__main__":
    unittest.main()
