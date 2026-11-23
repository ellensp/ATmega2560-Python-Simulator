"""Logic-probe agent for the AVR emulator.

Runs firmware in the emulator with a logic probe on chosen pins and an LCD
protocol decoder, controlled either from the command line (one run, one JSON
report) or over TCP with one JSON request per line, so an agent can drive it
step by step.

Command line:

    .venv-pypy310/bin/python probe_agent.py run FIRMWARE.hex --mcu atmega1280 --ms 3000

Server:

    .venv-pypy310/bin/python probe_agent.py serve --port 9100

    then send lines like:
    {"cmd": "load", "hex": "fw.hex", "mcu": "atmega1280", "lcd": "mightyboard_revg"}
    {"cmd": "run", "ms": 500}
    {"cmd": "lcd"}
    {"cmd": "edges", "pins": ["PC3"], "since_us": 0, "limit": 100}

Every reply is one JSON line: {"ok": true, ...} or {"ok": false, "error": "..."}.

Commands:
    load      hex, mcu (atmega2560|atmega1280), lcd (preset name or config object), pins (extra pins to probe),
              all_pins (probe every pin of every port), f_cpu
    reset     reset the MCU (the probe and decoders keep their state)
    run       ms | us | cycles; optional until_text (stop once the LCD shows it), until_instructions
    status    time, cycles, PC, halt reason
    lcd       LCD report: screen, timing checks, init sequence, shift register timing
    log       decoded LCD instructions/data: since_us, limit
    edges     raw pin edges: pins, since_us, until_us, limit
    activity  edge count per pin: since_us, until_us (all_pins shows which port bits really toggle)
    set_pin   pin, level (0/1, or null to release): drive an input pin from outside
    uart      bytes sent on a UART since the last uart call: index
    presets   list LCD presets
    quit      close the connection
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path

from sim import EMULATORS, create_emulator
from sim_probe import LCD_PRESETS, F_CPU_DEFAULT, LcdProbe, PinProbe, parse_pin, pin_label


class ProbeSession:
    def __init__(self) -> None:
        self.emu = None
        self.lcd: LcdProbe | None = None
        self.probe: PinProbe | None = None
        self.f_cpu = F_CPU_DEFAULT
        self.hex_path: str | None = None
        self.mcu: str | None = None
        self._uart_read = [0, 0, 0, 0]

    # ----- helpers -----

    def _need_emu(self) -> None:
        if self.emu is None:
            raise RuntimeError("no firmware loaded, send 'load' first")

    def _us(self, cycles: int) -> float:
        return round(cycles * 1e6 / self.f_cpu, 3)

    def _status(self) -> dict:
        emu = self.emu
        return {
            "mcu": self.mcu,
            "hex": self.hex_path,
            "cycles": emu.cycles,
            "time_ms": round(emu.cycles * 1e3 / self.f_cpu, 3),
            "pc": f"0x{emu.pc * 2:05X}",
            "halted": emu.halted,
            "halt_reason": emu.halt_reason,
        }

    # ----- commands -----

    def cmd_presets(self, req: dict) -> dict:
        return {"presets": LCD_PRESETS}

    def cmd_load(self, req: dict) -> dict:
        hex_path = req["hex"]
        self.mcu = req.get("mcu", "atmega2560")
        self.f_cpu = int(req.get("f_cpu", F_CPU_DEFAULT))
        self.emu = create_emulator(self.mcu)
        self.emu.load_program_hex(hex_path)
        self.hex_path = str(Path(hex_path).resolve())
        self._uart_read = [0, 0, 0, 0]
        lcd_cfg = req.get("lcd", "mightyboard_revg")
        pins = req.get("pins", [])
        if lcd_cfg:
            self.lcd = LcdProbe(self.emu, lcd_cfg, f_cpu=self.f_cpu, extra_pins=pins)
            self.probe = self.lcd.probe
        else:
            self.lcd = None
            self.probe = PinProbe(self.emu, pins, f_cpu=self.f_cpu)
        if req.get("all_pins"):
            self.probe.add_all_pins()
        return {"status": self._status(), "probed_pins": sorted(self.probe._last)}

    def cmd_reset(self, req: dict) -> dict:
        self._need_emu()
        self.emu.reset()
        return {"status": self._status()}

    def cmd_run(self, req: dict) -> dict:
        self._need_emu()
        emu = self.emu
        if "cycles" in req:
            span = int(req["cycles"])
        elif "us" in req:
            span = int(float(req["us"]) * self.f_cpu / 1e6)
        else:
            span = int(float(req.get("ms", 100)) * self.f_cpu / 1e3)
        target = emu.cycles + span
        until_text = req.get("until_text")
        until_instr = req.get("until_instructions")
        stop = "time"
        started = time.time()
        step = emu.step
        while emu.cycles < target:
            if emu.halted:
                stop = "halted"
                break
            for _ in range(5000):
                step()
                if emu.halted:
                    break
            if self.lcd is not None:
                if until_text and any(until_text in line for line in self.lcd.lcd.screen()):
                    stop = "until_text"
                    break
                if until_instr is not None and self.lcd.lcd.instructions >= int(until_instr):
                    stop = "until_instructions"
                    break
        return {"stop": stop, "wall_s": round(time.time() - started, 2), "status": self._status()}

    def cmd_status(self, req: dict) -> dict:
        self._need_emu()
        return {"status": self._status()}

    def cmd_lcd(self, req: dict) -> dict:
        self._need_emu()
        if self.lcd is None:
            raise RuntimeError("no LCD decoder configured")
        rep = self.lcd.report()
        rep["status"] = self._status()
        return rep

    def cmd_log(self, req: dict) -> dict:
        if self.lcd is None:
            raise RuntimeError("no LCD decoder configured")
        since = float(req.get("since_us", 0))
        limit = int(req.get("limit", 200))
        items = [e for e in self.lcd.lcd.log if e["at_us"] >= since][:limit]
        return {"log": items, "dropped": self.lcd.lcd.log_dropped}

    def cmd_edges(self, req: dict) -> dict:
        self._need_emu()
        pins = {pin_label(*parse_pin(p)) for p in req.get("pins", [])} or None
        since = float(req.get("since_us", 0))
        until = float(req.get("until_us", 1e18))
        limit = int(req.get("limit", 500))
        out = []
        for e in self.probe.edges:
            us = self._us(e.cycle)
            if us < since or us > until or (pins and e.pin not in pins):
                continue
            out.append({"at_us": us, "cycle": e.cycle, "pin": e.pin, "level": e.level})
            if len(out) >= limit:
                break
        return {"edges": out, "total_edges": len(self.probe.edges), "dropped": self.probe.dropped}

    def cmd_activity(self, req: dict) -> dict:
        self._need_emu()
        since = int(float(req.get("since_us", 0)) * self.f_cpu / 1e6)
        until = req.get("until_us")
        until = None if until is None else int(float(until) * self.f_cpu / 1e6)
        return {"activity": self.probe.activity(since, until)}

    def cmd_set_pin(self, req: dict) -> dict:
        self._need_emu()
        port, bit = parse_pin(req["pin"])
        level = req.get("level")
        if level is None:
            self.emu.release_pin_level(port, bit)
        else:
            self.emu.set_pin_level(port, bit, int(level))
        return {}

    def cmd_uart(self, req: dict) -> dict:
        self._need_emu()
        idx = int(req.get("index", 0))
        log = self.emu.uarts[idx].tx_log
        data = bytes(log[self._uart_read[idx]:])
        self._uart_read[idx] = len(log)
        return {"text": data.decode("latin-1")}

    def handle(self, req: dict) -> dict:
        name = req.get("cmd")
        fn = getattr(self, f"cmd_{name}", None)
        if fn is None:
            return {"ok": False, "error": f"unknown cmd '{name}'"}
        try:
            out = fn(req)
        except Exception as exc:  # report errors to the client instead of dropping the connection
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        out["ok"] = True
        return out


def serve(host: str, port: int) -> None:
    session = ProbeSession()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    print(f"probe agent listening on {host}:{port}", flush=True)
    while True:
        conn, _ = srv.accept()
        with conn, conn.makefile("rw", encoding="utf-8", newline="\n") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as exc:
                    reply = {"ok": False, "error": f"bad JSON: {exc}"}
                else:
                    if req.get("cmd") == "quit":
                        f.write(json.dumps({"ok": True}) + "\n")
                        f.flush()
                        break
                    reply = session.handle(req)
                f.write(json.dumps(reply) + "\n")
                f.flush()


def run_once(args: argparse.Namespace) -> int:
    session = ProbeSession()
    load = {"hex": args.hex_file, "mcu": args.mcu, "lcd": args.lcd, "pins": args.pin, "all_pins": args.all_pins}
    out = session.handle({"cmd": "load", **load})
    if not out["ok"]:
        print(json.dumps(out), file=sys.stderr)
        return 1
    run = {"cmd": "run", "ms": args.ms}
    if args.until_text:
        run["until_text"] = args.until_text
    result = session.handle(run)
    report = session.handle({"cmd": "lcd"}) if args.lcd else {}
    report["run"] = result
    report["uart0"] = session.handle({"cmd": "uart", "index": 0}).get("text", "")[-2000:]
    if args.all_pins:
        report["activity"] = session.handle({"cmd": "activity"})["activity"]
        if session.lcd is not None and session.lcd.lcd.powered_at is not None:
            # Edges from LCD power-on to the end of the run
            start_us = session.lcd.lcd.powered_at * 1e6 / session.f_cpu
            report["activity_after_lcd_power"] = session.handle({"cmd": "activity", "since_us": start_us})["activity"]
    if args.log:
        report["log"] = session.handle({"cmd": "log", "limit": args.log})["log"]
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    if args.json or not args.out:
        print(text)
    if args.lcd and session.lcd is not None:
        print("\n".join(f"|{line}|" for line in session.lcd.lcd.screen()), file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Logic probe / LCD decoder agent for the AVR emulator")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_run = sub.add_parser("run", help="run firmware once and print a JSON report")
    p_run.add_argument("hex_file")
    p_run.add_argument("--mcu", default="atmega2560", choices=sorted(EMULATORS))
    p_run.add_argument("--ms", type=float, default=2000, help="simulated time to run")
    p_run.add_argument("--lcd", default="mightyboard_revg", help="LCD preset ('' for none)")
    p_run.add_argument("--pin", action="append", default=[], help="extra pin to probe, e.g. PC4 (repeatable)")
    p_run.add_argument("--all-pins", action="store_true", help="probe every pin of every port")
    p_run.add_argument("--until-text", default=None, help="stop once the LCD shows this text")
    p_run.add_argument("--log", type=int, default=0, help="include the first N decoded LCD instructions")
    p_run.add_argument("--out", default=None, help="write the JSON report to this file")
    p_run.add_argument("--json", action="store_true", help="also print the report when --out is given")

    p_srv = sub.add_parser("serve", help="serve JSON-lines requests over TCP")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=9100)

    args = parser.parse_args()
    if args.mode == "serve":
        serve(args.host, args.port)
        return 0
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
