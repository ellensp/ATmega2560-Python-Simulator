import unittest

from sim import ATmega2560Emulator


class TestGPIOBehavior(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)
        return emu

    def test_input_pullup_reads_high_when_pin_is_undriven(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = 1 << 2

        self.assertEqual(emu._data_read(pin_addr), 1 << 2)
        self.assertEqual(emu._io_read(pin_addr - 0x20), 1 << 2)

    def test_external_low_overrides_pullup_on_input_pin(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = 1 << 2
        emu.set_pin_level("B", 2, 0)

        self.assertEqual(emu._data_read(pin_addr), 0x00)

    def test_releasing_external_drive_restores_pullup_level(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = 1 << 2
        emu.set_pin_level("B", 2, 0)

        self.assertEqual(emu._data_read(pin_addr), 0x00)

        emu.release_pin_level("B", 2)

        self.assertEqual(emu._data_read(pin_addr), 1 << 2)

    def test_releasing_external_drive_without_pullup_reads_low(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = 0x00
        emu.set_pin_level("B", 2, 1)

        self.assertEqual(emu._data_read(pin_addr), 1 << 2)

        emu.release_pin_level("B", 2)

        self.assertEqual(emu._data_read(pin_addr), 0x00)

    def test_output_pin_reads_port_latch_not_external_level(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["B"]
        emu.data[ddr_addr] = 1 << 1
        emu.data[port_addr] = 1 << 1
        emu.set_pin_level("B", 1, 0)

        self.assertEqual(emu._data_read(pin_addr), 1 << 1)

    def test_writing_pin_register_toggles_port_latch_bits(self) -> None:
        emu = self._new_emu()
        pin_addr, _, port_addr = emu.GPIO_PORTS["B"]
        emu.data[port_addr] = 0b00000011

        emu._data_write(pin_addr, 0b00000101)

        self.assertEqual(emu.data[port_addr], 0b00000110)

    def test_high_port_reads_and_pin_toggle_follow_gpio_rules(self) -> None:
        emu = self._new_emu()
        pin_addr, ddr_addr, port_addr = emu.GPIO_PORTS["K"]
        emu.data[ddr_addr] = 0x00
        emu.data[port_addr] = 1 << 4

        self.assertEqual(emu._data_read(pin_addr), 1 << 4)

        emu._data_write(pin_addr, 1 << 4)

        self.assertEqual(emu.data[port_addr], 0x00)
        self.assertEqual(emu._data_read(pin_addr), 0x00)


if __name__ == "__main__":
    unittest.main()
