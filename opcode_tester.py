import argparse
import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from sim import ATmega2560Emulator


FLAG_BITS = {
    "C": ATmega2560Emulator.FLAG_C,
    "Z": ATmega2560Emulator.FLAG_Z,
    "N": ATmega2560Emulator.FLAG_N,
    "V": ATmega2560Emulator.FLAG_V,
    "S": ATmega2560Emulator.FLAG_S,
    "H": ATmega2560Emulator.FLAG_H,
    "T": ATmega2560Emulator.FLAG_T,
    "I": ATmega2560Emulator.FLAG_I,
}


@dataclass
class OpcodeTestCase:
    program_words: List[int]
    steps: int | None = None
    init_regs: Dict[int, int] = field(default_factory=dict)
    init_flags: Dict[str, int] = field(default_factory=dict)
    init_data: Dict[int, int] = field(default_factory=dict)
    init_pc: int | None = None
    init_sp: int | None = None
    expect_regs: Dict[int, int] = field(default_factory=dict)
    expect_flags: Dict[str, int] = field(default_factory=dict)
    expect_data: Dict[int, int] = field(default_factory=dict)
    expect_pc: int | None = None
    expect_sp: int | None = None
    expect_cycles: int | None = None
    expect_desc: str | None = None


@dataclass
class OpcodeTestResult:
    ok: bool
    mismatches: List[str]
    final_pc: int
    final_sp: int
    final_sreg: int
    final_cycles: int
    final_regs: List[int]
    last_description: str


def parse_number(token: str) -> int:
    return int(token.strip(), 0)


def _parse_assignment(token: str) -> tuple[str, str]:
    if "=" not in token:
        raise ValueError(f"Invalid assignment '{token}'. Expected KEY=VALUE.")
    key, value = token.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise ValueError(f"Invalid assignment '{token}'. Expected KEY=VALUE.")
    return key, value


def parse_opcode_words(tokens: Iterable[str]) -> List[int]:
    words: List[int] = []
    for token in tokens:
        for piece in token.split(","):
            piece = piece.strip()
            if not piece:
                continue
            words.append(parse_number(piece) & 0xFFFF)
    if not words:
        raise ValueError("At least one opcode word is required.")
    return words


def parse_reg_map(tokens: Iterable[str]) -> Dict[int, int]:
    reg_map: Dict[int, int] = {}
    for token in tokens:
        reg_name, value_text = _parse_assignment(token)
        if not reg_name.lower().startswith("r"):
            raise ValueError(f"Invalid register '{reg_name}'. Use r0..r31.")
        idx = parse_number(reg_name[1:])
        if idx < 0 or idx > 31:
            raise ValueError(f"Invalid register index {idx}. Must be 0..31.")
        reg_map[idx] = parse_number(value_text) & 0xFF
    return reg_map


def parse_flag_map(tokens: Iterable[str]) -> Dict[str, int]:
    flag_map: Dict[str, int] = {}
    for token in tokens:
        name, value_text = _parse_assignment(token)
        name = name.upper()
        if name not in FLAG_BITS:
            known = ", ".join(sorted(FLAG_BITS.keys()))
            raise ValueError(f"Unknown flag '{name}'. Valid: {known}")
        val = parse_number(value_text)
        if val not in (0, 1):
            raise ValueError(f"Invalid flag value {val} for {name}. Use 0 or 1.")
        flag_map[name] = val
    return flag_map


def parse_data_map(tokens: Iterable[str]) -> Dict[int, int]:
    data_map: Dict[int, int] = {}
    for token in tokens:
        addr_text, value_text = _parse_assignment(token)
        addr = parse_number(addr_text) & 0xFFFF
        data_map[addr] = parse_number(value_text) & 0xFF
    return data_map


def _apply_flags(emu: ATmega2560Emulator, flags: Dict[str, int]) -> None:
    for name, val in flags.items():
        bit = FLAG_BITS[name]
        if val:
            emu.sreg |= 1 << bit
        else:
            emu.sreg &= ~(1 << bit)


