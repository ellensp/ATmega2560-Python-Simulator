"""ATmega2560 emulator — instruction fetch, decode, and disassembly mixin."""

from dataclasses import dataclass
from typing import List


@dataclass
class DisassemblyLine:
    pc: int
    words: int
    bytes_hex: str
    text: str
    is_pc: bool


class _DecodeMixin:
    # -----------------------------
    # Fetch helpers
    # -----------------------------

    def _instruction_words_at_pc(self, pc_word: int) -> int:
        if pc_word < 0 or pc_word >= len(self.program):
            return 1

        op = self.program[pc_word]

        # JMP/CALL (22-bit address) are two-word instructions.
        if (op & 0xFE0E) in (0x940C, 0x940E):
            return 2

        # LDS/STS direct-address forms are two-word instructions.
        if (op & 0xFE0F) in (0x9000, 0x9200):
            return 2

        return 1

    def _fetch_next_word(self) -> int:
        if self.pc < 0 or self.pc >= len(self.program):
            self.halted = True
            return 0x0000
        self._profile_record_flash_word_read(self.pc)
        word = self.program[self.pc]
        self.pc += 1
        return word

    @staticmethod
    def _decode_long_target(first_word: int, second_word: int) -> int:
        # JMP/CALL encode a 22-bit word address:
        # low 16 bits in second word, upper 6 bits in first word.
        k_hi = ((first_word >> 3) & 0x3E) | (first_word & 0x1)
        return ((k_hi << 16) | (second_word & 0xFFFF)) & 0x3FFFFF

    # -----------------------------
    # Decode helpers
    # -----------------------------

    @staticmethod
    def _decode_rd_rr(opcode: int) -> tuple[int, int]:
        # Format: xxxx xxrd dddd rrrr
        rd = (opcode >> 4) & 0x1F
        rr = (opcode & 0x0F) | ((opcode >> 5) & 0x10)
        return rd, rr

    @staticmethod
    def _decode_k8(opcode: int) -> int:
        # Format for LDI/ORI/ANDI/SUBI/CPI: KKKK dddd KKKK
        return ((opcode >> 4) & 0xF0) | (opcode & 0x0F)

    @staticmethod
    def _decode_rd_high(opcode: int) -> int:
        # dddd in instruction maps to R16..R31
        return 16 + ((opcode >> 4) & 0x0F)

    # -----------------------------
    # Disassembler
    # -----------------------------

    def _disassemble_one(self, pc_word: int) -> tuple[int, str]:
        if pc_word < 0 or pc_word >= len(self.program):
            return 1, "<out of range>"

        opcode = self.program[pc_word]
        next_word = self.program[pc_word + 1] if (pc_word + 1) < len(self.program) else 0

        if opcode == 0x0000:
            return 1, "NOP"
        if (opcode & 0xFC00) == 0x2C00:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"MOV r{rd}, r{rr}"
        if (opcode & 0xFF00) == 0x0100:
            d = (opcode >> 4) & 0x0F
            r = opcode & 0x0F
            rd = d * 2
            rr = r * 2
            return 1, f"MOVW r{rd}:r{rd + 1}, r{rr}:r{rr + 1}"
        if (opcode & 0xFC00) == 0x0C00:
            rd, rr = self._decode_rd_rr(opcode)
            if rd == rr:
                return 1, f"LSL r{rd}"
            return 1, f"ADD r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x1C00:
            rd, rr = self._decode_rd_rr(opcode)
            if rd == rr:
                return 1, f"ROL r{rd}"
            return 1, f"ADC r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x1800:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"SUB r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x0800:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"SBC r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x0400:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"CPC r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x2000:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"AND r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x2800:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"OR r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x2400:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"EOR r{rd}, r{rr}"
        if (opcode & 0xF000) == 0xE000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"LDI r{rd}, 0x{k:02X}"
        if (opcode & 0xF000) == 0x5000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"SUBI r{rd}, 0x{k:02X}"
        if (opcode & 0xF000) == 0x4000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"SBCI r{rd}, 0x{k:02X}"
        if (opcode & 0xF000) == 0x7000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"ANDI r{rd}, 0x{k:02X}"
        if (opcode & 0xF000) == 0x6000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"ORI r{rd}, 0x{k:02X}"
        if (opcode & 0xFF00) == 0x9600:
            d = (opcode >> 4) & 0x3
            k = ((opcode >> 2) & 0x30) | (opcode & 0x0F)
            rd = 24 + (d * 2)
            return 1, f"ADIW r{rd}:r{rd + 1}, {k}"
        if (opcode & 0xFF00) == 0x9700:
            d = (opcode >> 4) & 0x3
            k = ((opcode >> 2) & 0x30) | (opcode & 0x0F)
            rd = 24 + (d * 2)
            return 1, f"SBIW r{rd}:r{rd + 1}, {k}"
        if (opcode & 0xFE0F) == 0x9403:
            rd = (opcode >> 4) & 0x1F
            return 1, f"INC r{rd}"
        if (opcode & 0xFE0F) == 0x940A:
            rd = (opcode >> 4) & 0x1F
            return 1, f"DEC r{rd}"
        if (opcode & 0xFE0F) == 0x9406:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LSR r{rd}"
        if (opcode & 0xFE0F) == 0x9405:
            rd = (opcode >> 4) & 0x1F
            return 1, f"ASR r{rd}"
        if (opcode & 0xFE0F) == 0x9407:
            rd = (opcode >> 4) & 0x1F
            return 1, f"ROR r{rd}"
        if (opcode & 0xFE0F) == 0x9402:
            rd = (opcode >> 4) & 0x1F
            return 1, f"SWAP r{rd}"
        if (opcode & 0xFE0F) == 0x9400:
            rd = (opcode >> 4) & 0x1F
            return 1, f"COM r{rd}"
        if (opcode & 0xFE0F) == 0x9401:
            rd = (opcode >> 4) & 0x1F
            return 1, f"NEG r{rd}"
        if (opcode & 0xFC00) == 0x9C00:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"MUL r{rd}, r{rr}"
        if (opcode & 0xFF00) == 0x0200:
            d = 16 + ((opcode >> 4) & 0x0F)
            r = 16 + (opcode & 0x0F)
            return 1, f"MULS r{d}, r{r}"
        if (opcode & 0xFF88) == 0x0300:
            d = 16 + ((opcode >> 4) & 0x07)
            r = 16 + (opcode & 0x07)
            return 1, f"MULSU r{d}, r{r}"
        if (opcode & 0xFF88) == 0x0308:
            d = 16 + ((opcode >> 4) & 0x07)
            r = 16 + (opcode & 0x07)
            return 1, f"FMUL r{d}, r{r}"
        if (opcode & 0xFF88) == 0x0380:
            d = 16 + ((opcode >> 4) & 0x07)
            r = 16 + (opcode & 0x07)
            return 1, f"FMULS r{d}, r{r}"
        if (opcode & 0xFF88) == 0x0388:
            d = 16 + ((opcode >> 4) & 0x07)
            r = 16 + (opcode & 0x07)
            return 1, f"FMULSU r{d}, r{r}"
        if (opcode & 0xF000) == 0x3000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            return 1, f"CPI r{rd}, 0x{k:02X}"
        if (opcode & 0xFC00) == 0x1400:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"CP r{rd}, r{rr}"
        if (opcode & 0xFC00) == 0x1000:
            rd, rr = self._decode_rd_rr(opcode)
            return 1, f"CPSE r{rd}, r{rr}"
        if (opcode & 0xFE08) == 0xFC00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            return 1, f"SBRC r{rr}, {b}"
        if (opcode & 0xFE08) == 0xFE00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            return 1, f"SBRS r{rr}, {b}"
        if (opcode & 0xFF00) == 0x9900:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            return 1, f"SBIC {self._format_io_operand(a)}, {b}"
        if (opcode & 0xFF00) == 0x9B00:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            return 1, f"SBIS {self._format_io_operand(a)}, {b}"
        if (opcode & 0xFF00) == 0x9800:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            return 1, f"CBI {self._format_io_operand(a)}, {b}"
        if (opcode & 0xFF00) == 0x9A00:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            return 1, f"SBI {self._format_io_operand(a)}, {b}"
        if (opcode & 0xF800) == 0xB000:
            rd = (opcode >> 4) & 0x1F
            a = (opcode & 0x0F) | ((opcode >> 5) & 0x30)
            return 1, f"IN r{rd}, {self._format_io_operand(a)}"
        if (opcode & 0xF800) == 0xB800:
            rr = (opcode >> 4) & 0x1F
            a = (opcode & 0x0F) | ((opcode >> 5) & 0x30)
            return 1, f"OUT {self._format_io_operand(a)}, r{rr}"
        if (opcode & 0xFE0F) == 0x900C:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, X"
        if (opcode & 0xD200) == 0x8000:
            rd = (opcode >> 4) & 0x1F
            ptr_name = "Y" if (opcode & 0x0008) else "Z"
            q = ((opcode >> 8) & 0x20) | ((opcode >> 7) & 0x18) | (opcode & 0x7)
            return 1, f"LDD r{rd}, {ptr_name}+{q}"
        if (opcode & 0xFE0F) == 0x900D:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, X+"
        if (opcode & 0xFE0F) == 0x900E:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, -X"
        if (opcode & 0xFE0F) == 0x8008:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, Y"
        if (opcode & 0xFE0F) == 0x9009:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, Y+"
        if (opcode & 0xFE0F) == 0x900A:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, -Y"
        if (opcode & 0xFE0F) == 0x8000:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, Z"
        if (opcode & 0xFE0F) == 0x9001:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, Z+"
        if (opcode & 0xFE0F) == 0x9002:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LD r{rd}, -Z"
        if (opcode & 0xFE0F) == 0x920C:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST X, r{rr}"
        if (opcode & 0xFE0F) == 0x9204:
            rd = (opcode >> 4) & 0x1F
            return 1, f"XCH Z, r{rd}"
        if (opcode & 0xFE0F) == 0x9205:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LAS Z, r{rd}"
        if (opcode & 0xFE0F) == 0x9206:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LAC Z, r{rd}"
        if (opcode & 0xFE0F) == 0x9207:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LAT Z, r{rd}"
        if (opcode & 0xD200) == 0x8200:
            rr = (opcode >> 4) & 0x1F
            ptr_name = "Y" if (opcode & 0x0008) else "Z"
            q = ((opcode >> 8) & 0x20) | ((opcode >> 7) & 0x18) | (opcode & 0x7)
            return 1, f"STD {ptr_name}+{q}, r{rr}"
        if (opcode & 0xFE0F) == 0x920D:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST X+, r{rr}"
        if (opcode & 0xFE0F) == 0x920E:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST -X, r{rr}"
        if (opcode & 0xFE0F) == 0x8208:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST Y, r{rr}"
        if (opcode & 0xFE0F) == 0x9209:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST Y+, r{rr}"
        if (opcode & 0xFE0F) == 0x920A:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST -Y, r{rr}"
        if (opcode & 0xFE0F) == 0x8200:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST Z, r{rr}"
        if (opcode & 0xFE0F) == 0x9201:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST Z+, r{rr}"
        if (opcode & 0xFE0F) == 0x9202:
            rr = (opcode >> 4) & 0x1F
            return 1, f"ST -Z, r{rr}"
        if (opcode & 0xFE0F) == 0x9000:
            rd = (opcode >> 4) & 0x1F
            return 2, f"LDS r{rd}, 0x{next_word:04X}"
        if (opcode & 0xFE0F) == 0x9200:
            rr = (opcode >> 4) & 0x1F
            return 2, f"STS 0x{next_word:04X}, r{rr}"
        if opcode == 0x95C8:
            return 1, "LPM"
        if opcode == 0x95D8:
            return 1, "ELPM"
        if (opcode & 0xFE0F) == 0x9004:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LPM r{rd}, Z"
        if (opcode & 0xFE0F) == 0x9005:
            rd = (opcode >> 4) & 0x1F
            return 1, f"LPM r{rd}, Z+"
        if (opcode & 0xFE0F) == 0x9006:
            rd = (opcode >> 4) & 0x1F
            return 1, f"ELPM r{rd}, Z"
        if (opcode & 0xFE0F) == 0x9007:
            rd = (opcode >> 4) & 0x1F
            return 1, f"ELPM r{rd}, Z+"
        if opcode == 0x9409:
            return 1, "IJMP"
        if opcode == 0x9419:
            return 1, "EIJMP"
        if opcode == 0x9509:
            return 1, "ICALL"
        if opcode == 0x9519:
            return 1, "EICALL"
        if (opcode & 0xFE0F) == 0x920F:
            rr = (opcode >> 4) & 0x1F
            return 1, f"PUSH r{rr}"
        if (opcode & 0xFE0F) == 0x900F:
            rd = (opcode >> 4) & 0x1F
            return 1, f"POP r{rd}"
        if (opcode & 0xF000) == 0xC000:
            k = self._sign_extend(opcode & 0x0FFF, 12)
            target = (pc_word + 1 + k) & 0x3FFFFF
            return 1, f"RJMP 0x{target:05X}"
        if (opcode & 0xF000) == 0xD000:
            k = self._sign_extend(opcode & 0x0FFF, 12)
            target = (pc_word + 1 + k) & 0x3FFFFF
            return 1, f"RCALL 0x{target:05X}"
        if (opcode & 0xFE0E) == 0x940C:
            target = self._decode_long_target(opcode, next_word)
            return 2, f"JMP 0x{target:05X}"
        if (opcode & 0xFE0E) == 0x940E:
            target = self._decode_long_target(opcode, next_word)
            return 2, f"CALL 0x{target:05X}"
        if (opcode & 0xFE08) == 0xF800:
            rd = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            return 1, f"BLD r{rd}, {b}"
        if (opcode & 0xFE08) == 0xFA00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            return 1, f"BST r{rr}, {b}"
        if (opcode & 0xFC00) == 0xF000:
            s = opcode & 0x7
            k = self._sign_extend((opcode >> 3) & 0x7F, 7)
            target = (pc_word + 1 + k) & 0x3FFFFF
            brbs_alias = {
                self.FLAG_C: "BRCS",
                self.FLAG_Z: "BREQ",
                self.FLAG_N: "BRMI",
                self.FLAG_V: "BRVS",
                self.FLAG_S: "BRLT",
                self.FLAG_H: "BRHS",
                self.FLAG_T: "BRTS",
                self.FLAG_I: "BRIE",
            }
            mnemonic = brbs_alias.get(s, f"BRBS {s}")
            return 1, f"{mnemonic} 0x{target:05X}"
        if (opcode & 0xFC00) == 0xF400:
            s = opcode & 0x7
            k = self._sign_extend((opcode >> 3) & 0x7F, 7)
            target = (pc_word + 1 + k) & 0x3FFFFF
            brbc_alias = {
                self.FLAG_C: "BRCC",
                self.FLAG_Z: "BRNE",
                self.FLAG_N: "BRPL",
                self.FLAG_V: "BRVC",
                self.FLAG_S: "BRGE",
                self.FLAG_H: "BRHC",
                self.FLAG_T: "BRTC",
                self.FLAG_I: "BRID",
            }
            mnemonic = brbc_alias.get(s, f"BRBC {s}")
            return 1, f"{mnemonic} 0x{target:05X}"
        if opcode == 0x9588:
            return 1, "SLEEP"
        if opcode == 0x9598:
            return 1, "BREAK"
        if opcode == 0x95A8:
            return 1, "WDR"
        if opcode == 0x95E8:
            return 1, "SPM"
        if opcode == 0x95F8:
            return 1, "SPM Z+"
        if opcode == 0x9408:
            return 1, "SEC"
        if opcode == 0x9488:
            return 1, "CLC"
        if opcode == 0x9418:
            return 1, "SEZ"
        if opcode == 0x9498:
            return 1, "CLZ"
        if opcode == 0x9428:
            return 1, "SEN"
        if opcode == 0x94A8:
            return 1, "CLN"
        if opcode == 0x9438:
            return 1, "SEV"
        if opcode == 0x94B8:
            return 1, "CLV"
        if opcode == 0x9448:
            return 1, "SES"
        if opcode == 0x94C8:
            return 1, "CLS"
        if opcode == 0x9458:
            return 1, "SEH"
        if opcode == 0x94D8:
            return 1, "CLH"
        if opcode == 0x9468:
            return 1, "SET"
        if opcode == 0x94E8:
            return 1, "CLT"
        if opcode == 0x9478:
            return 1, "SEI"
        if opcode == 0x94F8:
            return 1, "CLI"
        if opcode == 0x9508:
            return 1, "RET"
        if opcode == 0x9518:
            return 1, "RETI"

        return self._instruction_words_at_pc(pc_word), f"OP 0x{opcode:04X}"

    def disassemble_window(
        self, center_pc: int | None = None, before: int = 20, after: int = 40
    ) -> List[DisassemblyLine]:
        if center_pc is None:
            center_pc = self.pc
        center_pc = max(0, min(center_pc, max(len(self.program) - 1, 0)))

        start = max(0, center_pc - max(before, 0))
        end_limit = min(len(self.program), center_pc + max(after, 0) + 1)

        lines: List[DisassemblyLine] = []
        i = start
        while i < end_limit:
            words, text = self._disassemble_one(i)
            words = max(1, words)
            chunk = self.program[i : min(i + words, len(self.program))]
            byte_parts: List[str] = []
            for word in chunk:
                byte_parts.append(f"{word & 0xFF:02X}")
                byte_parts.append(f"{(word >> 8) & 0xFF:02X}")
            lines.append(
                DisassemblyLine(
                    pc=i,
                    words=words,
                    bytes_hex=" ".join(byte_parts),
                    text=text,
                    is_pc=(i == self.pc),
                )
            )
            i += words
        return lines
