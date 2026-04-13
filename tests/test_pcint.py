import unittest

from sim import ATmega2560Emulator


class TestPCINT(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        return emu

    def test_pcint0_flag_sets_on_masked_pin_change(self) -> None:
        emu = self._new_emu()
        emu.data[emu.DATA_PCMSK0] = 1 << 0
        emu.data[emu.DATA_PCICR] = 1 << 0

        emu.step()
        self.assertEqual((emu.data[0x20 + emu.IO_PCIFR] >> 0) & 1, 0)

        emu.set_pin_level("B", 0, 1)
        emu.step()
        self.assertEqual((emu.data[0x20 + emu.IO_PCIFR] >> 0) & 1, 1)

    def test_pcint_does_not_flag_when_mask_bit_is_clear(self) -> None:
        emu = self._new_emu()
        emu.data[emu.DATA_PCMSK0] = 0x00
        emu.data[emu.DATA_PCICR] = 1 << 0

        emu.set_pin_level("B", 3, 1)
        emu.step()
        self.assertEqual((emu.data[0x20 + emu.IO_PCIFR] >> 0) & 1, 0)

    def test_pcint_flags_when_released_pin_rises_to_pullup_level(self) -> None:
        emu = self._new_emu()
        emu.data[emu.DATA_PCMSK0] = 1 << 0
        emu.data[emu.DATA_PCICR] = 1 << 0
        emu.data[emu.GPIO_PORTS["B"][2]] = 1 << 0

        emu.set_pin_level("B", 0, 0)
        emu.step()
        emu._data_write(0x20 + emu.IO_PCIFR, 1 << 0)

        emu.release_pin_level("B", 0)
        emu.step()

        self.assertEqual((emu.data[0x20 + emu.IO_PCIFR] >> 0) & 1, 1)

    def test_pcifr_write_one_to_clear(self) -> None:
        emu = self._new_emu()
        emu.data[0x20 + emu.IO_PCIFR] = 0x07

        emu._data_write(0x20 + emu.IO_PCIFR, 1 << 1)
        self.assertEqual(emu.data[0x20 + emu.IO_PCIFR], 0x05)

    def test_pcint0_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[emu.DATA_PCMSK0] = 1 << 1
        emu.data[emu.DATA_PCICR] = 1 << 0

        emu.set_pin_level("B", 1, 1)
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_PCINT0)

    def test_pcint1_and_pcint2_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[emu.DATA_PCMSK1] = 1 << 2
        emu.data[emu.DATA_PCMSK2] = 1 << 4
        emu.data[emu.DATA_PCICR] = (1 << 1) | (1 << 2)

        emu.set_pin_level("J", 2, 1)
        emu.step()
        self.assertEqual(emu.pc, emu.VECTOR_PCINT1)

        # Return to mainline context and dispatch PCINT2 next.
        emu.pc = 0
        emu.sp = 0x21FF
        emu._set_flag(emu.FLAG_I, 1)
        emu.set_pin_level("K", 4, 1)
        emu.step()
        self.assertEqual(emu.pc, emu.VECTOR_PCINT2)


if __name__ == "__main__":
    unittest.main()
