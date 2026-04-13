import unittest

from sim import ATmega2560Emulator


class TestINT0(unittest.TestCase):
    def test_rising_edge_triggers_int0_vector(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 0x01  # enable INT0
        emu.data[emu.DATA_EICRA] = 0x03       # rising edge on INT0

        emu.set_int0_pin(0)
        emu.set_int0_pin(1)
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_INT0)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.sp, 0x21FC)

    def test_wrong_edge_does_not_trigger(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 8)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 0x01  # enable INT0
        emu.data[emu.DATA_EICRA] = 0x03       # rising edge mode

        emu.set_int0_pin(1)
        emu.set_int0_pin(0)  # falling edge: should not trigger
        emu.step()

        self.assertEqual(emu.pc, 1)


if __name__ == "__main__":
    unittest.main()
