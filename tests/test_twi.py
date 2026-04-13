import unittest

from sim import ATmega2560Emulator


class TestTWIController(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        return emu

    def test_start_condition_sets_status_and_twint(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))

        emu.step()
        emu.step()

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_START)
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWINT_BIT) & 1, 1)
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWSTA_BIT) & 1, 0)

    def test_master_transmit_address_and_data_ack_path(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        emu.step()
        emu.step()

        emu._data_write(emu.DATA_TWDR, 0x50)  # SLA+W for address 0x28
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        emu.step()
        emu.step()

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MT_SLA_ACK)

        emu._data_write(emu.DATA_TWDR, 0xAB)
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        emu.step()
        emu.step()

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MT_DATA_ACK)
        self.assertEqual(emu.twi_transmitted_bytes, [0xAB])

    def test_master_receive_loads_twdr_and_status(self) -> None:
        emu = self._new_emu()
        emu.queue_twi_read_bytes([0x5E])
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        emu.step()
        emu.step()

        emu._data_write(emu.DATA_TWDR, 0x51)  # SLA+R for address 0x28
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        emu.step()
        emu.step()

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MR_SLA_ACK)

        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWEA_BIT))
        emu.step()
        emu.step()

        self.assertEqual(emu.data[emu.DATA_TWDR], 0x5E)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MR_DATA_ACK)

    def test_twi_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu._data_write(
            emu.DATA_TWCR,
            (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWIE_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT),
        )

        emu.step()
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TWI)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_stop_condition_returns_twi_to_idle(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        emu.step()
        emu.step()

        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTO_BIT))

        self.assertEqual(emu._twi_state, "idle")
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWSTO_BIT) & 1, 0)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, 0xF8)


if __name__ == "__main__":
    unittest.main()
