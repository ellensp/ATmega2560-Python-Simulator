import argparse
import socket
import sys
import time

from sim import ATmega2560Emulator


def _format_regs(regs: list[int]) -> str:
    return " ".join(f"r{i}:{regs[i]:02X}" for i in range(32))


def _bits8(value: int) -> str:
    return format(value & 0xFF, "08b")


def _io_level(ddr: int, port: int, pin: int) -> int:
    # Effective pin level: output pins from PORT latch, input pins from PIN register.
    return ((port & ddr) | (pin & (~ddr & 0xFF))) & 0xFF


def _inject_uart_payload(emu: ATmega2560Emulator, uart_index: int, payload: bytes) -> None:
    uart = emu.get_uart(uart_index)
    emu.data[uart.DATA_UCSRB] |= 1 << uart.RXEN_BIT
    for byte in payload:
        emu.inject_uart_rx_byte(uart_index, byte)


def _enable_uart0_simple_console_mode(emu: ATmega2560Emulator) -> None:
    """Enable a lightweight UART0 TX path for direct console streaming.

    This bypasses queued per-step UART0 transmission timing and marks bytes as
    transmitted immediately when firmware writes UDR0 with TX enabled.

    This keeps peripheral and interrupt behavior intact so firmware execution
    remains faithful while UART0 TX output is surfaced with low overhead.
    """
    uart0 = emu.get_uart(0)

    def _write_udr_fast(self, value: int, data: bytearray) -> None:  # type: ignore[no-redef]
        data[self.DATA_UDR] = value & 0xFF
        if ((data[self.DATA_UCSRB] >> self.TXEN_BIT) & 1) == 0:
            return
        self.tx_log.append(value & 0xFF)
        data[self.DATA_UCSRA] |= 1 << self.UDRE_BIT
        data[self.DATA_UCSRA] |= 1 << self.TXC_BIT

    def _advance_fast(self, _cycles: int, _data: bytearray) -> None:  # type: ignore[no-redef]
        return

    def _is_transmitting_fast(self) -> bool:  # type: ignore[no-redef]
        return False

    uart0._pending_tx.clear()  # type: ignore[attr-defined]
    emu.data[uart0.DATA_UCSRA] |= 1 << uart0.UDRE_BIT
    uart0.write_udr = _write_udr_fast.__get__(uart0, type(uart0))
    uart0.advance = _advance_fast.__get__(uart0, type(uart0))
    uart0.is_transmitting = _is_transmitting_fast.__get__(uart0, type(uart0))

    # Intentionally avoid disabling other peripherals/interrupts here.


def _stream_uart_console_bytes(payload: bytes) -> None:
    if not payload:
        return
    try:
        sys.stdout.buffer.write(payload)
        sys.stdout.flush()
    except BrokenPipeError:
        raise SystemExit(0)


def _parse_adc_args(parser: argparse.ArgumentParser, adc_values: list[str]) -> list[tuple[int, int]]:
    """Parse and validate --adc command-line arguments.
    
    Args:
        parser: ArgumentParser for error reporting
        adc_values: List of ADC specs from --adc arguments (repeatable)
        
    Returns:
        List of (channel, value) tuples
    """
    adc_pairs: list[tuple[int, int]] = []
    for spec in adc_values:
        for item in spec.split(","):
            text = item.strip()
            if not text:
                continue
            if "=" not in text:
                parser.error(f"Invalid --adc value '{text}'. Use CHANNEL=VALUE.")
            channel_text, value_text = text.split("=", 1)
            channel_text = channel_text.strip().lower()
            if channel_text.startswith("adc"):
                channel_text = channel_text[3:]
            try:
                channel = int(channel_text, 10)
            except ValueError:
                parser.error(f"Invalid ADC channel in '{text}'. Use 0..15 or ADC0..ADC15.")
            try:
                value = int(value_text.strip(), 10)
            except ValueError:
                parser.error(f"Invalid ADC value in '{text}'. Use 0..1023.")
            if not 0 <= channel <= 15:
                parser.error(f"ADC channel out of range in '{text}'. Use 0..15.")
            if not 0 <= value <= 1023:
                parser.error(f"ADC value out of range in '{text}'. Use 0..1023.")
            adc_pairs.append((channel, value))
    return adc_pairs