def run_opcode_test_case(case: OpcodeTestCase, verbose: bool = False) -> OpcodeTestResult:
    emu = ATmega2560Emulator()
    emu.load_program_words(case.program_words)

    for idx, val in case.init_regs.items():
        emu.reg[idx] = val & 0xFF

    _apply_flags(emu, case.init_flags)

    for addr, val in case.init_data.items():
        emu.data[addr & 0xFFFF] = val & 0xFF

    if case.init_pc is not None:
        emu.pc = case.init_pc & 0x3FFFFF
    if case.init_sp is not None:
        emu.sp = case.init_sp & 0xFFFF

    steps = len(case.program_words) if case.steps is None else case.steps
    last_description = ""
    for i in range(steps):
        if emu.halted:
            break
        result = emu.step()
        last_description = result.description
        if verbose:
            print(
                f"step={i:04d} pc=0x{result.pc_before:04X}->0x{emu.pc:04X} "
                f"op=0x{result.opcode:04X} dcyc={result.cycles} "
                f"cycles={emu.cycles} sreg=0b{emu.sreg:08b} {result.description}"
            )

    mismatches: List[str] = []

    for idx, expected in case.expect_regs.items():
        actual = emu.reg[idx]
        if actual != (expected & 0xFF):
            mismatches.append(
                f"reg r{idx}: expected 0x{expected & 0xFF:02X}, got 0x{actual:02X}"
            )

    for name, expected in case.expect_flags.items():
        bit = FLAG_BITS[name]
        actual = (emu.sreg >> bit) & 1
        if actual != expected:
            mismatches.append(f"flag {name}: expected {expected}, got {actual}")

    for addr, expected in case.expect_data.items():
        actual = emu.data[addr & 0xFFFF]
        if actual != (expected & 0xFF):
            mismatches.append(
                f"data[0x{addr & 0xFFFF:04X}]: expected 0x{expected & 0xFF:02X}, got 0x{actual:02X}"
            )

    if case.expect_pc is not None and emu.pc != (case.expect_pc & 0x3FFFFF):
        mismatches.append(f"pc: expected 0x{case.expect_pc & 0x3FFFFF:04X}, got 0x{emu.pc:04X}")

    if case.expect_sp is not None and emu.sp != (case.expect_sp & 0xFFFF):
        mismatches.append(f"sp: expected 0x{case.expect_sp & 0xFFFF:04X}, got 0x{emu.sp:04X}")

    if case.expect_cycles is not None and emu.cycles != case.expect_cycles:
        mismatches.append(f"cycles: expected {case.expect_cycles}, got {emu.cycles}")

    if case.expect_desc is not None and last_description != case.expect_desc:
        mismatches.append(
            f"desc: expected '{case.expect_desc}', got '{last_description}'"
        )

    return OpcodeTestResult(
        ok=(len(mismatches) == 0),
        mismatches=mismatches,
        final_pc=emu.pc,
        final_sp=emu.sp,
        final_sreg=emu.sreg,
        final_cycles=emu.cycles,
        final_regs=emu.reg[:],
        last_description=last_description,
    )


def _format_summary(result: OpcodeTestResult) -> str:
    reg_text = " ".join(f"r{i}:{result.final_regs[i]:02X}" for i in range(32))
    body = {
        "ok": result.ok,
        "mismatches": result.mismatches,
        "pc": result.final_pc,
        "sp": result.final_sp,
        "sreg": result.final_sreg,
        "cycles": result.final_cycles,
        "regs": result.final_regs,
        "last_description": result.last_description,
    }
    return (
        f"PASS={result.ok}\n"
        f"pc=0x{result.final_pc:04X} sp=0x{result.final_sp:04X} "
        f"sreg=0b{result.final_sreg:08b} cycles={result.final_cycles} "
        f"last_desc=\"{result.last_description}\"\n"
        f"regs: {reg_text}\n"
        f"json: {json.dumps(body, sort_keys=True)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run raw AVR opcode words with custom initial CPU state and assert expected state."
        )
    )
    parser.add_argument(
        "--opcodes",
        nargs="+",
        required=True,
        help="Hex/decimal opcode words (e.g. --opcodes 0xE005 0x0F01 or comma-separated).",
    )
    parser.add_argument("--steps", type=int, default=None, help="Instruction steps to execute.")

    parser.add_argument("--set-reg", action="append", default=[], help="Set register: rN=VAL")
    parser.add_argument("--set-flag", action="append", default=[], help="Set flag: C=0|1")
    parser.add_argument("--set-data", action="append", default=[], help="Set data memory: ADDR=VAL")
    parser.add_argument("--set-pc", type=parse_number, default=None, help="Initial PC (word address)")
    parser.add_argument("--set-sp", type=parse_number, default=None, help="Initial SP")

    parser.add_argument("--expect-reg", action="append", default=[], help="Expected register: rN=VAL")
    parser.add_argument("--expect-flag", action="append", default=[], help="Expected flag: C=0|1")
    parser.add_argument("--expect-data", action="append", default=[], help="Expected data memory: ADDR=VAL")
    parser.add_argument("--expect-pc", type=parse_number, default=None, help="Expected final PC")
    parser.add_argument("--expect-sp", type=parse_number, default=None, help="Expected final SP")
    parser.add_argument("--expect-cycles", type=int, default=None, help="Expected final cycle count")
    parser.add_argument("--expect-desc", default=None, help="Expected last executed instruction description")

    parser.add_argument("-v", "--verbose", action="store_true", help="Per-step trace")
    args = parser.parse_args()

    case = OpcodeTestCase(
        program_words=parse_opcode_words(args.opcodes),
        steps=args.steps,
        init_regs=parse_reg_map(args.set_reg),
        init_flags=parse_flag_map(args.set_flag),
        init_data=parse_data_map(args.set_data),
        init_pc=args.set_pc,
        init_sp=args.set_sp,
        expect_regs=parse_reg_map(args.expect_reg),
        expect_flags=parse_flag_map(args.expect_flag),
        expect_data=parse_data_map(args.expect_data),
        expect_pc=args.expect_pc,
        expect_sp=args.expect_sp,
        expect_cycles=args.expect_cycles,
        expect_desc=args.expect_desc,
    )

    result = run_opcode_test_case(case, verbose=args.verbose)
    print(_format_summary(result))

    if not result.ok:
        for msg in result.mismatches:
            print(f"FAIL: {msg}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
