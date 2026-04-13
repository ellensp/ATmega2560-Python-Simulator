import unittest

from avr_encoding import ldi, lds, sts
from sim_peripherals import UART0
from sim import ATmega2560Emulator


class TestUART0(unittest.TestCase):
    def test_sts_to_udr0_transmits_when_tx_enabled(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[UART0.DATA_UCSR0B] |= 1 << UART0.TXEN0_BIT

        program = [
            ldi(16, 0x41),
            *sts(16, UART0.DATA_UDR0),
        ]
        emu.load_program_words(program)

        emu.step()
        emu.step()

        self.assertEqual(emu.uart0.tx_log, [0x41])
        ucsr0a = emu.data[UART0.DATA_UCSR0A]
        self.assertEqual((ucsr0a >> UART0.UDRE0_BIT) & 1, 1)
        self.assertEqual((ucsr0a >> UART0.TXC0_BIT) & 1, 1)

    def test_sts_to_udr0_ignored_when_tx_disabled(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[UART0.DATA_UCSR0B] &= ~(1 << UART0.TXEN0_BIT)

        program = [
            ldi(16, 0x55),
            *sts(16, UART0.DATA_UDR0),
        ]
        emu.load_program_words(program)

        emu.step()
        emu.step()

        self.assertEqual(emu.uart0.tx_log, [])

    def test_rx_injection_and_udr_read(self) -> None:
        emu = ATmega2560Emulator()
        emu.data[UART0.DATA_UCSR0B] |= 1 << UART0.RXEN0_BIT

        emu.inject_uart0_rx_byte(0x33)
        self.assertEqual((emu.data[UART0.DATA_UCSR0A] >> UART0.RXC0_BIT) & 1, 1)

        # LDS r18, UDR0 should consume the byte and clear RXC when FIFO empty.
        program = [
            *lds(18, UART0.DATA_UDR0),
        ]
        emu.load_program_words(program)
        emu.step()

        self.assertEqual(emu.reg[18], 0x33)
        self.assertEqual((emu.data[UART0.DATA_UCSR0A] >> UART0.RXC0_BIT) & 1, 0)

    def test_rx_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 80)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART0.DATA_UCSR0B] |= (1 << UART0.RXEN0_BIT) | (1 << UART0.RXCIE0_BIT)

        emu.inject_uart0_rx_byte(0x7A)
        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_USART0_RX)

    def test_udre_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 80)
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART0.DATA_UCSR0B] |= (1 << UART0.TXEN0_BIT) | (1 << UART0.UDRIE0_BIT)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_USART0_UDRE)

    def test_tx_interrupt_dispatch_after_transmit_complete(self) -> None:
        emu = ATmega2560Emulator()
        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART0.DATA_UCSR0B] |= (1 << UART0.TXEN0_BIT) | (1 << UART0.TXCIE0_BIT)

        program = [
            ldi(16, 0x41),
            *sts(16, UART0.DATA_UDR0),
        ]
        program.extend([0x0000] * 80)
        emu.load_program_words(program)

        emu.step()  # LDI
        emu.step()  # STS -> queues TX, completion happens at end of step

        self.assertEqual(emu.pc, emu.VECTOR_USART0_TX)


if __name__ == "__main__":
    unittest.main()
