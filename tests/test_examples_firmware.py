import subprocess
import unittest
from pathlib import Path

from sim import ATmega2560Emulator


class TestExampleFirmwareOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parent.parent
        cls.tmp_dir = Path("/tmp/atmega2560_sim_example_tests")
        cls.tmp_dir.mkdir(parents=True, exist_ok=True)

        cls.fib_hex = cls._compile_example("fibonacci_uart")
        cls.primes_hex = cls._compile_example("primes_uart")
        cls.counter_hex = cls._compile_example("counter_uart")
        cls.uart0_rx_isr_hex = cls._compile_example("uart0_rx_isr")

    @classmethod
    def _compile_example(cls, name: str) -> Path:
        src = cls.repo_root / "examples" / name / f"{name}.c"
        elf = cls.tmp_dir / f"{name}_test.elf"
        hex_path = cls.tmp_dir / f"{name}_test.hex"

        subprocess.run(
            [
                "avr-gcc",
                "-mmcu=atmega2560",
                "-DF_CPU=1000UL",
                "-DBAUD=62UL",  # UBRR = 0: the shortest frame time
                "-Os",
                "-Wall",
                "-Wextra",
                "-std=c11",
                "-o",
                str(elf),
                str(src),
            ],
            check=True,
            cwd=cls.repo_root,
        )
        subprocess.run(
            [
                "avr-objcopy",
                "-O",
                "ihex",
                "-R",
                ".eeprom",
                str(elf),
                str(hex_path),
            ],
            check=True,
            cwd=cls.repo_root,
        )
        return hex_path

    def _run_until_lines(self, hex_path: Path, min_lines: int, max_steps: int) -> list[str]:
        emu = ATmega2560Emulator()
        emu.load_program_hex(str(hex_path))

        for _ in range(max_steps):
            emu.step()
            if emu.uart0.tx_log.count(0x0A) >= min_lines:
                break

        text = bytes(emu.uart0.tx_log).decode("ascii", "replace").replace("\r", "")
        return [line for line in text.split("\n") if line != ""]

    def test_fibonacci_sequence_prefix(self) -> None:
        lines = self._run_until_lines(self.fib_hex, min_lines=8, max_steps=1_500_000)
        self.assertGreaterEqual(len(lines), 8)
        self.assertEqual(lines[0], "Fibonacci:")
        self.assertEqual(lines[1:8], ["0", "1", "1", "2", "3", "5", "8"])

    def test_primes_sequence_prefix(self) -> None:
        lines = self._run_until_lines(self.primes_hex, min_lines=8, max_steps=6_000_000)
        self.assertGreaterEqual(len(lines), 8)
        self.assertEqual(lines[0], "Primes:")
        self.assertEqual(lines[1:8], ["2", "3", "5", "7", "11", "13", "17"])

    def test_counter_increments(self) -> None:
        lines = self._run_until_lines(self.counter_hex, min_lines=4, max_steps=900_000)
        self.assertGreaterEqual(len(lines), 4)
        self.assertEqual(lines[0:4], ["count=0", "count=1", "count=2", "count=3"])

    def test_uart0_rx_isr_reports_received_bytes(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_hex(str(self.uart0_rx_isr_hex))

        for _ in range(200_000):
            emu.step()
            if b"uart0 rx isr ready\r\n" in bytes(emu.uart0.tx_log):
                break

        for ch in b"A\n":
            emu.inject_uart0_rx_byte(ch)

        for _ in range(200_000):
            emu.step()
            tx = bytes(emu.uart0.tx_log)
            if b"received {A}\r\n" in tx and b"received {\\n}\r\n" in tx:
                break

        text = bytes(emu.uart0.tx_log).decode("ascii", "replace")
        self.assertIn("uart0 rx isr ready\r\n", text)
        self.assertIn("received {A}\r\n", text)
        self.assertIn("received {\\n}\r\n", text)


if __name__ == "__main__":
    unittest.main()
