import unittest

from avr_encoding import cpi, ldi
from sim import ATmega2560Emulator


def enc_reg_reg(base: int, rd: int, rr: int) -> int:
    return base | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def op_add(rd: int, rr: int) -> int:
    return enc_reg_reg(0x0C00, rd, rr)


def op_sub(rd: int, rr: int) -> int:
    return enc_reg_reg(0x1800, rd, rr)


def op_and(rd: int, rr: int) -> int:
    return enc_reg_reg(0x2000, rd, rr)


def op_sbc(rd: int, rr: int) -> int:
    return enc_reg_reg(0x0800, rd, rr)


def op_adc(rd: int, rr: int) -> int:
    return enc_reg_reg(0x1C00, rd, rr)


def op_cpc(rd: int, rr: int) -> int:
    return enc_reg_reg(0x0400, rd, rr)


def op_cp(rd: int, rr: int) -> int:
    return enc_reg_reg(0x1400, rd, rr)


def op_sbci(rd: int, imm: int) -> int:
    return 0x4000 | ((imm & 0xF0) << 4) | (((rd - 16) & 0x0F) << 4) | (imm & 0x0F)


def op_lsr(rd: int) -> int:
    return 0x9406 | ((rd & 0x1F) << 4)


def op_asr(rd: int) -> int:
    return 0x9405 | ((rd & 0x1F) << 4)


def op_ror(rd: int) -> int:
    return 0x9407 | ((rd & 0x1F) << 4)


def op_rol(rd: int) -> int:
    # ROL is encoded as ADC Rd,Rd.
    return op_adc(rd, rd)


