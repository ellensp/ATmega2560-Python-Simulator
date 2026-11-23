"""Run the hardware-comparison firmware and compare every value with a real ATmega2560.

examples/hwcheck/hwcheck.hex prints `name=value` lines on USART0. The expected
values in examples/hwcheck/atmega2560_hardware.txt were captured from an Arduino
Mega 2560 R3 running the same image. See examples/hwcheck/README.md.
"""

import unittest
from pathlib import Path

from sim import ATmega2560Emulator

HWCHECK_DIR = Path(__file__).resolve().parent.parent / "examples" / "hwcheck"


def _values(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        value = value.strip()
        if sep:
            out[name] = value
    return out


class TestHardwareComparison(unittest.TestCase):
    def test_simulator_matches_real_atmega2560(self) -> None:
        expected = _values((HWCHECK_DIR / "atmega2560_hardware.txt").read_text())
        self.assertEqual(len(expected), 199)

        emu = ATmega2560Emulator()
        emu.set_twi_devices([])  # nothing on the bus but the board's pull-ups
        emu.load_program_hex(str(HWCHECK_DIR / "hwcheck.hex"))
        for _ in range(6_000_000):
            emu.step()
            if emu.uart0.tx_log[-6:] == list(b"DONE\r\n"):
                break
        else:
            self.fail("firmware did not finish")

        got = _values(bytes(emu.uart0.tx_log).decode("latin-1"))
        for name, value in expected.items():
            with self.subTest(check=name):
                self.assertEqual(got.get(name), value)


if __name__ == "__main__":
    unittest.main()
