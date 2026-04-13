import unittest

from avr_encoding import add, ldi, lds, rjmp, sts
from sim_peripherals import UART0, WatchdogTimer
from sim import ATmega2560Emulator


class TestISRFirmwarePatterns(unittest.TestCase):
    def test_timer0_compa_isr_tick_updates_sram_counter(self) -> None:
        emu = ATmega2560Emulator()
        counter_addr = 0x0200

        program = [rjmp(-1)] * 128
        vector = emu.VECTOR_TIMER0_COMPA
        program[vector:vector + 6] = [
            *lds(16, counter_addr),
            ldi(17, 1),
            add(16, 17),
            *sts(16, counter_addr),
            0x9518,  # RETI
        ]
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x27] = 0x03  # OCR0A
        emu.data[0x006E] = 0x02       # TIMSK0 OCIE0A

        while emu.data[counter_addr] == 0:
            emu.step()

        while emu.sp != 0x21FF:
            emu.step()

        self.assertEqual(emu.data[counter_addr], 1)
        self.assertEqual(emu.sp, 0x21FF)

    def test_uart_rx_isr_reads_udr_and_stores_byte(self) -> None:
        emu = ATmega2560Emulator()
        sink_addr = 0x0201

        program = [rjmp(-1)] * 128
        vector = emu.VECTOR_USART0_RX
        program[vector:vector + 4] = [
            *lds(16, UART0.DATA_UDR0),
            *sts(16, sink_addr),
            0x9518,  # RETI
        ]
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[UART0.DATA_UCSR0B] |= (1 << UART0.RXEN0_BIT) | (1 << UART0.RXCIE0_BIT)
        emu.inject_uart0_rx_byte(0x5A)

        while emu.data[sink_addr] != 0x5A:
            emu.step()

        while emu.sp != 0x21FF:
            emu.step()

        self.assertEqual(emu.data[sink_addr], 0x5A)
        self.assertEqual((emu.data[UART0.DATA_UCSR0A] >> UART0.RXC0_BIT) & 1, 0)
        self.assertEqual(emu.sp, 0x21FF)

    def test_int0_isr_sets_sram_flag(self) -> None:
        emu = ATmega2560Emulator()
        flag_addr = 0x0202

        program = [rjmp(-1)] * 64
        vector = emu.VECTOR_INT0
        program[vector:vector + 3] = [
            ldi(16, 0xA5),
            *sts(16, flag_addr),
            0x9518,  # RETI
        ]
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + emu.IO_EIMSK] = 0x01
        emu.data[emu.DATA_EICRA] = 0x03  # rising edge
        emu.set_int0_pin(0)
        emu.set_int0_pin(1)

        while emu.data[flag_addr] != 0xA5:
            emu.step()

        while emu.sp != 0x21FF:
            emu.step()

        self.assertEqual(emu.data[flag_addr], 0xA5)
        self.assertEqual(emu.sp, 0x21FF)

    def test_watchdog_isr_sets_sram_flag(self) -> None:
        emu = ATmega2560Emulator()
        flag_addr = 0x0203

        program = [rjmp(-1)] * 128
        vector = emu.VECTOR_WDT
        program[vector:vector + 3] = [
            ldi(16, 0x5D),
            *sts(16, flag_addr),
            0x9518,  # RETI
        ]
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x40)  # WDIE

        while emu.data[flag_addr] != 0x5D:
            emu.step()

        while emu.sp != 0x21FF:
            emu.step()

        self.assertEqual(emu.data[flag_addr], 0x5D)
        self.assertEqual(emu.sp, 0x21FF)


if __name__ == "__main__":
    unittest.main()
