import tempfile
import unittest
from pathlib import Path

from hex_loader import load_hex_bytes
from sim import ATmega2560Emulator


class TestHexLoader(unittest.TestCase):
    def write_hex(self, text: str) -> str:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".hex", encoding="ascii")
        tmp.write(text)
        tmp.flush()
        tmp.close()
        return tmp.name

    def test_load_data_and_eof(self) -> None:
        # Data bytes: 0x05 0xE0 0x13 0xE0 -> words [0xE005, 0xE013]
        hex_text = ":0400000005E013E024\n:00000001FF\n"
        path = self.write_hex(hex_text)

        data = load_hex_bytes(path)
        self.assertEqual(data, bytes([0x05, 0xE0, 0x13, 0xE0]))

        emu = ATmega2560Emulator()
        emu.load_program_hex(path)
        self.assertEqual(emu.program, [0xE005, 0xE013])

        Path(path).unlink(missing_ok=True)

    def test_extended_linear_address_record(self) -> None:
        # Put two bytes at absolute byte address 0x00010000.
        hex_text = (
            ":020000040001F9\n"
            ":0200000005E019\n"
            ":00000001FF\n"
        )
        path = self.write_hex(hex_text)
        data = load_hex_bytes(path)

        self.assertEqual(len(data), 0x10002)
        self.assertEqual(data[0x10000], 0x05)
        self.assertEqual(data[0x10001], 0xE0)

        Path(path).unlink(missing_ok=True)

    def test_extended_segment_address_record(self) -> None:
        # Segment 0x1000 -> base 0x10000; start segment (03) and start linear (05) records are ignored.
        hex_text = (
            ":020000021000EC\n"
            ":0200000005E019\n"
            ":0400000300000000F9\n"
            ":0400000500000000F7\n"
            ":00000001FF\n"
        )
        path = self.write_hex(hex_text)
        data = load_hex_bytes(path)

        self.assertEqual(len(data), 0x10002)
        self.assertEqual(data[0x10000], 0x05)
        self.assertEqual(data[0x10001], 0xE0)

        Path(path).unlink(missing_ok=True)

    def test_bad_checksum_raises(self) -> None:
        # Last byte intentionally wrong checksum (should not be 0x00).
        bad_hex = ":0400000005E013E000\n:00000001FF\n"
        path = self.write_hex(bad_hex)

        with self.assertRaises(ValueError):
            load_hex_bytes(path)

        Path(path).unlink(missing_ok=True)

    def test_unsupported_record_type_raises(self) -> None:
        # Record type 06 is not an Intel HEX record type.
        bad_hex = ":020000061234B0\n:00000001FF\n"
        path = self.write_hex(bad_hex)

        with self.assertRaises(ValueError):
            load_hex_bytes(path)

        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
