import unittest

from sim import ATmega2560Emulator


class TestGPIOAlternateFunctions(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)
        return emu

    def test_usart0_tx_pin_reads_high_when_tx_enabled(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["E"]
        emu.data[ddr_addr] = 1 << 1
        emu.data[port_addr] = 0x00

        emu._data_write(emu.uart0.DATA_UCSRB, 1 << emu.uart0.TXEN_BIT)

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1)

    def test_spi_master_sck_pin_follows_cpol(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = (1 << 1) | (1 << 2)
        emu.data[port_addr] = 0x00

        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT) | (1 << emu.SPCR_CPOL_BIT))

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1)

        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 0x00)

    def test_spi_master_mosi_pin_reflects_shifted_data_bit(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = (1 << 1) | (1 << 2)
        emu.data[port_addr] = 0x00
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))

        emu._data_write(emu.DATA_SPDR, 0x80)
        self.assertEqual(emu._data_read(pin_addr) & (1 << 2), 1 << 2)

        for _ in range(4):
            emu.step()

        emu._data_write(emu.DATA_SPDR, 0x00)
        self.assertEqual(emu._data_read(pin_addr) & (1 << 2), 0x00)

    def test_twi_start_drives_sda_low_and_stop_releases_it(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["D"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = (1 << 0) | (1 << 1)

        emu._data_write(
            emu.DATA_TWCR,
            (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT),
        )

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 0x00)

        emu._data_write(
            emu.DATA_TWCR,
            (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTO_BIT),
        )

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1)

    def test_spi_sck_goes_active_during_transfer(self) -> None:
        """SCK leaves the CPOL idle level for the duration of a transfer."""
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = (1 << 1) | (1 << 2)
        emu.data[port_addr] = 0x00
        # CPOL=0: idle SCK = 0.
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))

        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 0x00, "SCK idle before transfer")

        emu._data_write(emu.DATA_SPDR, 0x55)
        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1, "SCK active (~CPOL) during transfer")

        for _ in range(4):
            emu.step()
        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 0x00, "SCK returns to CPOL after transfer")

    def test_spi_mosi_shifts_mid_transfer(self) -> None:
        """MOSI reflects the bit currently being shifted, not just the initial top bit."""
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = (1 << 1) | (1 << 2)
        emu.data[port_addr] = 0x00
        emu._data_write(emu.DATA_SPCR, (1 << emu.SPCR_SPE_BIT) | (1 << emu.SPCR_MSTR_BIT))

        # 0x80 = 1000_0000: bit 7 = 1, all others 0.
        emu._data_write(emu.DATA_SPDR, 0x80)
        # elapsed=0 → bit_idx=0 → bit 7 of 0x80 = 1.
        self.assertEqual(emu._data_read(pin_addr) & (1 << 2), 1 << 2, "MOSI=1 at start (bit 7)")

        emu.step()
        # elapsed=1 out of total=4 → bit_idx = min(7, 1*8//4) = 2 → bit 5 of 0x80 = 0.
        self.assertEqual(emu._data_read(pin_addr) & (1 << 2), 0x00, "MOSI=0 mid-transfer (bit 5 of 0x80)")

    def test_uart_tx_pin_low_during_byte_transmission(self) -> None:
        """TX pin goes low (start-bit) while a byte is being shifted out, then returns high."""
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["E"]
        emu.data[ddr_addr] = 1 << 1
        emu.data[port_addr] = 0x00

        emu._data_write(emu.uart0.DATA_UCSRB, 1 << emu.uart0.TXEN_BIT)
        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1, "TX idle-high before transmission")

        emu._data_write(emu.uart0.DATA_UDR, 0x41)  # enqueue 'A'
        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 0, "TX low while byte is pending")

        emu.step()  # advance() dequeues the byte
        self.assertEqual(emu._data_read(pin_addr) & (1 << 1), 1 << 1, "TX idle-high after transmission")

    def test_twi_scl_driven_low_during_operation(self) -> None:
        """SCL is released high when TWI is idle and driven low during an active operation."""
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["D"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = (1 << 0) | (1 << 1)  # pull-ups on SCL (bit 0) and SDA (bit 1)

        # Enable TWI only — no operation in progress.
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT))
        self.assertEqual(emu._data_read(pin_addr) & (1 << 0), 1 << 0, "SCL high when TWI idle")

        # Kick off a START operation; operation_cycles_remaining becomes > 0.
        emu._data_write(
            emu.DATA_TWCR,
            (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT),
        )
        self.assertEqual(emu._data_read(pin_addr) & (1 << 0), 0x00, "SCL low during START operation")

        # Let the operation complete (2 cycles).
        for _ in range(2):
            emu.step()
        self.assertEqual(emu._data_read(pin_addr) & (1 << 0), 1 << 0, "SCL released after operation")


if __name__ == "__main__":
    unittest.main()
