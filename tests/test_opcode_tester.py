import subprocess
import sys
import unittest

from avr_encoding import brbc, brbs, call, cpse, cpi, in_, jmp, ldi, lds, out, pop, push, rcall, rjmp, sts
from opcode_tester import OpcodeTestCase, run_opcode_test_case


def rr_op(base: int, rd: int, rr: int) -> int:
    return base | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def add(rd: int, rr: int) -> int:
    return rr_op(0x0C00, rd, rr)


def adc(rd: int, rr: int) -> int:
    return rr_op(0x1C00, rd, rr)


def sub(rd: int, rr: int) -> int:
    return rr_op(0x1800, rd, rr)


def sbc(rd: int, rr: int) -> int:
    return rr_op(0x0800, rd, rr)


def cpc(rd: int, rr: int) -> int:
    return rr_op(0x0400, rd, rr)


def cp(rd: int, rr: int) -> int:
    return rr_op(0x1400, rd, rr)


def and_(rd: int, rr: int) -> int:
    return rr_op(0x2000, rd, rr)


def or_(rd: int, rr: int) -> int:
    return rr_op(0x2800, rd, rr)


def eor(rd: int, rr: int) -> int:
    return rr_op(0x2400, rd, rr)


def subi(rd: int, imm: int) -> int:
    return 0x5000 | ((imm & 0xF0) << 4) | ((rd - 16) << 4) | (imm & 0x0F)


def sbci(rd: int, imm: int) -> int:
    return 0x4000 | ((imm & 0xF0) << 4) | ((rd - 16) << 4) | (imm & 0x0F)


def andi(rd: int, imm: int) -> int:
    return 0x7000 | ((imm & 0xF0) << 4) | ((rd - 16) << 4) | (imm & 0x0F)


def ori(rd: int, imm: int) -> int:
    return 0x6000 | ((imm & 0xF0) << 4) | ((rd - 16) << 4) | (imm & 0x0F)


def mov(rd: int, rr: int) -> int:
    return rr_op(0x2C00, rd, rr)


