import unittest

from avr_encoding import out as out_io
from sim import ATmega2560Emulator


class TestTimer1(unittest.TestCase):
    def test_overflow_sets_tov1(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000, 0x0000])  # two NOPs => 2 cycles

        emu.data[0x0081] = 0x01  # TCCR1B CS=001
        emu.data[0x0084] = 0xFE  # TCNT1L
        emu.data[0x0085] = 0xFF  # TCNT1H

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0084], 0x00)
        self.assertEqual(emu.data[0x0085], 0x00)
        self.assertEqual(emu.data[0x20 + 0x16] & 0x01, 0x01)  # TIFR1.TOV1

    def test_compare_a_sets_ocf1a(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0081] = 0x01  # TCCR1B CS=001
        emu.data[0x0088] = 0x02  # OCR1AL
        emu.data[0x0089] = 0x00  # OCR1AH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H

        emu.step()  # TCNT1=1
        emu.step()  # TCNT1=2 -> OCF1A

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x16] >> 1) & 1, 1)

    def test_tifr1_write_one_clears_flag(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x20 + 0x16] = 0x01

        # OUT 0x16, r16 where r16=0x01
        emu.reg[16] = 0x01
        emu.load_program_words([out_io(0x16, 16)])
        emu.step()

        self.assertEqual(emu.data[0x20 + 0x16] & 0x01, 0x00)

    def test_compare_b_sets_ocf1b(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0081] = 0x01  # TCCR1B CS=001
        emu.data[0x008A] = 0x02  # OCR1BL
        emu.data[0x008B] = 0x00  # OCR1BH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x16] >> 2) & 1, 1)

    def test_compare_c_sets_ocf1c(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0081] = 0x01  # TCCR1B CS=001
        emu.data[0x008C] = 0x02  # OCR1CL
        emu.data[0x008D] = 0x00  # OCR1CH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H

        emu.step()
        emu.step()

        emu.step()  # one instruction later (hardware timing)
        self.assertEqual((emu.data[0x20 + 0x16] >> 3) & 1, 1)

    def test_trigger_timer1_capture_latches_icr_and_sets_icf1(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[0x0084] = 0x34
        emu.data[0x0085] = 0x12

        emu.trigger_timer1_capture()

        self.assertEqual(emu.data[0x0086], 0x34)  # ICR1L
        self.assertEqual(emu.data[0x0087], 0x12)  # ICR1H
        self.assertEqual((emu.data[0x20 + 0x16] >> 5) & 1, 1)  # ICF1

    def test_fast_pwm_8bit_wrap_sets_tov1(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 4)

        emu.data[0x0080] = 0x01  # WGM10=1
        emu.data[0x0081] = 0x09  # WGM12=1 + CS=001 => mode 0b0101
        emu.data[0x0084] = 0xFE
        emu.data[0x0085] = 0x00

        emu.step()
        emu.step()

        self.assertEqual(emu.data[0x0084], 0x00)
        self.assertEqual(emu.data[0x20 + 0x16] & 0x01, 0x01)

    def test_phase_correct_8bit_sets_tov1_at_bottom(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 300)

        emu.data[0x0080] = 0x01  # mode 0b0001
        emu.data[0x0081] = 0x01  # CS=001
        emu.data[0x0084] = 0xFE
        emu.data[0x0085] = 0x00

        emu.step()
        emu.step()
        for _ in range(254):
            emu.step()

        self.assertEqual(emu.data[0x0084], 0x00)
        self.assertEqual(emu.data[0x20 + 0x16] & 0x01, 0x01)


if __name__ == "__main__":
    unittest.main()
