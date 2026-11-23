import unittest

from sim import ATmega2560Emulator


class TestSPIController(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        return emu

    def test_master_transfer_completes_and_receives_queued_byte(self) -> None:
        emu = self._new_emu()
        emu.queue_spi_response_bytes([0xA5])
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))
        emu._data_write(emu.DATA_SPDR, 0x3C)

        for _ in range(33):  # one byte at f/4
            emu.step()

        self.assertEqual(emu.spi_transmitted_bytes, [0x3C])
        self.assertEqual((emu.data[emu.DATA_SPSR] >> emu.SPSR_SPIF_BIT) & 1, 1)
        self.assertEqual(emu.data[emu.DATA_SPDR], 0xA5)

    def test_reading_spdr_clears_spif(self) -> None:
        emu = self._new_emu()
        emu.queue_spi_response_bytes([0x55])
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))
        emu._data_write(emu.DATA_SPDR, 0x11)

        for _ in range(33):  # one byte at f/4
            emu.step()

        self.assertEqual(emu._data_read(emu.DATA_SPDR), 0x55)
        self.assertEqual((emu.data[emu.DATA_SPSR] >> emu.SPSR_SPIF_BIT) & 1, 0)

    def test_write_collision_sets_wcol_when_busy(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))
        emu._data_write(emu.DATA_SPDR, 0x12)
        emu._data_write(emu.DATA_SPDR, 0x34)

        self.assertEqual((emu.data[emu.DATA_SPSR] >> emu.SPSR_WCOL_BIT) & 1, 1)
        self.assertEqual(emu.spi_transmitted_bytes, [])

    def test_spi_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.queue_spi_response_bytes([0x66])
        emu._data_write(
            emu.DATA_SPCR,
            (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT) | (1 << emu.SPCR_SPIE_BIT),
        )
        emu._data_write(emu.DATA_SPDR, 0x20)

        for _ in range(34):  # one byte at f/4 (33 cycles), then one instruction before the interrupt
            emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_SPI_STC)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_disabled_spi_does_not_start_transfer(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_SPDR, 0x77)

        for _ in range(6):
            emu.step()

        self.assertEqual(emu.spi_transmitted_bytes, [])
        self.assertEqual((emu.data[emu.DATA_SPSR] >> emu.SPSR_SPIF_BIT) & 1, 0)


if __name__ == "__main__":
    unittest.main()