def movw(rd_even: int, rr_even: int) -> int:
    return 0x0100 | (((rd_even // 2) & 0x0F) << 4) | ((rr_even // 2) & 0x0F)


def adiw(rd_pair_base: int, k: int) -> int:
    # rd_pair_base in {24, 26, 28, 30}
    dd = (rd_pair_base - 24) // 2
    return 0x9600 | ((k & 0x30) << 2) | (dd << 4) | (k & 0x0F)


def sbiw(rd_pair_base: int, k: int) -> int:
    dd = (rd_pair_base - 24) // 2
    return 0x9700 | ((k & 0x30) << 2) | (dd << 4) | (k & 0x0F)


def op_single(base: int, rd: int) -> int:
    return base | ((rd & 0x1F) << 4)


def mul(rd: int, rr: int) -> int:
    return rr_op(0x9C00, rd, rr)


def muls(rd: int, rr: int) -> int:
    # MULS supports r16..r31.
    return 0x0200 | (((rd - 16) & 0x0F) << 4) | ((rr - 16) & 0x0F)


def mulsu(rd: int, rr: int) -> int:
    # MULSU supports r16..r23.
    return 0x0300 | (((rd - 16) & 0x07) << 4) | ((rr - 16) & 0x07)


def fmul(rd: int, rr: int) -> int:
    # FMUL supports r16..r23.
    return 0x0308 | (((rd - 16) & 0x07) << 4) | ((rr - 16) & 0x07)


def fmuls(rd: int, rr: int) -> int:
    # FMULS supports r16..r23.
    return 0x0380 | (((rd - 16) & 0x07) << 4) | ((rr - 16) & 0x07)


def fmulsu(rd: int, rr: int) -> int:
    # FMULSU supports r16..r23.
    return 0x0388 | (((rd - 16) & 0x07) << 4) | ((rr - 16) & 0x07)


def ldd(ptr: str, rd: int, q: int) -> int:
    base = 0x8008 if ptr.upper() == "Y" else 0x8000
    q &= 0x3F
    return (
        base
        | ((rd & 0x1F) << 4)
        | (q & 0x7)
        | ((q & 0x18) << 7)
        | ((q & 0x20) << 8)
    )


def std(ptr: str, rr: int, q: int) -> int:
    base = 0x8208 if ptr.upper() == "Y" else 0x8200
    q &= 0x3F
    return (
        base
        | ((rr & 0x1F) << 4)
        | (q & 0x7)
        | ((q & 0x18) << 7)
        | ((q & 0x20) << 8)
    )


def bld(rd: int, bit: int) -> int:
    return 0xF800 | ((rd & 0x1F) << 4) | (bit & 0x7)


def bst(rr: int, bit: int) -> int:
    return 0xFA00 | ((rr & 0x1F) << 4) | (bit & 0x7)


def sbrc(rr: int, bit: int) -> int:
    return 0xFC00 | ((rr & 0x1F) << 4) | (bit & 0x7)


def sbrs(rr: int, bit: int) -> int:
    return 0xFE00 | ((rr & 0x1F) << 4) | (bit & 0x7)


def sbic(io_addr: int, bit: int) -> int:
    return 0x9900 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


def sbis(io_addr: int, bit: int) -> int:
    return 0x9B00 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


def op_z_atomic(base: int, rd: int) -> int:
    return base | ((rd & 0x1F) << 4)


def xch(rd: int) -> int:
    return op_z_atomic(0x9204, rd)


def las(rd: int) -> int:
    return op_z_atomic(0x9205, rd)


def lac(rd: int) -> int:
    return op_z_atomic(0x9206, rd)


def lat(rd: int) -> int:
    return op_z_atomic(0x9207, rd)


def elpm(rd: int | None = None, post_inc: bool = False) -> int:
    if rd is None:
        return 0x95D8
    return (0x9007 if post_inc else 0x9006) | ((rd & 0x1F) << 4)


def lpm_rd_z(rd: int) -> int:
    return 0x9004 | ((rd & 0x1F) << 4)


def sbi(io_addr: int, bit: int) -> int:
    return 0x9A00 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


def cbi(io_addr: int, bit: int) -> int:
    return 0x9800 | ((io_addr & 0x1F) << 3) | (bit & 0x7)


def bset(bit: int) -> int:
    return 0x9408 | ((bit & 0x7) << 4)


def bclr(bit: int) -> int:
    return 0x9488 | ((bit & 0x7) << 4)


def ld_x(rd: int) -> int:
    return 0x900C | ((rd & 0x1F) << 4)


def st_x(rr: int) -> int:
    return 0x920C | ((rr & 0x1F) << 4)


def ld_x_post(rd: int) -> int:
    return 0x900D | ((rd & 0x1F) << 4)


def st_x_post(rr: int) -> int:
    return 0x920D | ((rr & 0x1F) << 4)


def ld_pre_x(rd: int) -> int:
    return 0x900E | ((rd & 0x1F) << 4)


def st_pre_x(rr: int) -> int:
    return 0x920E | ((rr & 0x1F) << 4)


def ld_y(rd: int) -> int:
    return 0x8008 | ((rd & 0x1F) << 4)


def ld_y_post(rd: int) -> int:
    return 0x9009 | ((rd & 0x1F) << 4)


def ld_pre_y(rd: int) -> int:
    return 0x900A | ((rd & 0x1F) << 4)


def ld_z(rd: int) -> int:
    return 0x8000 | ((rd & 0x1F) << 4)


def ld_z_post(rd: int) -> int:
    return 0x9001 | ((rd & 0x1F) << 4)


def ld_pre_z(rd: int) -> int:
    return 0x9002 | ((rd & 0x1F) << 4)


def st_y(rr: int) -> int:
    return 0x8208 | ((rr & 0x1F) << 4)


def st_y_post(rr: int) -> int:
    return 0x9209 | ((rr & 0x1F) << 4)


def st_pre_y(rr: int) -> int:
    return 0x920A | ((rr & 0x1F) << 4)


def st_z(rr: int) -> int:
    return 0x8200 | ((rr & 0x1F) << 4)


def st_z_post(rr: int) -> int:
    return 0x9201 | ((rr & 0x1F) << 4)


def st_pre_z(rr: int) -> int:
    return 0x9202 | ((rr & 0x1F) << 4)


def lpm() -> int:
    return 0x95C8


def lpm_rd_z_post(rd: int) -> int:
    return 0x9005 | ((rd & 0x1F) << 4)


class TestOpcodeTesterMatrix(unittest.TestCase):
    def test_matrix_registers_flags_and_cycles(self) -> None:
        cases = [
            OpcodeTestCase(
                program_words=[add(16, 17)],
                init_regs={16: 0x7F, 17: 0x01},
                expect_regs={16: 0x80},
                expect_flags={"N": 1, "V": 1, "S": 0, "H": 1, "Z": 0, "C": 0},
                expect_cycles=1,
            ),
            OpcodeTestCase(
                program_words=[adc(16, 17)],
                init_regs={16: 0x00, 17: 0x00},
                init_flags={"C": 1},
                expect_regs={16: 0x01},
                expect_flags={"C": 0, "Z": 0},
            ),
            OpcodeTestCase(
                program_words=[adc(16, 17)],
                init_regs={16: 0xFF, 17: 0x00},
                init_flags={"C": 1},
                expect_regs={16: 0x00},
                expect_flags={"C": 1, "Z": 1, "H": 1, "N": 0, "V": 0, "S": 0},
            ),
            OpcodeTestCase(
                program_words=[add(16, 16)],
                init_regs={16: 0x40},
                expect_regs={16: 0x80},
                expect_desc="LSL r16",
            ),
            OpcodeTestCase(
                program_words=[adc(16, 16)],
                init_regs={16: 0x80},
                init_flags={"C": 0},
                expect_regs={16: 0x00},
                expect_flags={"C": 1, "Z": 1},
                expect_desc="ROL r16",
            ),
            OpcodeTestCase(
                program_words=[sub(16, 17)],
                init_regs={16: 0x10, 17: 0x20},
                expect_regs={16: 0xF0},
                expect_flags={"N": 1, "C": 1, "Z": 0},
            ),
            OpcodeTestCase(
                program_words=[sbc(16, 17)],
                init_regs={16: 0x01, 17: 0x01},
                init_flags={"C": 1, "Z": 0},
                expect_regs={16: 0xFF},
                expect_flags={"Z": 0, "C": 1},
            ),
            OpcodeTestCase(
                program_words=[cpc(16, 17)],
                init_regs={16: 0x20, 17: 0x20},
                init_flags={"C": 0, "Z": 1},
                expect_regs={16: 0x20},
                expect_flags={"Z": 1, "C": 0},
            ),
            OpcodeTestCase(
                program_words=[cp(16, 17)],
                init_regs={16: 0x10, 17: 0x10},
                expect_regs={16: 0x10},
                expect_flags={"Z": 1, "C": 0, "N": 0},
            ),
            OpcodeTestCase(
                program_words=[cpi(20, 0x10)],
                init_regs={20: 0x01},
                expect_regs={20: 0x01},
                expect_flags={"C": 1, "Z": 0, "N": 1},
            ),
            OpcodeTestCase(
                program_words=[and_(16, 17)],
                init_regs={16: 0xF0, 17: 0x0F},
                expect_regs={16: 0x00},
                expect_flags={"Z": 1, "N": 0, "V": 0, "S": 0},
            ),
            OpcodeTestCase(
                program_words=[or_(16, 17)],
                init_regs={16: 0x80, 17: 0x01},
                expect_regs={16: 0x81},
                expect_flags={"Z": 0, "N": 1, "V": 0, "S": 1},
            ),
            OpcodeTestCase(
                program_words=[eor(16, 17)],
                init_regs={16: 0xAA, 17: 0xFF},
                expect_regs={16: 0x55},
                expect_flags={"N": 0, "Z": 0},
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x33), mov(17, 16)],
                expect_regs={16: 0x33, 17: 0x33},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[movw(24, 30)],
                init_regs={30: 0x34, 31: 0x12},
                expect_regs={24: 0x34, 25: 0x12},
            ),
            OpcodeTestCase(
                program_words=[subi(20, 0x01), andi(20, 0x0F), ori(20, 0x80)],
                init_regs={20: 0x11},
                expect_regs={20: 0x80},
                expect_flags={"N": 1, "Z": 0},
            ),
            OpcodeTestCase(
                program_words=[sbci(20, 0x01)],
                init_regs={20: 0x10},
                init_flags={"C": 1, "Z": 1},
                expect_regs={20: 0x0E},
                expect_flags={"C": 0, "Z": 0, "N": 0},
            ),
            OpcodeTestCase(
                program_words=[adiw(24, 1)],
                init_regs={24: 0xFF, 25: 0x7F},
                expect_regs={24: 0x00, 25: 0x80},
                expect_flags={"N": 1, "V": 1, "S": 0, "Z": 0, "C": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbiw(24, 1)],
                init_regs={24: 0x00, 25: 0x00},
                expect_regs={24: 0xFF, 25: 0xFF},
                expect_flags={"N": 1, "V": 0, "S": 1, "Z": 0, "C": 1},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9403, 16), op_single(0x940A, 16)],  # INC, DEC
                init_regs={16: 0x00},
                expect_regs={16: 0x00},
                expect_flags={"Z": 1, "N": 0},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9406, 16)],  # LSR
                init_regs={16: 0x01},
                expect_regs={16: 0x00},
                expect_flags={"C": 1, "Z": 1, "N": 0, "V": 1, "S": 1},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9405, 16)],  # ASR
                init_regs={16: 0x81},
                expect_regs={16: 0xC0},
                expect_flags={"C": 1, "N": 1, "V": 0, "S": 1},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9407, 16)],  # ROR
                init_regs={16: 0x02},
                init_flags={"C": 1},
                expect_regs={16: 0x81},
                expect_flags={"C": 0, "N": 1, "V": 1, "S": 0},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9402, 16)],  # SWAP
                init_regs={16: 0xA5},
                expect_regs={16: 0x5A},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9400, 16)],  # COM
                init_regs={16: 0xFF},
                expect_regs={16: 0x00},
                expect_flags={"C": 1, "Z": 1, "N": 0, "V": 0, "S": 0},
            ),
            OpcodeTestCase(
                program_words=[op_single(0x9401, 16)],  # NEG
                init_regs={16: 0x01},
                expect_regs={16: 0xFF},
                expect_flags={"C": 1, "Z": 0, "N": 1, "V": 0, "S": 1, "H": 1},
            ),
            OpcodeTestCase(
                program_words=[mul(16, 17)],
                init_regs={16: 0x10, 17: 0x10},
                expect_regs={0: 0x00, 1: 0x01},
                expect_flags={"C": 0, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[muls(16, 17)],
                init_regs={16: 0xFF, 17: 0x02},
                expect_regs={0: 0xFE, 1: 0xFF},
                expect_flags={"C": 1, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[mulsu(16, 17)],
                init_regs={16: 0xFE, 17: 0x03},
                expect_regs={0: 0xFA, 1: 0xFF},
                expect_flags={"C": 1, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[fmul(16, 17)],
                init_regs={16: 0x80, 17: 0x02},
                expect_regs={0: 0x00, 1: 0x02},
                expect_flags={"C": 0, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[fmuls(16, 17)],
                init_regs={16: 0xFF, 17: 0xFF},
                expect_regs={0: 0x02, 1: 0x00},
                expect_flags={"C": 0, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[fmulsu(16, 17)],
                init_regs={16: 0xFF, 17: 0x02},
                expect_regs={0: 0xFC, 1: 0xFF},
                expect_flags={"C": 1, "Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[0x9478, 0x94E8],  # BSET I, BCLR T
                init_flags={"T": 1, "I": 0},
                expect_flags={"I": 1, "T": 0},
            ),
            OpcodeTestCase(
                program_words=[0x9408, 0x9488],  # SEC, CLC
                init_flags={"C": 0},
                expect_flags={"C": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[0x9478, 0x94F8],  # SEI, CLI
                init_flags={"I": 0},
                expect_flags={"I": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                # Full BSET sweep over all SREG bits 0..7.
                program_words=[bset(bit) for bit in range(8)],
                init_flags={"C": 0, "Z": 0, "N": 0, "V": 0, "S": 0, "H": 0, "T": 0, "I": 0},
                expect_flags={"C": 1, "Z": 1, "N": 1, "V": 1, "S": 1, "H": 1, "T": 1, "I": 1},
                expect_desc="SEI",
                expect_cycles=8,
            ),
            OpcodeTestCase(
                # Full BCLR sweep over all SREG bits 0..7.
                program_words=[bclr(bit) for bit in range(8)],
                init_flags={"C": 1, "Z": 1, "N": 1, "V": 1, "S": 1, "H": 1, "T": 1, "I": 1},
                expect_flags={"C": 0, "Z": 0, "N": 0, "V": 0, "S": 0, "H": 0, "T": 0, "I": 0},
                expect_desc="CLI",
                expect_cycles=8,
            ),
            OpcodeTestCase(
                program_words=[0x9418, 0x9498],  # SEZ, CLZ
                init_flags={"Z": 0},
                expect_flags={"Z": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[0x9428, 0x94A8, 0x9438, 0x94B8, 0x9448, 0x94C8, 0x9458, 0x94D8, 0x9468, 0x94E8],
                init_flags={"N": 0, "V": 0, "S": 0, "H": 0, "T": 0},
                expect_flags={"N": 0, "V": 0, "S": 0, "H": 0, "T": 0},
                expect_desc="CLT",
                expect_cycles=10,
            ),
            OpcodeTestCase(
                program_words=[0x9588, ldi(16, 0xAA)],  # SLEEP
                expect_regs={16: 0x00},
                expect_pc=1,
                expect_cycles=1,
            ),
            OpcodeTestCase(
                program_words=[0x95A8, ldi(16, 0xAA)],  # WDR
                steps=2,
                expect_regs={16: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[0x9508],  # RET
                init_sp=0x0200,
                init_data={0x0201: 0x01, 0x0202: 0x23, 0x0203: 0x45},  # RET pops from SP+1
                expect_pc=0x12345,
                expect_sp=0x0203,
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[0x9518],  # RETI
                init_sp=0x0100,
                init_data={0x0101: 0x01, 0x0102: 0x23, 0x0103: 0x45},  # RETI pops from SP+1
                expect_pc=0x12345,
                expect_sp=0x0103,
                expect_flags={"I": 1},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[0x9598, ldi(16, 0xAA)],  # BREAK
                expect_regs={16: 0x00},
                expect_pc=1,
                expect_cycles=1,
            ),
            OpcodeTestCase(
                program_words=[0x9409, ldi(16, 0x11), ldi(16, 0x22)],  # IJMP
                init_regs={30: 0x02, 31: 0x00},
                steps=2,
                expect_regs={16: 0x22},
                expect_pc=3,
                expect_cycles=3,
            ),
            OpcodeTestCase(
                # ICALL -> target at 2 -> RET -> continue at 1
                program_words=[0x9509, ldi(16, 0x11), ldi(16, 0x22), 0x9508],
                init_regs={30: 0x02, 31: 0x00},
                steps=4,
                expect_regs={16: 0x11},
                expect_sp=0x21FF,
                expect_pc=2,
                expect_cycles=11,
            ),
            OpcodeTestCase(
                # RCALL -> target at 2 -> RET -> continue at 1
                program_words=[rcall(1), ldi(16, 0x11), ldi(16, 0x22), 0x9508],
                steps=4,
                expect_regs={16: 0x11},
                expect_sp=0x21FF,
                expect_pc=2,
                expect_cycles=11,
            ),
            OpcodeTestCase(
                program_words=[*jmp(0x001234)],
                steps=1,
                expect_pc=0x1234,
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[*call(0x000222)],
                steps=1,
                expect_pc=0x0222,
                expect_sp=0x21FC,
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[0x9419],  # EIJMP
                init_regs={30: 0x34, 31: 0x12},
                init_data={0x005C: 0x01},
                expect_pc=0x11234,
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[0x9519],  # EICALL
                init_regs={30: 0x34, 31: 0x12},
                init_data={0x005C: 0x01},
                expect_pc=0x11234,
                expect_sp=0x21FC,
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[std("Y", 16, 5), ldd("Y", 17, 5)],
                init_regs={16: 0xAB, 28: 0x10, 29: 0x02},
                expect_regs={17: 0xAB},
                expect_data={0x0215: 0xAB},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0xA5), *sts(16, 0x0212), *lds(17, 0x0212)],
                steps=3,
                expect_regs={17: 0xA5},
                expect_data={0x0212: 0xA5},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[std("Z", 18, 9), ldd("Z", 19, 9)],
                init_regs={18: 0x5C, 30: 0x20, 31: 0x02},
                expect_regs={19: 0x5C},
                expect_data={0x0229: 0x5C},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x3C), st_x(16), ld_x(17)],
                init_regs={26: 0x20, 27: 0x02},
                expect_regs={17: 0x3C},
                expect_data={0x0220: 0x3C},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x55), st_x_post(16), ld_pre_x(17)],
                init_regs={26: 0x20, 27: 0x02},
                expect_regs={17: 0x55, 26: 0x20, 27: 0x02},
                expect_data={0x0220: 0x55},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x66), st_pre_x(16), ld_x_post(17)],
                init_regs={26: 0x21, 27: 0x02},
                expect_regs={17: 0x66, 26: 0x21, 27: 0x02},
                expect_data={0x0220: 0x66},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x71), st_y(16), ld_y(17)],
                init_regs={28: 0x20, 29: 0x02},
                expect_regs={17: 0x71},
                expect_data={0x0220: 0x71},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x72), st_y_post(16), ld_pre_y(17)],
                init_regs={28: 0x20, 29: 0x02},
                expect_regs={17: 0x72, 28: 0x20, 29: 0x02},
                expect_data={0x0220: 0x72},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x73), st_pre_y(16), ld_y_post(17)],
                init_regs={28: 0x21, 29: 0x02},
                expect_regs={17: 0x73, 28: 0x21, 29: 0x02},
                expect_data={0x0220: 0x73},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x81), st_z(16), ld_z(17)],
                init_regs={30: 0x20, 31: 0x02},
                expect_regs={17: 0x81},
                expect_data={0x0220: 0x81},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x82), st_z_post(16), ld_pre_z(17)],
                init_regs={30: 0x20, 31: 0x02},
                expect_regs={17: 0x82, 30: 0x20, 31: 0x02},
                expect_data={0x0220: 0x82},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x83), st_pre_z(16), ld_z_post(17)],
                init_regs={30: 0x21, 31: 0x02},
                expect_regs={17: 0x83, 30: 0x21, 31: 0x02},
                expect_data={0x0220: 0x83},
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[lpm()],
                init_regs={30: 0x00, 31: 0x00},
                expect_regs={0: 0xC8},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[lpm_rd_z_post(16), 0x1234],
                init_regs={30: 0x02, 31: 0x00},
                steps=1,
                expect_regs={16: 0x34, 30: 0x03, 31: 0x00},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[elpm()],
                init_regs={30: 0x00, 31: 0x00},
                init_data={0x005B: 0x00},  # RAMPZ
                expect_regs={0: 0xD8},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[elpm(16, post_inc=False), elpm(17, post_inc=True)],
                init_regs={30: 0x00, 31: 0x00},
                init_data={0x005B: 0x00},  # RAMPZ
                expect_regs={16: 0x06, 17: 0x06, 30: 0x01, 31: 0x00},
                expect_cycles=6,
            ),
            OpcodeTestCase(
                program_words=[xch(16)],
                init_regs={16: 0xAA, 30: 0x00, 31: 0x02},
                init_data={0x0200: 0x55},
                expect_regs={16: 0x55},
                expect_data={0x0200: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[las(16)],
                init_regs={16: 0x0F, 30: 0x01, 31: 0x02},
                init_data={0x0201: 0xF0},
                expect_regs={16: 0xF0},
                expect_data={0x0201: 0xFF},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[lac(16)],
                init_regs={16: 0x0F, 30: 0x02, 31: 0x02},
                init_data={0x0202: 0xFF},
                expect_regs={16: 0xFF},
                expect_data={0x0202: 0xF0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[lat(16)],
                init_regs={16: 0x0F, 30: 0x03, 31: 0x02},
                init_data={0x0203: 0xF0},
                expect_regs={16: 0xF0},
                expect_data={0x0203: 0xFF},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                # SPM writes R1:R0 into program word at Z/2; LPM reads back low byte.
                program_words=[0x95E8, lpm_rd_z(16), 0x0000],
                init_regs={0: 0xAB, 1: 0xCD, 30: 0x04, 31: 0x00},
                steps=2,
                expect_regs={16: 0xAB},
                expect_cycles=7,
            ),
            OpcodeTestCase(
                program_words=[0x95F8],  # SPM Z+
                init_regs={0: 0x11, 1: 0x22, 30: 0x08, 31: 0x00},
                expect_regs={30: 0x0A, 31: 0x00},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[brbs(1, 1)],
                init_flags={"Z": 1},
                expect_desc="BREQ +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(1, 1)],
                init_flags={"Z": 0},
                expect_desc="BRNE +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(0, 1)],
                init_flags={"C": 1},
                expect_desc="BRCS +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(0, 1)],
                init_flags={"C": 0},
                expect_desc="BRCC +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(7, 1)],
                init_flags={"I": 1},
                expect_desc="BRIE +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(7, 1)],
                init_flags={"I": 0},
                expect_desc="BRID +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(2, 1)],
                init_flags={"N": 1},
                expect_desc="BRMI +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(2, 1)],
                init_flags={"N": 0},
                expect_desc="BRPL +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(3, 1)],
                init_flags={"V": 1},
                expect_desc="BRVS +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(3, 1)],
                init_flags={"V": 0},
                expect_desc="BRVC +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(4, 1)],
                init_flags={"S": 1},
                expect_desc="BRLT +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(4, 1)],
                init_flags={"S": 0},
                expect_desc="BRGE +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(5, 1)],
                init_flags={"H": 1},
                expect_desc="BRHS +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(5, 1)],
                init_flags={"H": 0},
                expect_desc="BRHC +1",
            ),
            OpcodeTestCase(
                program_words=[brbs(6, 1)],
                init_flags={"T": 1},
                expect_desc="BRTS +1",
            ),
            OpcodeTestCase(
                program_words=[brbc(6, 1)],
                init_flags={"T": 0},
                expect_desc="BRTC +1",
            ),
            OpcodeTestCase(
                program_words=[bst(16, 2), bld(17, 0)],
                init_regs={16: 0x04, 17: 0x00},
                expect_regs={17: 0x01},
                expect_flags={"T": 1},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[bst(16, 2), bld(17, 0)],
                init_regs={16: 0x00, 17: 0xFF},
                expect_regs={17: 0xFE},
                expect_flags={"T": 0},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbi(0x05, 7), cbi(0x05, 7)],
                expect_data={0x25: 0x00},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0xAA), out(0x31, 16), in_(17, 0x31)],
                expect_regs={17: 0xAA},
                expect_data={0x51: 0xAA},
            ),
            OpcodeTestCase(
                program_words=[ldi(16, 0x44), push(16), pop(17)],
                expect_regs={17: 0x44},
                expect_sp=0x21FF,
                expect_cycles=5,
            ),
            OpcodeTestCase(
                program_words=[rjmp(1), ldi(16, 0x11), ldi(16, 0x22)],
                expect_regs={16: 0x22},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[brbs(0, 1), ldi(16, 0x11), ldi(16, 0x22)],
                steps=2,
                init_flags={"C": 1},
                expect_regs={16: 0x22},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[brbc(0, 1), ldi(16, 0x11), ldi(16, 0x22)],
                steps=2,
                init_flags={"C": 0},
                expect_regs={16: 0x22},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[cpse(16, 17), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x12, 17: 0x12},
                expect_regs={18: 0x55},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                program_words=[cpse(16, 17), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x12, 17: 0x13},
                expect_regs={18: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbrc(16, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x00},
                expect_regs={18: 0x55},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                # Skip over two-word instruction.
                program_words=[sbrc(16, 0), *jmp(4), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x00},
                expect_regs={18: 0x55},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[sbrc(16, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x01},
                expect_regs={18: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbrs(16, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x01},
                expect_regs={18: 0x55},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                # Skip over two-word instruction.
                program_words=[sbrs(16, 0), *jmp(4), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x01},
                expect_regs={18: 0x55},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[sbrs(16, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_regs={16: 0x00},
                expect_regs={18: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbic(0x1A, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x00},
                expect_regs={18: 0x55},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                # Skip over two-word instruction.
                program_words=[sbic(0x1A, 0), *jmp(4), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x00},
                expect_regs={18: 0x55},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[sbic(0x1A, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x01},
                expect_regs={18: 0xAA},
                expect_cycles=2,
            ),
            OpcodeTestCase(
                program_words=[sbis(0x1A, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x01},
                expect_regs={18: 0x55},
                expect_cycles=3,
            ),
            OpcodeTestCase(
                # Skip over two-word instruction.
                program_words=[sbis(0x1A, 0), *jmp(4), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x01},
                expect_regs={18: 0x55},
                expect_cycles=4,
            ),
            OpcodeTestCase(
                program_words=[sbis(0x1A, 0), ldi(18, 0xAA), ldi(18, 0x55)],
                steps=2,
                init_data={0x20 + 0x1A: 0x00},
                expect_regs={18: 0xAA},
                expect_cycles=2,
            ),
        ]

        for idx, case in enumerate(cases):
            with self.subTest(case=idx):
                result = run_opcode_test_case(case)
                self.assertTrue(result.ok, "\n".join(result.mismatches))

    def test_cli_accepts_state_and_expectations(self) -> None:
        cmd = [
            sys.executable,
            "opcode_tester.py",
            "--opcodes",
            "0xE005",
            "0x0F01",
            "--set-reg",
            "r17=0x03",
            "--expect-reg",
            "r16=0x08",
            "--expect-flag",
            "Z=0",
            "--expect-cycles",
            "2",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS=True", proc.stdout)

    def test_cli_fails_on_mismatch(self) -> None:
        cmd = [
            sys.executable,
            "opcode_tester.py",
            "--opcodes",
            "0xE005",
            "--expect-reg",
            "r16=0x99",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FAIL:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
