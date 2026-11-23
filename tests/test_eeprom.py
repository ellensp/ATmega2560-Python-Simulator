import unittest

from sim import ATmega2560Emulator


class TestEEPROMController(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        emu.EEPROM_WRITE_CYCLES = 2  # short programming time for these tests
        emu.EEPROM_HALF_WRITE_CYCLES = 2
        return emu

    def test_write_takes_3_3_ms(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0xCFFF])  # rjmp .-2
        emu._data_write(emu.DATA_EEARL, 0x10)
        emu._data_write(emu.DATA_EEDR, 0x5A)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEMPE_BIT)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEPE_BIT)

        for _ in range(52800 // 2 - 1):  # 2 cycles per step
            emu.step()
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 1)
        self.assertEqual(emu.eeprom[0x0010], 0xFF)  # still erased
        emu.step()
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 0)
        self.assertEqual(emu.eeprom[0x0010], 0x5A)

    def test_erase_only_and_write_only_modes(self) -> None:
        emu = self._new_emu()
        emu.eeprom[0x0020] = 0xF0

        emu._data_write(emu.DATA_EEARL, 0x20)
        emu._data_write(emu.DATA_EEDR, 0x3C)
        mode_write_only = 1 << emu.EECR_EEPM1_BIT
        emu._data_write(emu.DATA_EECR, mode_write_only | (1 << emu.EECR_EEMPE_BIT))
        emu._data_write(emu.DATA_EECR, mode_write_only | (1 << emu.EECR_EEPE_BIT))
        emu.step()
        emu.step()
        self.assertEqual(emu.eeprom[0x0020], 0x30)  # write only: bits can only be cleared

        mode_erase_only = 1 << emu.EECR_EEPM0_BIT
        emu._data_write(emu.DATA_EECR, mode_erase_only | (1 << emu.EECR_EEMPE_BIT))
        emu._data_write(emu.DATA_EECR, mode_erase_only | (1 << emu.EECR_EEPE_BIT))
        emu.step()
        emu.step()
        self.assertEqual(emu.eeprom[0x0020], 0xFF)

    def test_read_and_write_strobes_halt_the_cpu(self) -> None:
        emu = ATmega2560Emulator()
        eecr_io = emu.DATA_EECR - 0x20
        sbi = lambda bit: 0x9A00 | (eecr_io << 3) | bit  # noqa: E731
        emu.load_program_words([sbi(emu.EECR_EERE_BIT), sbi(emu.EECR_EEMPE_BIT), sbi(emu.EECR_EEPE_BIT)])
        self.assertEqual(emu.step().cycles, 2 + 4)  # read: halted 4 cycles
        self.assertEqual(emu.step().cycles, 2)
        self.assertEqual(emu.step().cycles, 2 + 2)  # write: halted 2 cycles

    def test_eere_reads_selected_eeprom_byte_into_eedr(self) -> None:
        emu = self._new_emu()
        emu.eeprom[0x0123] = 0x5A

        emu._data_write(emu.DATA_EEARL, 0x23)
        emu._data_write(emu.DATA_EEARH, 0x01)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EERE_BIT)

        self.assertEqual(emu.data[emu.DATA_EEDR], 0x5A)

    def test_eepe_without_eempe_does_not_start_write(self) -> None:
        emu = self._new_emu()
        emu.eeprom[0x0042] = 0x10

        emu._data_write(emu.DATA_EEARL, 0x42)
        emu._data_write(emu.DATA_EEARH, 0x00)
        emu._data_write(emu.DATA_EEDR, 0xAA)

        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEPE_BIT)
        for _ in range(4):
            emu.step()

        self.assertEqual(emu.eeprom[0x0042], 0x10)
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 0)

    def test_eempe_then_eepe_starts_and_completes_write(self) -> None:
        emu = self._new_emu()

        emu._data_write(emu.DATA_EEARL, 0x55)
        emu._data_write(emu.DATA_EEARH, 0x00)
        emu._data_write(emu.DATA_EEDR, 0xBE)

        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEMPE_BIT)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEPE_BIT)
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 1)

        emu.step()
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 1)

        emu.step()
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 0)
        self.assertEqual(emu.eeprom[0x0055], 0xBE)

    def test_eempe_window_expires_if_eepe_not_set_soon_enough(self) -> None:
        emu = self._new_emu()

        emu._data_write(emu.DATA_EEARL, 0x33)
        emu._data_write(emu.DATA_EEARH, 0x00)
        emu._data_write(emu.DATA_EEDR, 0x7C)

        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEMPE_BIT)
        for _ in range(5):
            emu.step()

        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEPE_BIT)
        for _ in range(3):
            emu.step()

        self.assertEqual(emu.eeprom[0x0033], 0xFF)  # still erased
        self.assertEqual((emu.data[emu.DATA_EECR] >> emu.EECR_EEPE_BIT) & 1, 0)

    def test_eeprom_contents_persist_across_reset(self) -> None:
        emu = self._new_emu()

        emu._data_write(emu.DATA_EEARL, 0x20)
        emu._data_write(emu.DATA_EEARH, 0x00)
        emu._data_write(emu.DATA_EEDR, 0x99)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEMPE_BIT)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EEPE_BIT)
        emu.step()
        emu.step()

        emu.reset()
        self.assertEqual(emu.eeprom[0x0020], 0x99)

    def test_eeprom_ready_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)

        emu._data_write(emu.DATA_EEARL, 0x10)
        emu._data_write(emu.DATA_EEARH, 0x00)
        emu._data_write(emu.DATA_EEDR, 0x11)
        emu._data_write(emu.DATA_EECR, 1 << emu.EECR_EERIE_BIT)
        emu._data_write(emu.DATA_EECR, (1 << emu.EECR_EEMPE_BIT) | (1 << emu.EECR_EERIE_BIT))
        emu._data_write(emu.DATA_EECR, (1 << emu.EECR_EEPE_BIT) | (1 << emu.EECR_EERIE_BIT))

        emu.step()
        self.assertEqual(emu.pc, 1)

        emu.step()
        emu.step()  # one instruction later (hardware timing)
        self.assertEqual(emu.pc, emu.VECTOR_EEPROM_READY)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)


if __name__ == "__main__":
    unittest.main()
