import socket
import time
import unittest

from sim_peripherals import UART0, UART1, UART2, UART3
from run_hex import UARTTCPBridge, _inject_uart_payload
from sim import ATmega2560Emulator


class TestUARTTCPBridge(unittest.TestCase):
    def test_inject_uart_payload_primes_selected_uart_rx_fifo(self) -> None:
        emu = ATmega2560Emulator()

        _inject_uart_payload(emu, 2, b"Hi")

        self.assertEqual(emu.data[UART2.DATA_UDR2], ord("H"))
        self.assertEqual((emu.data[UART2.DATA_UCSR2A] >> UART2.RXC2_BIT) & 1, 1)

    def test_inject_uart_payload_primes_uart0_rx_fifo(self) -> None:
        emu = ATmega2560Emulator()

        _inject_uart_payload(emu, 0, b"Hi")

        self.assertEqual(emu.data[UART0.DATA_UDR0], ord("H"))
        self.assertEqual((emu.data[UART0.DATA_UCSR0A] >> UART0.RXC0_BIT) & 1, 1)

    def test_bridge_receives_tcp_data_into_uart0(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[UART0.DATA_UCSR0B] |= 1 << UART0.RXEN0_BIT

        bridge = UARTTCPBridge("127.0.0.1", 0)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.sendall(b"Z")

        for _ in range(20):
            bridge.pump(emu)
            if emu.data[UART0.DATA_UDR0] == ord("Z"):
                break
            time.sleep(0.01)

        self.assertEqual(emu.data[UART0.DATA_UDR0], ord("Z"))
        self.assertEqual((emu.data[UART0.DATA_UCSR0A] >> UART0.RXC0_BIT) & 1, 1)

        client.close()
        bridge.close()

    def test_bridge_forwards_uart0_tx_log(self) -> None:
        emu = ATmega2560Emulator()
        bridge = UARTTCPBridge("127.0.0.1", 0)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.settimeout(1.0)

        # First pump accepts the client.
        bridge.pump(emu)
        emu.uart0.tx_log.append(0x41)
        bridge.pump(emu)

        self.assertEqual(client.recv(1), b"A")

        client.close()
        bridge.close()

    def test_bridge_forwards_selected_uart_tx_log(self) -> None:
        emu = ATmega2560Emulator()
        bridge = UARTTCPBridge("127.0.0.1", 0, uart_index=3)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.settimeout(1.0)

        bridge.pump(emu)
        emu.get_uart(3).tx_log.append(0x44)
        bridge.pump(emu)

        self.assertEqual(client.recv(1), b"D")

        client.close()
        bridge.close()

    def test_bridge_rx_can_drive_usart0_interrupt(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART0.DATA_UCSR0B] |= (1 << UART0.RXEN0_BIT) | (1 << UART0.RXCIE0_BIT)

        bridge = UARTTCPBridge("127.0.0.1", 0)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.sendall(b"Q")

        for _ in range(20):
            bridge.pump(emu)
            emu.step()
            if emu.pc == emu.VECTOR_USART0_RX:
                break
            time.sleep(0.01)

        self.assertEqual(emu.pc, emu.VECTOR_USART0_RX)

        client.close()
        bridge.close()

    def test_bridge_receives_tcp_data_into_selected_uart(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[UART1.DATA_UCSR1B] |= 1 << UART1.RXEN1_BIT

        bridge = UARTTCPBridge("127.0.0.1", 0, uart_index=1)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.sendall(b"Z")

        for _ in range(20):
            bridge.pump(emu)
            if emu.data[UART1.DATA_UDR1] == ord("Z"):
                break
            time.sleep(0.01)

        self.assertEqual(emu.data[UART1.DATA_UDR1], ord("Z"))
        self.assertEqual((emu.data[UART1.DATA_UCSR1A] >> UART1.RXC1_BIT) & 1, 1)

        client.close()
        bridge.close()

    def test_bridge_rx_can_drive_selected_usart_interrupt(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART3.DATA_UCSR3B] |= (1 << UART3.RXEN3_BIT) | (1 << UART3.RXCIE3_BIT)

        bridge = UARTTCPBridge("127.0.0.1", 0, uart_index=3)
        bridge.start()
        port = bridge._server.getsockname()[1]  # type: ignore[union-attr]

        client = socket.create_connection(("127.0.0.1", port), timeout=1.0)
        client.sendall(b"Q")

        for _ in range(20):
            bridge.pump(emu)
            emu.step()
            if emu.pc == emu.VECTOR_USART3_RX:
                break
            time.sleep(0.01)

        self.assertEqual(emu.pc, emu.VECTOR_USART3_RX)

        client.close()
        bridge.close()


if __name__ == "__main__":
    unittest.main()
