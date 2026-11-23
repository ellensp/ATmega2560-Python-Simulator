import unittest

from sim import ATmega2560Emulator


class TestTWIController(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 1024)
        return emu

    @staticmethod
    def _run(emu: ATmega2560Emulator, cycles: int) -> None:
        for _ in range(cycles):
            emu.step()  # NOPs: one cycle each

    def test_no_device_answers_with_nack(self) -> None:
        emu = self._new_emu()
        emu.set_twi_devices([0x3C])
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 22)
        emu._data_write(emu.DATA_TWDR, 0x50)  # SLA+W for address 0x28: nobody there
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        self._run(emu, 145)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, 0x20)

        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 22)
        emu._data_write(emu.DATA_TWDR, 0x78)  # SLA+W for address 0x3C
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        self._run(emu, 145)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MT_SLA_ACK)

    def test_bit_time_follows_twbr(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWBR, 12)  # 16 + 2 * 12 = 40 cycles per bit
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 45)  # one SCL period (40) + 6 cycles for the START
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWINT_BIT) & 1, 0)
        self._run(emu, 1)
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWINT_BIT) & 1, 1)

    def test_start_condition_sets_status_and_twint(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))

        self._run(emu, 22)

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_START)
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWINT_BIT) & 1, 1)
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWSTA_BIT) & 1, 0)

    def test_master_transmit_address_and_data_ack_path(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 22)

        emu._data_write(emu.DATA_TWDR, 0x50)  # SLA+W for address 0x28
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        self._run(emu, 145)

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MT_SLA_ACK)

        emu._data_write(emu.DATA_TWDR, 0xAB)
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        self._run(emu, 145)

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MT_DATA_ACK)
        self.assertEqual(emu.twi_transmitted_bytes, [0xAB])

    def test_master_receive_loads_twdr_and_status(self) -> None:
        emu = self._new_emu()
        emu.queue_twi_read_bytes([0x5E])
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 22)

        emu._data_write(emu.DATA_TWDR, 0x51)  # SLA+R for address 0x28
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT))
        self._run(emu, 145)

        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MR_SLA_ACK)

        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWEA_BIT))
        self._run(emu, 145)

        self.assertEqual(emu.data[emu.DATA_TWDR], 0x5E)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, emu.TWI_STATUS_MR_DATA_ACK)

    def test_twi_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu._data_write(
            emu.DATA_TWCR,
            (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWIE_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT),
        )

        self._run(emu, 23)  # 22 cycles for the START, then one instruction

        self.assertEqual(emu.pc, emu.VECTOR_TWI)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_stop_condition_returns_twi_to_idle(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTA_BIT))
        self._run(emu, 22)

        emu._data_write(emu.DATA_TWCR, (1 << emu.TWCR_TWEN_BIT) | (1 << emu.TWCR_TWINT_BIT) | (1 << emu.TWCR_TWSTO_BIT))

        self.assertEqual(emu._twi_state, "idle")
        self.assertEqual((emu.data[emu.DATA_TWCR] >> emu.TWCR_TWSTO_BIT) & 1, 0)
        self.assertEqual(emu.data[emu.DATA_TWSR] & 0xF8, 0xF8)


if __name__ == "__main__":
    unittest.main()