class TestAVRFlagBehavior(unittest.TestCase):
    FLAG_C = 0
    FLAG_Z = 1
    FLAG_N = 2
    FLAG_V = 3
    FLAG_S = 4
    FLAG_H = 5

    def run_program(self, program: list[int], steps: int | None = None) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words(program)
        count = len(program) if steps is None else steps
        for _ in range(count):
            emu.step()
        return emu

    def flag(self, emu: ATmega2560Emulator, bit: int) -> int:
        return (emu.sreg >> bit) & 1

    def test_add_overflow_flags(self) -> None:
        # 0x7F + 0x01 = 0x80: N=1, V=1, S=0, H=1, Z=0, C=0
        emu = self.run_program([
            ldi(16, 0x7F),
            ldi(17, 0x01),
            op_add(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x80)
        self.assertEqual(self.flag(emu, self.FLAG_N), 1)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_S), 0)
        self.assertEqual(self.flag(emu, self.FLAG_H), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_C), 0)

    def test_add_carry_zero_flags(self) -> None:
        # 0xFF + 0x01 = 0x00: Z=1, C=1, H=1, N=0, V=0, S=0
        emu = self.run_program([
            ldi(16, 0xFF),
            ldi(17, 0x01),
            op_add(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_H), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 0)
        self.assertEqual(self.flag(emu, self.FLAG_S), 0)

    def test_sub_overflow_flags(self) -> None:
        # 0x80 - 0x01 = 0x7F: V=1, N=0, S=1, H=1, Z=0, C=0
        emu = self.run_program([
            ldi(16, 0x80),
            ldi(17, 0x01),
            op_sub(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x7F)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)
        self.assertEqual(self.flag(emu, self.FLAG_S), 1)
        self.assertEqual(self.flag(emu, self.FLAG_H), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_C), 0)

    def test_and_sets_logic_flags(self) -> None:
        # 0xF0 & 0x0F = 0x00: Z=1, N=0, V=0, S=0
        emu = self.run_program([
            ldi(16, 0xF0),
            ldi(17, 0x0F),
            op_and(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 0)
        self.assertEqual(self.flag(emu, self.FLAG_S), 0)

    def test_cpi_does_not_modify_register(self) -> None:
        emu = self.run_program([
            ldi(16, 0x10),
            cpi(16, 0x10),
        ])
        self.assertEqual(emu.reg[16], 0x10)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)
        self.assertEqual(self.flag(emu, self.FLAG_C), 0)

    def test_sbc_preserves_z_chain_semantics(self) -> None:
        # Z is intentionally cleared before SBC producing zero result.
        # For SBC, Z <- old_Z & (result == 0), so Z must stay 0 here.
        emu = self.run_program([
            ldi(16, 0x01),
            ldi(17, 0x01),
            cpi(16, 0x00),  # clears Z
            op_sbc(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)

    def test_adc_consumes_carry_in(self) -> None:
        # Prime C=1 then verify ADC includes carry-in in both data and flags.
        emu = self.run_program([
            ldi(16, 0x00),
            ldi(17, 0x01),
            op_sub(16, 17),      # sets C=1
            ldi(16, 0x7F),
            ldi(17, 0x00),
            op_adc(16, 17),      # 0x7F + 0x00 + C(1) = 0x80
        ])
        self.assertEqual(emu.reg[16], 0x80)
        self.assertEqual(self.flag(emu, self.FLAG_C), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)

    def test_adc_carry_out_with_carry_in(self) -> None:
        # 0xFF + 0x00 + C(1) -> 0x00 with carry out.
        emu = self.run_program([
            ldi(16, 0x00),
            ldi(17, 0x01),
            op_sub(16, 17),      # sets C=1
            ldi(16, 0xFF),
            ldi(17, 0x00),
            op_adc(16, 17),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)

    def test_sbc_consumes_carry_as_borrow(self) -> None:
        # Prime C=1 and verify SBC subtracts one extra.
        emu = self.run_program([
            ldi(16, 0x00),
            ldi(17, 0x01),
            op_sub(16, 17),      # sets C=1
            ldi(16, 0x00),
            ldi(17, 0x00),
            op_sbc(16, 17),      # 0x00 - 0x00 - 1 = 0xFF
        ])
        self.assertEqual(emu.reg[16], 0xFF)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)

    def test_cpc_chain_two_byte_compare(self) -> None:
        # CP low byte equal keeps Z=1; CPC high byte mismatch must clear Z and set borrow.
        emu = self.run_program([
            ldi(20, 0x00),
            ldi(21, 0x01),
            ldi(22, 0x00),
            ldi(23, 0x02),
            op_cp(20, 22),
            op_cpc(21, 23),
        ])
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)

    def test_sbci_uses_carry_in(self) -> None:
        # Prime C=1 and ensure SBCI subtracts immediate plus borrow.
        emu = self.run_program([
            ldi(16, 0x00),
            ldi(17, 0x01),
            op_sub(16, 17),      # sets C=1
            ldi(16, 0x00),
            op_sbci(16, 0x00),   # 0x00 - 0x00 - 1 = 0xFF
        ])
        self.assertEqual(emu.reg[16], 0xFF)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)

    def test_lsr_flags(self) -> None:
        # 0x01 >> 1 -> 0x00, with C=1 and AVR-defined V=C for LSR.
        emu = self.run_program([
            ldi(16, 0x01),
            op_lsr(16),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_S), 1)

    def test_asr_sign_extend_and_flags(self) -> None:
        # Arithmetic shift keeps sign bit.
        emu = self.run_program([
            ldi(16, 0x81),
            op_asr(16),
        ])
        self.assertEqual(emu.reg[16], 0xC0)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 0)
        self.assertEqual(self.flag(emu, self.FLAG_S), 1)

    def test_ror_uses_carry_in(self) -> None:
        # Prime C=1 then rotate right through carry.
        emu = self.run_program([
            ldi(20, 0x00),
            ldi(21, 0x01),
            op_sub(20, 21),      # C=1
            ldi(16, 0x02),
            op_ror(16),
        ])
        self.assertEqual(emu.reg[16], 0x81)
        self.assertEqual(self.flag(emu, self.FLAG_C), 0)
        self.assertEqual(self.flag(emu, self.FLAG_N), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_S), 0)

    def test_ror_lsb_to_carry(self) -> None:
        # LSB shifts into C; with C-in=0 and input 0x01 result is 0x00.
        emu = self.run_program([
            ldi(16, 0x01),
            op_ror(16),
        ])
        self.assertEqual(emu.reg[16], 0x00)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 1)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)
        self.assertEqual(self.flag(emu, self.FLAG_V), 1)
        self.assertEqual(self.flag(emu, self.FLAG_S), 1)

    def test_rol_alias_behavior(self) -> None:
        # Prime C=1 then ROL (ADC Rd,Rd) should rotate left through carry.
        emu = self.run_program([
            ldi(20, 0x00),
            ldi(21, 0x01),
            op_sub(20, 21),      # C=1
            ldi(16, 0x80),
            op_rol(16),          # 0x80 << 1 plus C-in -> 0x01, C-out=1
        ])
        self.assertEqual(emu.reg[16], 0x01)
        self.assertEqual(self.flag(emu, self.FLAG_C), 1)
        self.assertEqual(self.flag(emu, self.FLAG_Z), 0)
        self.assertEqual(self.flag(emu, self.FLAG_N), 0)


if __name__ == "__main__":
    unittest.main()
