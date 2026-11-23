"""Logic probe and LCD protocol decoders for the AVR emulator.

PinProbe records every level change of chosen GPIO pins with the CPU cycle it
happened on, like a logic analyzer connected to those pins. It hooks the
emulator's data-space writes, so OUT, STS, ST, SBI and CBI to a watched port's
PORTx, DDRx or PINx register are all seen.

Timestamps are the cycle count at the start of the instruction that changed
the pin, so they are exact to within the length of that instruction (1-2
cycles for the port instructions, 62.5-125 ns at 16 MHz).

ShiftRegisterDecoder turns three probed pins (serial data, shift clock, latch)
into the parallel outputs of a 74HC595-style shift register.

HD44780Decoder models an HD44780 character LCD driven in 4-bit mode from those
outputs. It executes the instructions it receives, keeps DDRAM so the screen
can be rendered, and checks every bus and execution timing against the
HD44780U datasheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

F_CPU_DEFAULT = 16_000_000

Level = Optional[int]  # 0, 1, or None when the pin is an input (not driven)


def parse_pin(name: str) -> Tuple[str, int]:
    """'PC0' / 'C0' -> ('C', 0)."""
    text = name.strip().upper()
    if text.startswith("P") and len(text) == 3:
        text = text[1:]
    if len(text) != 2 or not text[0].isalpha() or not text[1].isdigit():
        raise ValueError(f"Bad pin name '{name}', expected like 'PC0'")
    bit = int(text[1])
    if bit > 7:
        raise ValueError(f"Bad pin bit in '{name}'")
    return text[0], bit


def pin_label(port: str, bit: int) -> str:
    return f"P{port}{bit}"


@dataclass
class Edge:
    cycle: int
    pin: str
    level: Level


class PinProbe:
    """Records level changes on watched pins of an emulator."""

    def __init__(self, emu, pins: List[str], f_cpu: int = F_CPU_DEFAULT, max_edges: int = 2_000_000) -> None:
        self.emu = emu
        self.f_cpu = f_cpu
        self.max_edges = max_edges
        self.edges: List[Edge] = []
        self.dropped = 0
        self.listeners: List[Callable[[Edge], None]] = []
        self._watch: Dict[str, List[int]] = {}  # port letter -> bits
        self._addr_to_port: Dict[int, str] = {}
        self._last: Dict[str, Level] = {}
        for name in pins:
            self.add_pin(name)
        self._orig_data_write = emu._data_write
        emu._data_write = self._data_write_hook  # instance attribute shadows the mixin method

    def detach(self) -> None:
        self.emu.__dict__.pop("_data_write", None)

    def add_pin(self, name: str) -> str:
        port, bit = parse_pin(name)
        if port not in self.emu.GPIO_PORTS:
            raise ValueError(f"Port {port} doesn't exist")
        label = pin_label(port, bit)
        bits = self._watch.setdefault(port, [])
        if bit not in bits:
            bits.append(bit)
        for addr in self.emu.GPIO_PORTS[port]:
            self._addr_to_port[addr] = port
        self._last[label] = self._pin_level(port, bit)
        return label

    def _pin_level(self, port: str, bit: int) -> Level:
        _, ddr_addr, port_addr = self.emu.GPIO_PORTS[port]
        if not (self.emu.data[ddr_addr] >> bit) & 1:
            return None
        return (self.emu.data[port_addr] >> bit) & 1

    def add_all_pins(self) -> None:
        """Probe every pin of every GPIO port."""
        for port in self.emu.GPIO_PORTS:
            for bit in range(8):
                self.add_pin(f"P{port}{bit}")

    def level(self, name: str) -> Level:
        port, bit = parse_pin(name)
        return self._pin_level(port, bit)

    def activity(self, since_cycle: int = 0, until_cycle: Optional[int] = None) -> Dict[str, int]:
        """Number of edges on each pin in a cycle window, busiest first."""
        counts: Dict[str, int] = {}
        for e in self.edges:
            if e.cycle < since_cycle or (until_cycle is not None and e.cycle > until_cycle):
                continue
            counts[e.pin] = counts.get(e.pin, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def _data_write_hook(self, addr: int, value: int) -> None:
        self._orig_data_write(addr, value)
        port = self._addr_to_port.get(addr & 0xFFFF)
        if port is None:
            return
        cycle = self.emu.cycles
        for bit in self._watch[port]:
            label = pin_label(port, bit)
            lvl = self._pin_level(port, bit)
            if lvl != self._last[label]:
                self._last[label] = lvl
                edge = Edge(cycle, label, lvl)
                if len(self.edges) < self.max_edges:
                    self.edges.append(edge)
                else:
                    self.dropped += 1
                for listener in self.listeners:
                    listener(edge)

    def ns(self, cycles: int) -> float:
        return cycles * 1e9 / self.f_cpu

    def clear(self) -> None:
        self.edges.clear()
        self.dropped = 0


@dataclass
class MinTracker:
    """Smallest value seen for one timing parameter, with a datasheet limit."""

    name: str
    limit_ns: float
    unit_note: str = ""
    count: int = 0
    min_ns: Optional[float] = None
    min_at_ns: Optional[float] = None
    violations: int = 0
    first_violation_at_ns: Optional[float] = None

    def add(self, value_ns: float, at_ns: float) -> None:
        self.count += 1
        if self.min_ns is None or value_ns < self.min_ns:
            self.min_ns = value_ns
            self.min_at_ns = at_ns
        if value_ns < self.limit_ns:
            self.violations += 1
            if self.first_violation_at_ns is None:
                self.first_violation_at_ns = at_ns

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "limit_ns": self.limit_ns,
            "count": self.count,
            "min_ns": None if self.min_ns is None else round(self.min_ns, 1),
            "min_at_us": None if self.min_at_ns is None else round(self.min_at_ns / 1000, 3),
            "violations": self.violations,
            "first_violation_at_us": None if self.first_violation_at_ns is None else round(self.first_violation_at_ns / 1000, 3),
            "note": self.unit_note,
        }


class ShiftRegisterDecoder:
    """74HC595-style serial-in, parallel-out register driven from three pins.

    Bits shift in on the rising edge of the shift clock, MSB first (the first
    bit ends up on Q7), and are copied to the outputs on the rising edge of the
    latch (strobe) pin.
    """

    # 74HC595 at Vcc 4.5 V, 25 C (NXP 74HC595 datasheet)
    LIMITS_NS = {
        "ser_setup": 25.0,     # SER stable before SRCLK rises
        "ser_hold": 3.0,       # SER stable after SRCLK rises
        "srclk_high": 20.0,
        "srclk_low": 20.0,
        "srclk_to_rclk": 19.0, # last SRCLK rise before RCLK rise
        "rclk_high": 20.0,
    }

    def __init__(self, probe: PinProbe, data: str, clk: str, latch: str) -> None:
        self.probe = probe
        self.data_pin = pin_label(*parse_pin(data))
        self.clk_pin = pin_label(*parse_pin(clk))
        self.latch_pin = pin_label(*parse_pin(latch))
        self.levels: Dict[str, Level] = {p: probe.level(p) for p in (self.data_pin, self.clk_pin, self.latch_pin)}
        self.changed_at: Dict[str, int] = {p: 0 for p in self.levels}
        self.shift = 0
        self.output = 0
        self.output_listeners: List[Callable[[int, int], None]] = []
        self.latches = 0
        self._last_clk_rise: Optional[int] = None
        self.timing = {k: MinTracker(k, v) for k, v in self.LIMITS_NS.items()}
        probe.listeners.append(self._on_edge)

    def _on_edge(self, edge: Edge) -> None:
        pin = edge.pin
        if pin not in self.levels:
            return
        prev = self.levels[pin]
        t = edge.cycle
        ns = self.probe.ns
        if pin == self.data_pin and self._last_clk_rise is not None:
            self.timing["ser_hold"].add(ns(t - self._last_clk_rise), ns(t))
        if pin == self.clk_pin:
            if prev == 0 and edge.level == 1:
                self.timing["srclk_low"].add(ns(t - self.changed_at[pin]), ns(t))
                self.timing["ser_setup"].add(ns(t - self.changed_at[self.data_pin]), ns(t))
                bit = 1 if self.levels[self.data_pin] == 1 else 0
                self.shift = ((self.shift << 1) | bit) & 0xFF
                self._last_clk_rise = t
            elif prev == 1 and edge.level == 0:
                self.timing["srclk_high"].add(ns(t - self.changed_at[pin]), ns(t))
        if pin == self.latch_pin:
            if prev == 0 and edge.level == 1:
                if self._last_clk_rise is not None:
                    self.timing["srclk_to_rclk"].add(ns(t - self._last_clk_rise), ns(t))
                self.latches += 1
                if self.shift != self.output:
                    self.output = self.shift
                    for listener in self.output_listeners:
                        listener(t, self.output)
            elif prev == 1 and edge.level == 0:
                self.timing["rclk_high"].add(ns(t - self.changed_at[pin]), ns(t))
        self.levels[pin] = edge.level
        self.changed_at[pin] = t

    def report(self) -> dict:
        return {
            "latches": self.latches,
            "output": f"0x{self.output:02X}",
            "timing": [m.as_dict() for m in self.timing.values()],
        }


class HD44780Decoder:
    """HD44780 in 4-bit mode on a parallel byte (e.g. shift register outputs).

    The byte bit numbers of each LCD signal are given in `bits`. Instructions
    and data are executed as the LCD would, starting from the power-on reset
    state (8-bit interface, 1 line, display off). Every timing the HD44780U
    datasheet specifies for a write is checked:

    - Bus timing (Vcc 4.5-5.5 V): RS setup before E rises (tAS), E high
      width (PWEH), E cycle time (tcycE), data setup before E falls (tDSW),
      RS and data hold after E falls (tAH, tH).
    - Execution time: an E pulse while the previous instruction is still
      executing (37 us, 1.52 ms for clear and home at fosc 270 kHz).
    - Initialization: time from power-on to the first instruction (> 40 ms)
      and the 4.1 ms / 100 us waits of initialization by instruction.

    The older HD44780 (not U) needs longer bus times (tAS 140 ns, PWEH 450 ns,
    tDSW 195 ns, tcycE 1000 ns). They are checked as the 'legacy_*' entries.
    """

    LIMITS_NS = {
        "tAS": 40.0,
        "PWEH": 230.0,
        "tcycE": 500.0,
        "tDSW": 80.0,
        "tAH": 10.0,
        "tH": 10.0,
        "legacy_tAS": 140.0,
        "legacy_PWEH": 450.0,
        "legacy_tcycE": 1000.0,
        "legacy_tDSW": 195.0,
    }
    EXEC_NS = 37_000.0
    EXEC_LONG_NS = 1_520_000.0
    POWER_ON_WAIT_NS = 40_000_000.0
    INIT_WAIT1_NS = 4_100_000.0
    INIT_WAIT2_NS = 100_000.0

    def __init__(
        self,
        probe: PinProbe,
        source: ShiftRegisterDecoder,
        bits: Dict[str, int],
        cols: int = 20,
        rows: int = 4,
        power_pin: Optional[str] = None,
        power_active: int = 0,
        max_log: int = 4000,
    ) -> None:
        self.probe = probe
        self.bits = bits
        self.cols = cols
        self.rows = rows
        self.max_log = max_log
        self.power_pin = pin_label(*parse_pin(power_pin)) if power_pin else None
        self.power_active = power_active
        self.timing = {k: MinTracker(k, v) for k, v in self.LIMITS_NS.items()}
        self.exec_early = MinTracker("exec_wait", 0.0, "E fall before the previous instruction finished; min_ns is the shortfall as a negative number")
        self.log: List[dict] = []
        self.log_dropped = 0
        self.pulses_unpowered = 0
        self.powered_at: Optional[int] = None
        self.power_events: List[dict] = []
        self._byte = source.output
        self._changed: Dict[str, int] = {k: 0 for k in ("rs", "e", "data")}
        self._last_e_rise: Optional[int] = None
        self._last_e_fall: Optional[int] = None
        self._first_instr_at: Optional[int] = None
        self._init_8bit_times: List[int] = []
        self._reset_lcd()
        if self.power_pin is None:
            self.powered = True
            self.powered_at = 0
        else:
            self.powered = probe.level(self.power_pin) == power_active
            if self.powered:
                self.powered_at = probe.emu.cycles
            probe.listeners.append(self._on_power_edge)
        source.output_listeners.append(self._on_output)

    # ----- LCD state -----

    def _reset_lcd(self) -> None:
        self.eight_bit = True
        self.two_line = False
        self.display_on = False
        self.cursor_on = False
        self.blink_on = False
        self.increment = True
        self.shift_display = False
        self.addr = 0
        self.addr_cgram = False
        self.ddram = bytearray(b" " * 0x80)
        self.cgram = bytearray(64)
        self._nibble_hi: Optional[int] = None
        self.busy_until = 0
        self.instructions = 0
        self.data_writes = 0

    def _on_power_edge(self, edge: Edge) -> None:
        if edge.pin != self.power_pin:
            return
        on = edge.level == self.power_active
        self.power_events.append({"at_us": round(self.probe.ns(edge.cycle) / 1000, 3), "level": edge.level, "powered": on})
        if on and not self.powered:
            self.powered = True
            self.powered_at = edge.cycle
            self._reset_lcd()
            self._first_instr_at = None
            self._init_8bit_times = []
        elif not on and self.powered:
            self.powered = False

    def _bit(self, byte: int, name: str) -> int:
        return (byte >> self.bits[name]) & 1

    def _nibble(self, byte: int) -> int:
        return (
            (self._bit(byte, "d7") << 3)
            | (self._bit(byte, "d6") << 2)
            | (self._bit(byte, "d5") << 1)
            | self._bit(byte, "d4")
        )

    def _on_output(self, t: int, byte: int) -> None:
        prev = self._byte
        self._byte = byte
        ns = self.probe.ns
        rs_changed = self._bit(prev, "rs") != self._bit(byte, "rs")
        e_prev, e_now = self._bit(prev, "e"), self._bit(byte, "e")
        data_changed = self._nibble(prev) != self._nibble(byte)
        # Hold times: RS/data change after E fell
        if self._last_e_fall is not None:
            if rs_changed:
                self.timing["tAH"].add(ns(t - self._last_e_fall), ns(t))
            if data_changed:
                self.timing["tH"].add(ns(t - self._last_e_fall), ns(t))
        if rs_changed:
            self._changed["rs"] = t
        if data_changed:
            self._changed["data"] = t
        if e_prev == 0 and e_now == 1:
            setup = ns(t - self._changed["rs"])
            self.timing["tAS"].add(setup, ns(t))
            self.timing["legacy_tAS"].add(setup, ns(t))
            if self._last_e_rise is not None:
                cyc = ns(t - self._last_e_rise)
                self.timing["tcycE"].add(cyc, ns(t))
                self.timing["legacy_tcycE"].add(cyc, ns(t))
            self._last_e_rise = t
            self._changed["e"] = t
        elif e_prev == 1 and e_now == 0:
            width = ns(t - self._changed["e"])
            self.timing["PWEH"].add(width, ns(t))
            self.timing["legacy_PWEH"].add(width, ns(t))
            dsw = ns(t - self._changed["data"])
            self.timing["tDSW"].add(dsw, ns(t))
            self.timing["legacy_tDSW"].add(dsw, ns(t))
            self._last_e_fall = t
            self._changed["e"] = t
            self._latch(t, self._bit(byte, "rs"), self._nibble(byte))

    def _log(self, t: int, entry: dict) -> None:
        if len(self.log) < self.max_log:
            entry["at_us"] = round(self.probe.ns(t) / 1000, 3)
            self.log.append(entry)
        else:
            self.log_dropped += 1

    def _latch(self, t: int, rs: int, nibble: int) -> None:
        if not self.powered:
            self.pulses_unpowered += 1
            return
        ns_t = self.probe.ns(t)
        busy_ns = self.probe.ns(self.busy_until)
        if ns_t < busy_ns:
            self.exec_early.add(ns_t - busy_ns, ns_t)
        if self.eight_bit:
            # 8-bit interface: each E pulse is a whole instruction, low nibble 0
            self._execute(t, rs, nibble << 4, eight_bit_write=True)
            return
        if self._nibble_hi is None:
            self._nibble_hi = nibble
            return
        value = (self._nibble_hi << 4) | nibble
        self._nibble_hi = None
        self._execute(t, rs, value)

    def _execute(self, t: int, rs: int, value: int, eight_bit_write: bool = False) -> None:
        exec_ns = self.EXEC_NS
        if self._first_instr_at is None and self.powered_at is not None:
            self._first_instr_at = t
        if rs:
            self.data_writes += 1
            if self.addr_cgram:
                self.cgram[self.addr & 0x3F] = value
                self.addr = (self.addr + (1 if self.increment else -1)) & 0x3F
            else:
                self.ddram[self.addr & 0x7F] = value
                self._step_ddram()
            exec_ns += 4_000.0
            self._log(t, {"rs": 1, "value": f"0x{value:02X}", "desc": f"data {self._char(value)!r}"})
        else:
            self.instructions += 1
            desc = self._instruction(value)
            if value in (0x01, 0x02, 0x03):
                exec_ns = self.EXEC_LONG_NS
            if eight_bit_write and (value & 0xF0) == 0x30:
                self._init_8bit_times.append(t)
            self._log(t, {"rs": 0, "value": f"0x{value:02X}", "desc": desc + (" (8-bit write)" if eight_bit_write else "")})
        self.busy_until = t + int(exec_ns * self.probe.f_cpu / 1e9)

    def _step_ddram(self) -> None:
        if self.increment:
            self.addr += 1
        else:
            self.addr -= 1
        if self.two_line:
            if self.addr == 0x28:
                self.addr = 0x40
            elif self.addr == 0x68:
                self.addr = 0x00
            elif self.addr == 0x3F:
                self.addr = 0x27
            elif self.addr < 0:
                self.addr = 0x67
        else:
            self.addr %= 0x50
        self.addr &= 0x7F

    def _instruction(self, v: int) -> str:
        if v & 0x80:
            self.addr = v & 0x7F
            self.addr_cgram = False
            return f"set DDRAM 0x{self.addr:02X}"
        if v & 0x40:
            self.addr = v & 0x3F
            self.addr_cgram = True
            return f"set CGRAM 0x{self.addr:02X}"
        if v & 0x20:
            self.eight_bit = bool(v & 0x10)
            self.two_line = bool(v & 0x08)
            self._nibble_hi = None
            return f"function set {'8' if self.eight_bit else '4'}-bit, {'2' if self.two_line else '1'}-line, 5x{'10' if v & 0x04 else '8'}"
        if v & 0x10:
            return f"{'display' if v & 0x08 else 'cursor'} shift {'right' if v & 0x04 else 'left'}"
        if v & 0x08:
            self.display_on = bool(v & 0x04)
            self.cursor_on = bool(v & 0x02)
            self.blink_on = bool(v & 0x01)
            return f"display {'on' if self.display_on else 'off'}, cursor {'on' if self.cursor_on else 'off'}, blink {'on' if self.blink_on else 'off'}"
        if v & 0x04:
            self.increment = bool(v & 0x02)
            self.shift_display = bool(v & 0x01)
            return f"entry mode {'inc' if self.increment else 'dec'}{', shift' if self.shift_display else ''}"
        if v & 0x02:
            self.addr = 0
            self.addr_cgram = False
            return "return home"
        if v & 0x01:
            self.ddram[:] = b" " * 0x80
            self.addr = 0
            self.addr_cgram = False
            self.increment = True
            return "clear display"
        return "no-op (0x00)"

    @staticmethod
    def _char(v: int) -> str:
        if v < 8:
            return f"\\{v}"
        if 0x20 <= v < 0x7F:
            return chr(v)
        return f"\\x{v:02X}"

    # ----- results -----

    def screen(self) -> List[str]:
        """Text of each row as the panel would show it."""
        if not self.powered:
            return ["(LCD not powered)"]
        if not self.display_on:
            return ["(display off)"]
        offsets = [0x00, 0x40, 0x14, 0x54]
        lines = []
        for row in range(self.rows):
            if not self.two_line and row in (1, 3):
                lines.append("")  # second line driver unused in 1-line mode
                continue
            base = offsets[row]
            text = "".join(
                (chr(c) if 0x20 <= c < 0x7F else ("█" if c == 0xFF else ("#" if c < 8 else "?")))
                for c in self.ddram[base: base + self.cols]
            )
            lines.append(text)
        return lines

    def init_report(self) -> dict:
        ns = self.probe.ns
        out: dict = {}
        if self.powered_at is not None and self._first_instr_at is not None:
            wait = ns(self._first_instr_at - self.powered_at)
            out["power_on_to_first_instruction_ms"] = round(wait / 1e6, 3)
            out["power_on_wait_ok"] = wait >= self.POWER_ON_WAIT_NS
        times = self._init_8bit_times
        gaps = [ns(b - a) for a, b in zip(times, times[1:])]
        out["init_8bit_function_sets"] = len(times)
        if gaps:
            out["init_gaps_us"] = [round(g / 1000, 2) for g in gaps]
            if len(gaps) >= 1:
                out["init_wait1_ok"] = gaps[0] >= self.INIT_WAIT1_NS
            if len(gaps) >= 2:
                out["init_wait2_ok"] = gaps[1] >= self.INIT_WAIT2_NS
        return out

    def report(self) -> dict:
        return {
            "powered": self.powered,
            "power_events": self.power_events[:20],
            "pulses_while_unpowered": self.pulses_unpowered,
            "interface": "8-bit" if self.eight_bit else "4-bit",
            "lines": 2 if self.two_line else 1,
            "display_on": self.display_on,
            "instructions": self.instructions,
            "data_writes": self.data_writes,
            "init": self.init_report(),
            "timing": [m.as_dict() for m in self.timing.values()] + [self.exec_early.as_dict()],
            "screen": self.screen(),
        }


# Board presets: pins and shift register bit layout of known 3-wire LCD panels.
LCD_PRESETS = {
    # MakerBot MightyBoard Rev G/H (Replicator 2 / 2X) interface board.
    # Pins from MightyBoardFirmware boards/mighty_two/Configuration.hh,
    # bit layout from LiquidCrystalSerial.cc (RS 0b0010, E 0b1000, D7-D4 in the high nibble).
    "mightyboard_revg": {
        "data": "PC0",
        "clk": "PC1",
        "latch": "PC3",
        "power": "PA7",
        "power_active": 0,
        "bits": {"rs": 1, "e": 3, "d4": 4, "d5": 5, "d6": 6, "d7": 7},
        "cols": 20,
        "rows": 4,
        # Levels the interface board puts on MCU inputs: PC4 is pulled high when
        # the board is connected (MakerBot interface::isConnected()), and the
        # five buttons (J3-J6, G2) are pulled up and read low when pressed.
        "inputs": {"PC4": 1, "PJ3": 1, "PJ4": 1, "PJ5": 1, "PJ6": 1, "PG2": 1},
    },
}


class LcdProbe:
    """Probe + shift register + HD44780 decoders wired up for one panel."""

    def __init__(self, emu, preset: str | dict = "mightyboard_revg", f_cpu: int = F_CPU_DEFAULT, extra_pins: Optional[List[str]] = None) -> None:
        cfg = dict(LCD_PRESETS[preset]) if isinstance(preset, str) else dict(preset)
        self.config = cfg
        pins = [cfg["data"], cfg["clk"], cfg["latch"]]
        if cfg.get("power"):
            pins.append(cfg["power"])
        pins += list(extra_pins or [])
        for name, level in cfg.get("inputs", {}).items():
            port, bit = parse_pin(name)
            emu.set_pin_level(port, bit, level)
        self.probe = PinProbe(emu, pins, f_cpu=f_cpu)
        self.sr = ShiftRegisterDecoder(self.probe, cfg["data"], cfg["clk"], cfg["latch"])
        self.lcd = HD44780Decoder(
            self.probe,
            self.sr,
            cfg["bits"],
            cols=cfg.get("cols", 20),
            rows=cfg.get("rows", 4),
            power_pin=cfg.get("power"),
            power_active=cfg.get("power_active", 0),
        )

    def report(self) -> dict:
        return {"config": self.config, "shift_register": self.sr.report(), "lcd": self.lcd.report()}
