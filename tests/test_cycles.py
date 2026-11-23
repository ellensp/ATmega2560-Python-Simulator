import unittest

from avr_encoding import call, cpse, jmp, ldi, out, rcall, rjmp
from sim import ATmega2560Emulator


def enc_reg_reg(base: int, rd: int, rr: int) -> int:
    return base | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def op_add(rd: int, rr: int) -> int:
    return enc_reg_reg(0x0C00, rd, rr)


def op_push(rr: int) -> int:
    return 0x920F | ((rr & 0x1F) << 4)


def op_pop(rd: int) -> int:
    return 0x900F | ((rd & 0x1F) << 4)


def op_brbs(bit: int, k: int) -> int:
    return 0xF000 | ((k & 0x7F) << 3) | (bit & 0x7)


def op_sts(rr: int, addr16: int) -> tuple[int, int]:
    return (0x9200 | ((rr & 0x1F) << 4), addr16 & 0xFFFF)


def op_lds(rd: int, addr16: int) -> tuple[int, int]:
    return (0x9000 | ((rd & 0x1F) << 4), addr16 & 0xFFFF)


def op_sbrc(rr: int, bit: int) -> int:
    return 0xFC00 | ((rr & 0x1F) << 4) | (bit & 0x7)


def op_sbrs(rr: int, bit: int) -> int:
    return 0xFE00 | ((rr & 0x1F) << 4) | (bit & 0x7)


def op_sbic(io_addr: int, bit: int) -> int:
    return 0x9900 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


def op_sbis(io_addr: int, bit: int) -> int:
    return 0x9B00 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


