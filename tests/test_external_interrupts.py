import unittest

from sim import ATmega2560Emulator


class TestExternalInterrupts(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 96)
        return emu

    def test_int1_rising_edge_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 1 << 1
        emu.data[emu.DATA_EICRA] = 0b11 << 2  # ISC11:10 = rising edge for INT1

        emu.set_ext_int_pin(1, 0)
        emu.set_ext_int_pin(1, 1)
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_INT1)

    def test_int4_rising_edge_uses_eicrb(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 1 << 4
        emu.data[emu.DATA_EICRB] = 0b11 << 0  # ISC41:40 for INT4

        emu.set_ext_int_pin(4, 0)
        emu.set_ext_int_pin(4, 1)
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_INT4)

    def test_wrong_edge_does_not_trigger_int2(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 1 << 2
        emu.data[emu.DATA_EICRA] = 0b11 << 4  # rising edge mode INT2

        emu.set_ext_int_pin(2, 1)
        emu.set_ext_int_pin(2, 0)  # falling edge in rising mode
        emu.step()

        self.assertEqual(emu.pc, 1)

    def test_external_interrupt_priority_lowest_index_first(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = (1 << 2) | (1 << 5)
        emu.data[0x20 + emu.IO_EIFR] = (1 << 2) | (1 << 5)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_INT2)
        self.assertEqual((emu.data[0x20 + emu.IO_EIFR] >> 2) & 1, 0)
        self.assertEqual((emu.data[0x20 + emu.IO_EIFR] >> 5) & 1, 1)


if __name__ == "__main__":
    unittest.main()
