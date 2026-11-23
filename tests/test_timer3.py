import unittest

from avr_encoding import out as out_io
from sim import ATmega2560Emulator


class TestTimer3(unittest.TestCase):
    def test_overflow_sets_tov3(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])  # two NOPs => 2 cycles

        emu.data[0x0091] = 0x01  # TCCR3B CS=001
        emu.data[0x0094] = 0xFE  # TCNT3L
        emu.data[0x0095] = 0xFF  # TCNT3H

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0094], 0x00)
        self.assertEqual(emu.data[0x0095], 0x00)
        self.assertEqual(emu.data[0x20 + 0x18] & 0x01, 0x01)  # TIFR3.TOV3

    def test_compare_a_sets_ocf3a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0091] = 0x01  # TCCR3B CS=001
        emu.data[0x0098] = 0x02  # OCR3AL
        emu.data[0x0099] = 0x00  # OCR3AH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H

        emu.step()  # TCNT3=1
        emu.step()  # TCNT3=2 -> OCF3A

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x18] >> 1) & 1, 1)

    def test_tifr3_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x18] = 0x01

        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x18, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x18] & 0x01, 0x00)

    def test_compare_b_sets_ocf3b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0091] = 0x01  # TCCR3B CS=001
        emu.data[0x009A] = 0x02  # OCR3BL
        emu.data[0x009B] = 0x00  # OCR3BH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x18] >> 2) & 1, 1)

    def test_compare_c_sets_ocf3c(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0091] = 0x01  # TCCR3B CS=001
        emu.data[0x009C] = 0x02  # OCR3CL
        emu.data[0x009D] = 0x00  # OCR3CH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x18] >> 3) & 1, 1)

    def test_trigger_timer3_capture_latches_icr_and_sets_icf3(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x0094] = 0x78
        emu.data[0x0095] = 0x56

        emu.trigger_timer3_capture()

        self.assertEqual(emu.data[0x0096], 0x78)  # ICR3L
        self.assertEqual(emu.data[0x0097], 0x56)  # ICR3H
        self.assertEqual((emu.data[0x20 + 0x18] >> 5) & 1, 1)  # ICF3

    def test_fast_pwm_8bit_wrap_sets_tov3(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0090] = 0x01  # WGM30=1
        emu.data[0x0091] = 0x09  # WGM32=1 + CS=001
        emu.data[0x0094] = 0xFE
        emu.data[0x0095] = 0x00

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0094], 0x00)
        self.assertEqual(emu.data[0x20 + 0x18] & 0x01, 0x01)


if __name__ == "__main__":
    unittest.main()
