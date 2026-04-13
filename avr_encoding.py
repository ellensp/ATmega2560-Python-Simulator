"""Instruction encoding helpers for AVR 16-bit core opcodes.

These helpers make smoke tests and fixture programs easier to read.
All functions return one 16-bit word unless explicitly documented.
"""


def ldi(rd: int, imm8: int) -> int:
    if not (16 <= rd <= 31):
        raise ValueError("LDI destination must be r16..r31")
    imm8 &= 0xFF
    return 0xE000 | ((imm8 & 0xF0) << 4) | ((rd - 16) << 4) | (imm8 & 0x0F)


def mov(rd: int, rr: int) -> int:
    return 0x2C00 | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def add(rd: int, rr: int) -> int:
    return 0x0C00 | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def cpi(rd: int, imm8: int) -> int:
    if not (16 <= rd <= 31):
        raise ValueError("CPI destination must be r16..r31")
    imm8 &= 0xFF
    return 0x3000 | ((imm8 & 0xF0) << 4) | ((rd - 16) << 4) | (imm8 & 0x0F)


def cpse(rd: int, rr: int) -> int:
    return 0x1000 | ((rd & 0x1F) << 4) | (rr & 0x0F) | ((rr & 0x10) << 5)


def rjmp(k: int) -> int:
    return 0xC000 | (k & 0x0FFF)


def rcall(k: int) -> int:
    return 0xD000 | (k & 0x0FFF)


def brbs(sreg_bit: int, k: int) -> int:
    return 0xF000 | ((k & 0x7F) << 3) | (sreg_bit & 0x7)


def brbc(sreg_bit: int, k: int) -> int:
    return 0xF400 | ((k & 0x7F) << 3) | (sreg_bit & 0x7)


def push(rr: int) -> int:
    return 0x920F | ((rr & 0x1F) << 4)


def pop(rd: int) -> int:
    return 0x900F | ((rd & 0x1F) << 4)


def in_(rd: int, io_addr: int) -> int:
    io_addr &= 0x3F
    return 0xB000 | ((io_addr & 0x30) << 5) | ((rd & 0x1F) << 4) | (io_addr & 0x0F)


def out(io_addr: int, rr: int) -> int:
    io_addr &= 0x3F
    return 0xB800 | ((io_addr & 0x30) << 5) | ((rr & 0x1F) << 4) | (io_addr & 0x0F)


def lds(rd: int, addr16: int) -> tuple[int, int]:
    return (0x9000 | ((rd & 0x1F) << 4), addr16 & 0xFFFF)


def sts(rr: int, addr16: int) -> tuple[int, int]:
    return (0x9200 | ((rr & 0x1F) << 4), addr16 & 0xFFFF)


def jmp(addr_word: int) -> tuple[int, int]:
    addr_word &= 0x3FFFFF
    high = (addr_word >> 16) & 0x3F
    first = 0x940C | ((high & 0x1) << 0) | ((high & 0x3E) << 3)
    second = addr_word & 0xFFFF
    return first, second


def call(addr_word: int) -> tuple[int, int]:
    addr_word &= 0x3FFFFF
    high = (addr_word >> 16) & 0x3F
    first = 0x940E | ((high & 0x1) << 0) | ((high & 0x3E) << 3)
    second = addr_word & 0xFFFF
    return first, second
