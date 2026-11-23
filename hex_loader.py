"""Intel HEX parsing helpers for AVR program images."""

from pathlib import Path


def _parse_hex_line(line: str) -> tuple[int, int, int, bytes, int]:
    line = line.strip()
    if not line:
        raise ValueError("Empty HEX line")
    if not line.startswith(":"):
        raise ValueError("HEX line must start with ':'")

    raw = bytes.fromhex(line[1:])
    if len(raw) < 5:
        raise ValueError("HEX line too short")

    count = raw[0]
    addr = (raw[1] << 8) | raw[2]
    rectype = raw[3]
    data = raw[4 : 4 + count]
    checksum = raw[4 + count]

    if len(data) != count:
        raise ValueError("HEX data length mismatch")

    # Sum of all bytes including checksum must be 0 modulo 256.
    if (sum(raw) & 0xFF) != 0:
        raise ValueError("HEX checksum mismatch")

    return count, addr, rectype, data, checksum


def load_hex_bytes(path: str) -> bytes:
    """Load Intel HEX file into a contiguous byte image.

    Supported record types:
    - 00: data
    - 01: end-of-file
    - 02: extended segment address (base = value * 16)
    - 03, 05: start address (ignored)
    - 04: extended linear address
    """

    p = Path(path)
    lines = p.read_text(encoding="ascii").splitlines()

    flash_bytes: dict[int, int] = {}
    base_addr = 0

    for i, line in enumerate(lines, start=1):
        if not line.strip():
            continue

        _, addr, rectype, data, _ = _parse_hex_line(line)

        if rectype == 0x00:
            base = base_addr + addr
            for off, b in enumerate(data):
                flash_bytes[base + off] = b
        elif rectype == 0x01:
            break
        elif rectype == 0x04:
            if len(data) != 2:
                raise ValueError(f"Line {i}: invalid extended linear address record")
            base_addr = ((data[0] << 8) | data[1]) << 16
        elif rectype == 0x02:
            if len(data) != 2:
                raise ValueError(f"Line {i}: invalid extended segment address record")
            base_addr = ((data[0] << 8) | data[1]) << 4
        elif rectype in (0x03, 0x05):
            continue
        else:
            raise ValueError(f"Line {i}: unsupported record type 0x{rectype:02X}")

    if not flash_bytes:
        return b""

    max_addr = max(flash_bytes)
    image = bytearray(max_addr + 1)
    for a, b in flash_bytes.items():
        image[a] = b
    return bytes(image)
