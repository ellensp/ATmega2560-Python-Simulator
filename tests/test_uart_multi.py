import unittest

from avr_encoding import ldi, lds, sts
from sim_peripherals import UART1, UART2, UART3
from sim import ATmega2560Emulator


class TestAdditionalUARTs(unittest.TestCase):
    UART_CASES = [
        (1, UART1, "VECTOR_USART1_RX", "VECTOR_USART1_UDRE", "VECTOR_USART1_TX"),
        (2, UART2, "VECTOR_USART2_RX", "VECTOR_USART2_UDRE", "VECTOR_USART2_TX"),
        (3, UART3, "VECTOR_USART3_RX", "VECTOR_USART3_UDRE", "VECTOR_USART3_TX"),
    ]

    def test_tx_path_transmits_when_enabled(self) -> None:
        for index, uart_cls, _, _, _ in self.UART_CASES:
            with self.subTest(uart=index):
                emu = ATmega2560Emulator()
                emu.data[uart_cls.DATA_UCSRB] |= 1 << uart_cls.TXEN_BIT

                program = [
                    ldi(16, 0x40 + index),
                    *sts(16, uart_cls.DATA_UDR),
                ]
                emu.load_program_words(program)

                emu.step()
                emu.step()

                emu.step()  # one instruction later (hardware timing)
                self.assertEqual(emu.get_uart(index).tx_log, [0x40 + index])
                ucsra = emu.data[uart_cls.DATA_UCSRA]
                self.assertEqual((ucsra >> uart_cls.UDRE_BIT) & 1, 1)
                self.assertEqual((ucsra >> uart_cls.TXC_BIT) & 1, 1)

    def test_rx_path_consumes_injected_data(self) -> None:
        for index, uart_cls, _, _, _ in self.UART_CASES:
            with self.subTest(uart=index):
                emu = ATmega2560Emulator()
                emu.data[uart_cls.DATA_UCSRB] |= 1 << uart_cls.RXEN_BIT

                emu.inject_uart_rx_byte(index, 0x30 + index)
                self.assertEqual((emu.data[uart_cls.DATA_UCSRA] >> uart_cls.RXC_BIT) & 1, 1)

                emu.load_program_words([*lds(18, uart_cls.DATA_UDR)])
                emu.step()

                self.assertEqual(emu.reg[18], 0x30 + index)
                self.assertEqual((emu.data[uart_cls.DATA_UCSRA] >> uart_cls.RXC_BIT) & 1, 0)

    def test_rx_and_udre_interrupt_dispatch(self) -> None:
        for index, uart_cls, rx_vector_name, udre_vector_name, _ in self.UART_CASES:
            with self.subTest(uart=index):
                emu = ATmega2560Emulator()
                emu.load_program_words([0x0000] * 96)
                emu._set_flag(emu.FLAG_I, 1)
                emu.data[uart_cls.DATA_UCSRB] |= (1 << uart_cls.RXEN_BIT) | (1 << uart_cls.RXCIE_BIT)
                emu.inject_uart_rx_byte(index, 0x50 + index)

                emu.step()
                self.assertEqual(emu.pc, getattr(emu, rx_vector_name))

                emu = ATmega2560Emulator()
                emu.load_program_words([0x0000] * 96)
                emu._set_flag(emu.FLAG_I, 1)
                emu.data[uart_cls.DATA_UCSRB] |= (1 << uart_cls.TXEN_BIT) | (1 << uart_cls.UDRIE_BIT)

                emu.step()
                self.assertEqual(emu.pc, getattr(emu, udre_vector_name))

    def test_tx_interrupt_dispatch_after_transmit_complete(self) -> None:
        for index, uart_cls, _, _, tx_vector_name in self.UART_CASES:
            with self.subTest(uart=index):
                emu = ATmega2560Emulator()
                emu._set_flag(emu.FLAG_I, 1)
                emu.data[uart_cls.DATA_UCSRB] |= (1 << uart_cls.TXEN_BIT) | (1 << uart_cls.TXCIE_BIT)

                program = [
                    ldi(16, 0x60 + index),
                    *sts(16, uart_cls.DATA_UDR),
                ]
                program.extend([0x0000] * 96)
                emu.load_program_words(program)

                emu.step()
                emu.step()

                emu.step()  # one instruction later (hardware timing)
                emu.step()  # one instruction later (hardware timing)
                self.assertEqual(emu.pc, getattr(emu, tx_vector_name))


if __name__ == "__main__":
    unittest.main()