"""ATmega2560 emulator — interrupt service mixin."""

from sim_peripherals import Timer0, Timer1, Timer2, Timer3, Timer4, Timer5, WatchdogTimer


class _InterruptsMixin:

    # (TIFR/TIMSK bit, vector) in priority order.
    _TIMER8_SOURCES = ((1, "COMPA"), (2, "COMPB"), (0, "OVF"))
    _TIMER16_SOURCES = ((5, "CAPT"), (1, "COMPA"), (2, "COMPB"), (3, "COMPC"), (0, "OVF"))

    def _timer_pending(self, n: int, timer_cls):
        tifr_addr = 0x20 + getattr(timer_cls, f"IO_TIFR{n}")
        pending = self.data[tifr_addr] & self.data[getattr(timer_cls, f"DATA_TIMSK{n}")]
        if not pending:
            return None
        for bit, name in (self._TIMER8_SOURCES if n in (0, 2) else self._TIMER16_SOURCES):
            if (pending >> bit) & 1:
                return (getattr(self, f"VECTOR_TIMER{n}_{name}"), tifr_addr, 1 << bit, None)
        return None

    def _uart_pending(self, index: int):
        uart = self.uarts[index]
        ucsra = self.data[uart.DATA_UCSRA]
        ucsrb = self.data[uart.DATA_UCSRB]
        if not (ucsra & ucsrb & 0xE0):  # RXC/TXC/UDRE and their enables share bit positions
            return None
        rx_vector, udre_vector, tx_vector = self._uart_vectors(index)
        if ((ucsra >> uart.RXC_BIT) & 1) and ((ucsrb >> uart.RXCIE_BIT) & 1):
            return (rx_vector, None, 0, None)
        if ((ucsra >> uart.UDRE_BIT) & 1) and ((ucsrb >> uart.UDRIE_BIT) & 1):
            return (udre_vector, None, 0, None)
        # TXC is cleared when its vector is executed.
        return (tx_vector, uart.DATA_UCSRA, 1 << uart.TXC_BIT, None)

    def _find_pending_interrupt(self):
        """Highest-priority enabled pending interrupt (lowest vector first), without
        side effects: (vector, flag register or None, flag mask, pending attribute or None)."""
        data = self.data

        eifr_addr = 0x20 + self.IO_EIFR
        pending = (data[eifr_addr] | self._ext_level_mask) & data[0x20 + self.IO_EIMSK]
        if pending:
            index = (pending & -pending).bit_length() - 1
            return (self._ext_int_vector(index), eifr_addr, 1 << index, None)

        pcifr_addr = 0x20 + self.IO_PCIFR
        pending = data[pcifr_addr] & data[self.DATA_PCICR] & 0x07
        if pending:
            index = (pending & -pending).bit_length() - 1
            return ((self.VECTOR_PCINT0, self.VECTOR_PCINT1, self.VECTOR_PCINT2)[index], pcifr_addr, 1 << index, None)

        wdtcsr = data[WatchdogTimer.DATA_WDTCSR]
        if ((wdtcsr >> WatchdogTimer.WDIF_BIT) & 1) and ((wdtcsr >> WatchdogTimer.WDIE_BIT) & 1):
            return (self.VECTOR_WDT, WatchdogTimer.DATA_WDTCSR, 1 << WatchdogTimer.WDIF_BIT, None)

        found = self._timer_pending(2, Timer2) or self._timer_pending(1, Timer1) or self._timer_pending(0, Timer0)
        if found:
            return found

        if self._spi_interrupt_pending:
            spcr = data[self.DATA_SPCR]
            spsr = data[self.DATA_SPSR]
            if ((spcr >> self.SPCR_SPIE_BIT) & 1) and ((spsr >> self.SPSR_SPIF_BIT) & 1):
                return (self.VECTOR_SPI_STC, self.DATA_SPSR, 1 << self.SPSR_SPIF_BIT, "_spi_interrupt_pending")

        found = self._uart_pending(0)
        if found:
            return found

        if self._analog_comp_interrupt_pending and ((data[self.DATA_ACSR] >> self.ACSR_ACIE_BIT) & 1):
            return (self.VECTOR_ANALOG_COMP, self.DATA_ACSR, 1 << self.ACSR_ACI_BIT, "_analog_comp_interrupt_pending")

        if self._adc_interrupt_pending and ((data[self.DATA_ADCSRA] >> self.ADC_ADIE_BIT) & 1):
            return (self.VECTOR_ADC, self.DATA_ADCSRA, 1 << self.ADC_ADIF_BIT, "_adc_interrupt_pending")

        if self._eeprom_ready_interrupt_pending and ((data[self.DATA_EECR] >> self.EECR_EERIE_BIT) & 1):
            return (self.VECTOR_EEPROM_READY, None, 0, "_eeprom_ready_interrupt_pending")

        found = self._timer_pending(3, Timer3) or self._uart_pending(1)
        if found:
            return found

        if self._twi_interrupt_pending:
            twcr = data[self.DATA_TWCR]
            if ((twcr >> self.TWCR_TWIE_BIT) & 1) and ((twcr >> self.TWCR_TWINT_BIT) & 1):
                return (self.VECTOR_TWI, None, 0, "_twi_interrupt_pending")

        return (
            self._timer_pending(4, Timer4)
            or self._timer_pending(5, Timer5)
            or self._uart_pending(2)
            or self._uart_pending(3)
        )

    def _service_interrupts(self) -> int:
        """Enter the highest-priority pending interrupt, if any.

        Returns the CPU cycles the entry takes (0 when nothing was serviced). The
        caller advances the cycle counters and the peripherals by that amount.
        """
        if not self._get_flag(self.FLAG_I):
            return 0
        found = self._find_pending_interrupt()
        if found is None:
            return 0

        vector, flag_addr, flag_mask, pending_attr = found
        if flag_addr is not None:
            self.data[flag_addr] &= ~flag_mask & 0xFF
        if pending_attr is not None:
            setattr(self, pending_attr, False)

        self._set_flag(self.FLAG_I, 0)
        self._push_return_address(self.pc)
        self.pc = vector
        # Four cycles on a real ATmega2560. With the cycle an interrupt has to be
        # pending before it is taken, that is the datasheet's five-cycle response.
        return 4