class TestAVRCycleCounts(unittest.TestCase):
    def step_cycles(self, program: list[int], step_index: int = 0) -> int:
        emu = ATmega2560Emulator()
        emu.load_program_words(program)
        result = None
        for _ in range(step_index + 1):
            result = emu.step()
        assert result is not None
        return result.cycles

    def test_nop_is_1_cycle(self) -> None:
        self.assertEqual(self.step_cycles([0x0000]), 1)

    def test_add_is_1_cycle(self) -> None:
        cycles = self.step_cycles([
            ldi(16, 1),
            ldi(17, 2),
            op_add(16, 17),
        ], step_index=2)
        self.assertEqual(cycles, 1)

    def test_rjmp_is_2_cycles(self) -> None:
        self.assertEqual(self.step_cycles([rjmp(0)]), 2)

    def test_brbs_taken_vs_not_taken(self) -> None:
        # Taken path: set Z then branch on Z.
        taken_program = [
            ldi(16, 0x10),
            # CPI r16, 0x10
            0x3010,
            op_brbs(1, 0),
        ]
        self.assertEqual(self.step_cycles(taken_program, step_index=2), 2)

        # Not-taken path: Z is clear after reset.
        not_taken_program = [
            op_brbs(1, 0),
        ]
        self.assertEqual(self.step_cycles(not_taken_program), 1)

    def test_push_pop_cycles(self) -> None:
        push_cycles = self.step_cycles([ldi(16, 0xAA), op_push(16)], step_index=1)
        pop_cycles = self.step_cycles([op_pop(16)], step_index=0)
        self.assertEqual(push_cycles, 2)
        self.assertEqual(pop_cycles, 2)

    def test_rcall_and_ret_cycles(self) -> None:
        program = [
            rcall(1),   # step 0
            0x0000,     # return location
            0x9508,     # RET target
        ]
        self.assertEqual(self.step_cycles(program, step_index=0), 4)
        self.assertEqual(self.step_cycles(program, step_index=1), 5)

    def test_lds_sts_cycles(self) -> None:
        program = [
            ldi(16, 0x55),
            *op_sts(16, 0x0123),
            *op_lds(17, 0x0123),
        ]
        self.assertEqual(self.step_cycles(program, step_index=1), 2)
        self.assertEqual(self.step_cycles(program, step_index=2), 2)

    def test_jmp_call_cycles(self) -> None:
        call_program = [
            *call(3),
            0x0000,
            0x0000,
            0x9508,
        ]
        self.assertEqual(self.step_cycles(call_program, step_index=0), 5)

        jmp_program = [
            *jmp(2),
            0x0000,
            0x0000,
        ]
        self.assertEqual(self.step_cycles(jmp_program, step_index=0), 3)

    def test_cpse_skip_costs(self) -> None:
        # Skip one-word instruction => 2 cycles
        program_one = [
            ldi(16, 1),
            ldi(17, 1),
            cpse(16, 17),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(program_one, step_index=2), 2)

        # Skip two-word instruction => 3 cycles
        program_two = [
            ldi(16, 1),
            ldi(17, 1),
            cpse(16, 17),
            *call(8),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(program_two, step_index=2), 3)

    def test_sbrc_and_sbrs_skip_costs(self) -> None:
        # SBRC taken over 1-word -> 2 cycles.
        sbrc_one = [
            ldi(16, 0x00),
            op_sbrc(16, 0),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbrc_one, step_index=1), 2)

        # SBRC taken over 2-word -> 3 cycles.
        sbrc_two = [
            ldi(16, 0x00),
            op_sbrc(16, 0),
            *call(7),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbrc_two, step_index=1), 3)

        # SBRS taken over 1-word -> 2 cycles.
        sbrs_one = [
            ldi(16, 0x01),
            op_sbrs(16, 0),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbrs_one, step_index=1), 2)

        # SBRS taken over 2-word -> 3 cycles.
        sbrs_two = [
            ldi(16, 0x01),
            op_sbrs(16, 0),
            *jmp(7),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbrs_two, step_index=1), 3)

    def test_sbic_and_sbis_skip_costs(self) -> None:
        io_addr = 0x1E  # GPIOR0-style plain I/O location for deterministic SBIC/SBIS behavior.

        # Clear I/O bit for SBIC taken path.
        sbic_one = [
            ldi(16, 0x00),
            out(io_addr, 16),
            op_sbic(io_addr, 0),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbic_one, step_index=2), 2)

        sbic_two = [
            ldi(16, 0x00),
            out(io_addr, 16),
            op_sbic(io_addr, 0),
            *call(9),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbic_two, step_index=2), 3)

        # Set I/O bit for SBIS taken path.
        sbis_one = [
            ldi(16, 0x01),
            out(io_addr, 16),
            op_sbis(io_addr, 0),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbis_one, step_index=2), 2)

        sbis_two = [
            ldi(16, 0x01),
            out(io_addr, 16),
            op_sbis(io_addr, 0),
            *jmp(9),
            0x0000,
        ]
        self.assertEqual(self.step_cycles(sbis_two, step_index=2), 3)

    def test_indirect_and_extended_indirect_control_flow_cycles(self) -> None:
        ijmp_program = [
            0x9409,  # IJMP
        ]
        emu = ATmega2560Emulator()
        emu.load_program_words(ijmp_program)
        emu.reg[30] = 0x00
        emu.reg[31] = 0x00
        self.assertEqual(emu.step().cycles, 2)

        icall_program = [
            0x9509,  # ICALL
            0x9508,  # RET at target 1
        ]
        emu = ATmega2560Emulator()
        emu.load_program_words(icall_program)
        emu.reg[30] = 0x01
        emu.reg[31] = 0x00
        self.assertEqual(emu.step().cycles, 4)

        eijmp_program = [0x9419]
        emu = ATmega2560Emulator()
        emu.load_program_words(eijmp_program)
        emu.reg[30] = 0x00
        emu.reg[31] = 0x00
        emu.data[ATmega2560Emulator.DATA_EIND] = 0x01
        self.assertEqual(emu.step().cycles, 2)

        eicall_program = [0x9519]
        emu = ATmega2560Emulator()
        emu.load_program_words(eicall_program)
        emu.reg[30] = 0x00
        emu.reg[31] = 0x00
        emu.data[ATmega2560Emulator.DATA_EIND] = 0x01
        self.assertEqual(emu.step().cycles, 4)


if __name__ == "__main__":
    unittest.main()
