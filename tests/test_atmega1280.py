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

        emu.step()  # NOP: TOV0 set
        emu.step()  # NOP, then the interrupt is entered

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_OVF)
        self.assertEqual(emu.sp, 0x21FD)
        self.assertEqual(emu.data[0x21FF], 0x02)
        self.assertEqual(emu.data[0x21FE], 0x00)
        self.assertEqual(emu.cycles, 6)  # 2 NOPs + 4 cycle interrupt entry


class TestCallReturnCycles(unittest.TestCase):
    """CALL/RCALL/ICALL/RET/RETI take one more cycle with a 22-bit PC (ATmega2560); interrupt entry doesn't."""

    def cycles(self, cls, program: list[int], steps: int = 1, z: int = 0, sp: int | None = None) -> int:
        emu = cls()
        emu.load_program_words(program)
        emu.reg[30] = z & 0xFF
        emu.reg[31] = z >> 8
        if sp is not None:
            emu.sp = sp
        result = None
        for _ in range(steps):
            result = emu.step()
        assert result is not None
        return result.cycles

    def check(self, program: list[int], cycles_1280: int, cycles_2560: int, **kw) -> None:
        self.assertEqual(self.cycles(ATmega1280Emulator, program, **kw), cycles_1280)
        self.assertEqual(self.cycles(ATmega2560Emulator, program, **kw), cycles_2560)

    def test_call(self) -> None:
        self.check([*call(0x0100)], 4, 5)

    def test_rcall(self) -> None:
        self.check([0xD000], 3, 4)  # RCALL +0

    def test_icall(self) -> None:
        self.check([0x9509], 3, 4, z=1)

    def test_ret(self) -> None:
        self.check([0x9508], 4, 5, sp=0x0200)

    def test_reti(self) -> None:
        self.check([0x9518], 4, 5, sp=0x0200)

    def test_interrupt_entry(self) -> None:
        # Interrupt entry takes 4 cycles on both (measured on a real ATmega2560).
        for cls in (ATmega1280Emulator, ATmega2560Emulator):
            emu = cls()
            emu.load_program_words([0x0000] * 64)
            emu._set_flag(emu.FLAG_I, 1)
            emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
            emu.data[0x20 + 0x26] = 0xFF  # overflow on next tick
            emu.data[0x006E] = 0x01       # TIMSK0 TOIE0
            emu.step()
            emu.step()
            self.assertEqual(emu.cycles, 2 + 4, cls.__name__)


if __name__ == "__main__":
    unittest.main()
