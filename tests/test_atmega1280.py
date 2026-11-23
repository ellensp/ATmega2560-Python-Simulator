import unittest

from avr_encoding import call
from sim import ATmega1280Emulator, ATmega2560Emulator, create_emulator


class TestCreateEmulator(unittest.TestCase):
    def test_names(self) -> None:
        self.assertIs(type(create_emulator()), ATmega2560Emulator)
        self.assertIs(type(create_emulator("atmega2560")), ATmega2560Emulator)
        self.assertIs(type(create_emulator("ATmega1280")), ATmega1280Emulator)
        self.assertIs(type(create_emulator("1280")), ATmega1280Emulator)

    def test_unknown_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            create_emulator("atmega328p")


class TestATmega1280(unittest.TestCase):
    def test_flash_size(self) -> None:
        self.assertEqual(ATmega1280Emulator.FLASH_SIZE_BYTES, 128 * 1024)
        self.assertEqual(ATmega1280Emulator.PC_WORD_MASK, 0xFFFF)
        self.assertEqual(ATmega2560Emulator.PC_WORD_MASK, 0x1FFFF)

    def test_call_pushes_two_byte_return_address(self) -> None:
        emu = ATmega1280Emulator()
        emu.load_program_words([*call(0x0100)])

        emu.step()

        self.assertEqual(emu.pc, 0x0100)
        self.assertEqual(emu.sp, 0x21FD)
        self.assertEqual(emu.data[0x21FF], 0x02)  # return PC low byte
        self.assertEqual(emu.data[0x21FE], 0x00)  # return PC high byte

    def test_ret_pops_two_byte_return_address(self) -> None:
        emu = ATmega1280Emulator()
        emu.load_program_words([0x9508])  # RET
        emu.sp = 0x0200
        emu.data[0x0201] = 0x12
        emu.data[0x0202] = 0x34

        emu.step()

        self.assertEqual(emu.pc, 0x1234)
        self.assertEqual(emu.sp, 0x0202)

    def test_interrupt_entry_pushes_two_byte_return_address(self) -> None:
        emu = ATmega1280Emulator()
        emu.load_program_words([0x0000] * 64)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFF  # overflow on next tick
        emu.data[0x006E] = 0x01       # TIMSK0 TOIE0

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_OVF)
        self.assertEqual(emu.sp, 0x21FD)
        self.assertEqual(emu.data[0x21FF], 0x01)
        self.assertEqual(emu.data[0x21FE], 0x00)


if __name__ == "__main__":
    unittest.main()
