import unittest

from avr_encoding import ldi, lds, sts
from sim import ATmega2560Emulator


def regop(base: int, r: int) -> int:
    return base | ((r & 0x1F) << 4)


class TestCoreInvariants(unittest.TestCase):
    def run_steps(self, program: list[int], steps: int | None = None) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words(program)
        n = len(program) if steps is None else steps
        for _ in range(n):
            emu.step()
        return emu

    def test_inc_dec_shift_swap_and_lpm(self) -> None:
        # Program bytes in flash:
        # [0]=LDI r30,0  [1]=LDI r31,0  [2]=LPM r16,Z+ reads low byte of word0 (=0xE0)
        # [3]=INC r16    [4]=DEC r16    [5]=SWAP r16 [6]=LSR r16 [7]=ASR r16 [8]=ROR r16
        program = [
            ldi(30, 0x00),
            ldi(31, 0x00),
            regop(0x9005, 16),  # LPM r16, Z+
            regop(0x9403, 16),  # INC r16
            regop(0x940A, 16),  # DEC r16
            regop(0x9402, 16),  # SWAP r16
            regop(0x9406, 16),  # LSR r16
            regop(0x9405, 16),  # ASR r16
            regop(0x9407, 16),  # ROR r16
        ]
        emu = self.run_steps(program)
        self.assertEqual(emu.reg[30] | (emu.reg[31] << 8), 1)  # Z advanced by LPM Z+
        self.assertEqual(emu.reg[16], 0x81)

    def test_bset_bclr_and_sbi_cbi(self) -> None:
        program = [
            0x9478,  # BSET 7 (I)
            0x94F8,  # BCLR 7
            0x9A00,  # SBI 0x00,0
            0x9800,  # CBI 0x00,0
        ]
        emu = self.run_steps(program)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.data[0x20 + 0x00] & 1, 0)

    def test_memory_map_guards(self) -> None:
        # Write to invalid data address > 0x21FF should be ignored, read should return 0.
        program = [
            ldi(16, 0xAB),
            *sts(16, 0x3000),
            *lds(17, 0x3000),
        ]
        emu = self.run_steps(program)
        self.assertEqual(emu.reg[17], 0x00)
        self.assertEqual(emu.data[0x3000], 0x00)

    def test_sts_lds_can_access_stack_pointer_registers(self) -> None:
        # Marlin (and libc startup/runtime) can use data-space SPL/SPH access.
        # Ensure STS/LDS and internal SP stay coherent.
        program = [
            ldi(16, 0x34),
            *sts(16, ATmega2560Emulator.DATA_SPL),
            ldi(17, 0x12),
            *sts(17, ATmega2560Emulator.DATA_SPH),
            *lds(18, ATmega2560Emulator.DATA_SPL),
            *lds(19, ATmega2560Emulator.DATA_SPH),
        ]
        emu = self.run_steps(program)
        self.assertEqual(emu.sp, 0x1234)
        self.assertEqual(emu.reg[18], 0x34)
        self.assertEqual(emu.reg[19], 0x12)

    def test_elpm_reads_using_nonzero_rampz(self) -> None:
        emu = ATmega2560Emulator()
        # ELPM r16,Z ; ELPM r17,Z+
        emu.load_program_words([regop(0x9006, 16), regop(0x9007, 17)])

        # Place flash data at byte address 0x01_0010 (word index 0x8008).
        target_word = 0x8008
        if len(emu.program) <= target_word:
            emu.program.extend([0x0000] * (target_word + 1 - len(emu.program)))
        emu.program[target_word] = 0xBBAA

        emu.reg[30] = 0x10
        emu.reg[31] = 0x00
        emu.data[ATmega2560Emulator.DATA_RAMPZ] = 0x01

        step1 = emu.step()
        step2 = emu.step()

        self.assertEqual(step1.cycles, 3)
        self.assertEqual(step2.cycles, 3)
        self.assertEqual(emu.reg[16], 0xAA)
        self.assertEqual(emu.reg[17], 0xAA)
        self.assertEqual((emu.reg[31] << 8) | emu.reg[30], 0x0011)

    def test_eijmp_cross_page_control_flow(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x9419])  # EIJMP

        target_pc = 0x10004
        if len(emu.program) <= target_pc:
            emu.program.extend([0x0000] * (target_pc + 1 - len(emu.program)))
        emu.program[target_pc] = ldi(18, 0xA7)

        emu.reg[30] = 0x04
        emu.reg[31] = 0x00
        emu.data[ATmega2560Emulator.DATA_EIND] = 0x01

        step1 = emu.step()
        step2 = emu.step()

        self.assertEqual(step1.cycles, 2)
        self.assertEqual(emu.pc, target_pc + 1)
        self.assertEqual(step2.cycles, 1)
        self.assertEqual(emu.reg[18], 0xA7)

    def test_eicall_cross_page_target_and_ret(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x9519, ldi(19, 0x5A)])  # EICALL ; LDI r19,0x5A

        target_pc = 0x10008
        if len(emu.program) <= target_pc:
            emu.program.extend([0x0000] * (target_pc + 1 - len(emu.program)))
        emu.program[target_pc] = 0x9508  # RET

        emu.reg[30] = 0x08
        emu.reg[31] = 0x00
        emu.data[ATmega2560Emulator.DATA_EIND] = 0x01

        step1 = emu.step()  # EICALL to cross-page target
        self.assertEqual(step1.cycles, 4)
        self.assertEqual(emu.pc, target_pc)

        step2 = emu.step()  # RET back to low page return location
        self.assertEqual(step2.cycles, 5)
        self.assertEqual(emu.pc, 1)

        step3 = emu.step()  # Continue at return location
        self.assertEqual(step3.cycles, 1)
        self.assertEqual(emu.reg[19], 0x5A)

    def test_rcall_ret_preserves_high_pc_bits(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000])

        high_pc = 0x10010
        needed = high_pc + 3
        if len(emu.program) < needed:
            emu.program.extend([0x0000] * (needed - len(emu.program)))

        emu.program[high_pc] = 0xD001  # RCALL +1 -> high_pc + 2
        emu.program[high_pc + 1] = ldi(20, 0x77)
        emu.program[high_pc + 2] = 0x9508  # RET

        emu.pc = high_pc

        step1 = emu.step()
        self.assertEqual(step1.cycles, 4)
        self.assertEqual(emu.pc, high_pc + 2)

        step2 = emu.step()
        self.assertEqual(step2.cycles, 5)
        self.assertEqual(emu.pc, high_pc + 1)

        step3 = emu.step()
        self.assertEqual(step3.cycles, 1)
        self.assertEqual(emu.reg[20], 0x77)


if __name__ == "__main__":
    unittest.main()