class UARTTCPBridge:
    def __init__(
        self,
        host: str,
        port: int,
        uart_index: int = 0,
        baud: int = 9600,
        data_bits: int = 8,
        parity: str = "N",
        stop_bits: int = 1,
    ) -> None:
        self.host = host
        self.port = port
        self.uart_index = uart_index
        self.baud = baud
        self.data_bits = data_bits
        self.parity = parity.upper()
        self.stop_bits = stop_bits

        self._server: socket.socket | None = None
        self._client: socket.socket | None = None
        self._last_tx_index = 0
        self._next_accept_time = 0.0
        self._accept_retry_delay = 0.02

    def start(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(1)
        server.setblocking(False)
        self._server = server

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None
        if self._server is not None:
            try:
                self._server.close()
            finally:
                self._server = None

    def _accept_client(self) -> None:
        if self._server is None or self._client is not None:
            return

        now = time.monotonic()
        if now < self._next_accept_time:
            return

        try:
            client, _ = self._server.accept()
        except BlockingIOError:
            # Avoid busy-looping accept() when no client is waiting.
            self._next_accept_time = now + self._accept_retry_delay
            return
        client.setblocking(False)
        self._client = client
        self._next_accept_time = 0.0

    def _disconnect_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def pump(self, emu: ATmega2560Emulator) -> None:
        self._accept_client()
        if self._client is None:
            return

        try:
            rx = self._client.recv(4096)
            if rx:
                for byte in rx:
                    emu.inject_uart_rx_byte(self.uart_index, byte)
            else:
                self._disconnect_client()
                return
        except BlockingIOError:
            pass
        except OSError:
            self._disconnect_client()
            return

        uart = emu.get_uart(self.uart_index)
        if self._last_tx_index < len(uart.tx_log):
            payload = bytes(uart.tx_log[self._last_tx_index :])
            try:
                self._client.sendall(payload)
            except OSError:
                self._disconnect_client()
                return
            self._last_tx_index = len(uart.tx_log)

    def description(self) -> str:
        return (
            f"uart{self.uart_index}@{self.host}:{self.port} "
            f"{self.baud},{self.data_bits}{self.parity}{self.stop_bits}"
        )


def _render_visual(emu: ATmega2560Emulator, step: int, dcyc: int, desc: str, opcode: int) -> None:
    def io_to_data_addr(io_addr: int) -> int:
        # Low I/O (0x00..0x3F) maps to data space 0x20..0x5F.
        return io_addr + 0x20 if 0 <= io_addr <= 0x3F else io_addr

    ports = {
        "A": (io_to_data_addr(0x00), io_to_data_addr(0x01), io_to_data_addr(0x02)),
        "B": (io_to_data_addr(0x03), io_to_data_addr(0x04), io_to_data_addr(0x05)),
        "C": (io_to_data_addr(0x06), io_to_data_addr(0x07), io_to_data_addr(0x08)),
        "D": (io_to_data_addr(0x09), io_to_data_addr(0x0A), io_to_data_addr(0x0B)),
        "E": (io_to_data_addr(0x0C), io_to_data_addr(0x0D), io_to_data_addr(0x0E)),
        "F": (io_to_data_addr(0x0F), io_to_data_addr(0x10), io_to_data_addr(0x11)),
        "G": (io_to_data_addr(0x12), io_to_data_addr(0x13), io_to_data_addr(0x14)),
        # Extended I/O space ports on ATmega2560 (already data-space addresses).
        "H": (0x100, 0x101, 0x102),
        "J": (0x103, 0x104, 0x105),
        "K": (0x106, 0x107, 0x108),
        "L": (0x109, 0x10A, 0x10B),
    }

    pb_pin, pb_ddr, pb_port = ports["B"]
    ddrb = emu.data[pb_ddr]
    portb = emu.data[pb_port]
    pinb = emu.data[pb_pin]
    levb = _io_level(ddrb, portb, pinb)

    pb7_is_output = ((ddrb >> 7) & 1) == 1
    pb7_level = (levb >> 7) & 1
    if pb7_is_output:
        led = "ON" if pb7_level else "OFF"
    else:
        led = "INPUT"

    lines = []
    lines.append(f"step={step:06d} op=0x{opcode:04X} dcyc={dcyc} cycles={emu.cycles} instr=\"{desc}\"")
    lines.append(f"pc=0x{emu.pc:04X} sp=0x{emu.sp:04X} sreg=0b{emu.sreg:08b} LED(PB7)={led}")

    for name, (pin_addr, ddr_addr, port_addr) in ports.items():
        pin = emu.data[pin_addr]
        ddr = emu.data[ddr_addr]
        port = emu.data[port_addr]
        lev = _io_level(ddr, port, pin)
        lines.append(
            f"P{name} PIN={_bits8(pin)} DDR={_bits8(ddr)} PORT={_bits8(port)} LVL={_bits8(lev)}"
        )

    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AVR Intel HEX image in the ATmega2560 emulator.")
    parser.add_argument("hex_file", help="Path to Intel HEX file")
    parser.add_argument("--steps", type=int, default=1000, help="Maximum instruction steps")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-instruction trace")
    parser.add_argument("--visual", action="store_true", help="Print visual I/O port state view while running")
    parser.add_argument("--visual-every", type=int, default=1, help="Render visual view every N instructions")
    parser.add_argument("--visual-clear", action="store_true", help="Clear screen before each visual frame")
    parser.add_argument("--uart", default="0", help="UART instance to bridge (0..3 or USART0..USART3)")
    parser.add_argument("--baud", type=int, default=9600, help="UART bridge baud rate metadata")
    parser.add_argument("--data-bits", type=int, default=8, help="UART bridge data bits metadata")
    parser.add_argument("--parity", default="N", help="UART bridge parity metadata (N/E/O)")
    parser.add_argument("--stop-bits", type=int, default=1, help="UART bridge stop bits metadata")
    parser.add_argument("--uart-bridge-host", default="127.0.0.1", help="TCP host for UART bridge")
    parser.add_argument("--uart-bridge-port", type=int, default=None, help="Enable TCP UART bridge on this port")
    parser.add_argument("--reset-before-run", action="store_true", help="Reset MCU state before execution starts")
    parser.add_argument("--inject-text", default=None, help="Inject UTF-8 text into selected UART RX before execution")
    parser.add_argument("--inject-file", default=None, help="Inject raw file bytes into selected UART RX before execution")
    parser.add_argument("--show-bridge-status", action="store_true", help="Print bridge connection mode/status information")
    parser.add_argument(
        "--uart0-console-simple",
        action="store_true",
        help=(
            "Bypass detailed UART0 TX timing and stream UART0 bytes directly to console "
            "(debug convenience; not behavior-accurate for firmware validation)"
        ),
    )
    parser.add_argument(
        "--adc",
        dest="adc_values",
        action="append",
        default=[],
        metavar="CHANNEL=VALUE[,CHANNEL=VALUE...]",
        help="Set ADC channel startup value, e.g. --adc 0=512 or --adc 0=512,14=977,15=977 (repeatable)",
    )
    args = parser.parse_args()

    uart_text = str(args.uart).upper().replace("USART", "")
    if uart_text not in {"0", "1", "2", "3"}:
        raise SystemExit("UART bridge supports only USART0..USART3.")
    uart_index = int(uart_text)

    emu = ATmega2560Emulator()
    emu.load_program_hex(args.hex_file)
    if args.reset_before_run:
        emu.reset()

    # Parse and apply ADC startup values
    adc_pairs = _parse_adc_args(parser, args.adc_values)
    for channel, value in adc_pairs:
        emu.set_adc_channel_value(channel, value)

    if args.uart0_console_simple:
        if args.uart_bridge_port is not None:
            raise SystemExit("--uart0-console-simple cannot be combined with --uart-bridge-port")
        print(
            "warning: --uart0-console-simple is a debug fast path and can change firmware behavior; "
            "do not use it to validate control-flow/runtime correctness",
            file=sys.stderr,
        )
        _enable_uart0_simple_console_mode(emu)

    bridge = None
    if args.uart_bridge_port is not None:
        bridge = UARTTCPBridge(
            host=args.uart_bridge_host,
            port=args.uart_bridge_port,
            uart_index=uart_index,
            baud=args.baud,
            data_bits=args.data_bits,
            parity=args.parity,
            stop_bits=args.stop_bits,
        )
        bridge.start()
        print(f"uart_bridge={bridge.description()}")
    elif args.show_bridge_status:
        print("uart_bridge=disabled")

    if args.inject_file is not None:
        with open(args.inject_file, "rb") as f:
            _inject_uart_payload(emu, uart_index, f.read())

    if args.inject_text is not None:
        _inject_uart_payload(emu, uart_index, args.inject_text.encode("utf-8"))

    executed = 0
    uart0_console_cursor = 0
    try:
        for i in range(args.steps):
            if emu.halted:
                break

            result = emu.step()
            executed += 1

            if bridge is not None:
                bridge.pump(emu)

            if args.uart0_console_simple:
                uart0_log = emu.get_uart(0).tx_log
                if uart0_console_cursor < len(uart0_log):
                    chunk = bytes(uart0_log[uart0_console_cursor:])
                    uart0_console_cursor = len(uart0_log)
                    _stream_uart_console_bytes(chunk)

            if args.verbose:
                print(
                    f"step={i:06d} "
                    f"pc=0x{result.pc_before:04X}->0x{emu.pc:04X} "
                    f"op=0x{result.opcode:04X} "
                    f"instr=\"{result.description}\" "
                    f"sp=0x{emu.sp:04X} "
                    f"dcyc={result.cycles} "
                    f"cycles={emu.cycles} "
                    f"sreg=0b{emu.sreg:08b}"
                )
                print(f"regs: {_format_regs(emu.reg)}")

            if args.visual and (i % max(args.visual_every, 1) == 0):
                if args.visual_clear:
                    # ANSI clear + cursor home.
                    sys.stdout.write("\x1b[2J\x1b[H")
                    sys.stdout.flush()
                _render_visual(emu, i, result.cycles, result.description, result.opcode)
    finally:
        if bridge is not None:
            bridge.close()

    x = emu.reg[26] | (emu.reg[27] << 8)
    y = emu.reg[28] | (emu.reg[29] << 8)
    z = emu.reg[30] | (emu.reg[31] << 8)

    if args.uart0_console_simple:
        # Keep summary lines visually separated from streamed UART data.
        print()

    print(f"steps={executed}/{args.steps} pc=0x{emu.pc:04X} cycles={emu.cycles} halted={emu.halted}")
    print(f"SREG=0b{emu.sreg:08b} SP=0x{emu.sp:04X} X=0x{x:04X} Y=0x{y:04X} Z=0x{z:04X}")
    print("regs:", _format_regs(emu.reg))
    for index, uart in enumerate(emu.uarts):
        if not uart.tx_log:
            continue
        tx_hex = " ".join(f"{b:02X}" for b in uart.tx_log)
        tx_ascii = "".join(chr(b) if 32 <= b < 127 else "." for b in uart.tx_log)
        print(f"uart{index}_tx_hex={tx_hex}")
        print(f"uart{index}_tx_ascii={tx_ascii}")


if __name__ == "__main__":
    main()
