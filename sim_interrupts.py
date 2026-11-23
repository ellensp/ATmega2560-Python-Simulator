"""ATmega2560 emulator — interrupt service mixin."""

from sim_peripherals import Timer0, Timer1, Timer2, Timer3, Timer4, Timer5, WatchdogTimer


class _InterruptsMixin:

    def _service_interrupts(self) -> int:
        """Enter the highest-priority pending interrupt, if any.

        Returns the CPU cycles the entry takes (0 when nothing was serviced). The
        caller advances the cycle counters and the peripherals by that amount.
        """
        if not self._get_flag(self.FLAG_I):
            return 0

        eifr = self.data[0x20 + self.IO_EIFR]
        eimsk = self.data[0x20 + self.IO_EIMSK]
        pcifr = self.data[0x20 + self.IO_PCIFR]
        pcicr = self.data[self.DATA_PCICR]
        wdtcsr = self.data[WatchdogTimer.DATA_WDTCSR]
        eecr = self.data[self.DATA_EECR]
        adcsra = self.data[self.DATA_ADCSRA]
        acsr = self.data[self.DATA_ACSR]
        spcr = self.data[self.DATA_SPCR]
        spsr = self.data[self.DATA_SPSR]
        twcr = self.data[self.DATA_TWCR]

        ext_pending_mask = (eifr & eimsk) & 0xFF
        pcint0_pending = ((pcifr >> 0) & 1) and ((pcicr >> 0) & 1)
        pcint1_pending = ((pcifr >> 1) & 1) and ((pcicr >> 1) & 1)
        pcint2_pending = ((pcifr >> 2) & 1) and ((pcicr >> 2) & 1)
        wdt_pending = ((wdtcsr >> WatchdogTimer.WDIF_BIT) & 1) and ((wdtcsr >> WatchdogTimer.WDIE_BIT) & 1)
        eeprom_ready_pending = self._eeprom_ready_interrupt_pending and ((eecr >> self.EECR_EERIE_BIT) & 1)
        analog_comp_pending = self._analog_comp_interrupt_pending and ((acsr >> self.ACSR_ACIE_BIT) & 1)
        spi_pending = self._spi_interrupt_pending and ((spcr >> self.SPCR_SPIE_BIT) & 1) and ((spsr >> self.SPSR_SPIF_BIT) & 1)
        adc_pending = self._adc_interrupt_pending and ((adcsra >> self.ADC_ADIE_BIT) & 1)
        twi_pending = self._twi_interrupt_pending and ((twcr >> self.TWCR_TWIE_BIT) & 1) and ((twcr >> self.TWCR_TWINT_BIT) & 1)

        tifr0 = self.data[0x20 + Timer0.IO_TIFR0]
        timsk0 = self.data[Timer0.DATA_TIMSK0]
        tifr1 = self.data[0x20 + Timer1.IO_TIFR1]
        timsk1 = self.data[Timer1.DATA_TIMSK1]
        tifr2 = self.data[0x20 + Timer2.IO_TIFR2]
        timsk2 = self.data[Timer2.DATA_TIMSK2]
        tifr3 = self.data[0x20 + Timer3.IO_TIFR3]
        timsk3 = self.data[Timer3.DATA_TIMSK3]
        tifr4 = self.data[0x20 + Timer4.IO_TIFR4]
        timsk4 = self.data[Timer4.DATA_TIMSK4]
        tifr5 = self.data[0x20 + Timer5.IO_TIFR5]
        timsk5 = self.data[Timer5.DATA_TIMSK5]

        compa_pending = ((tifr0 >> Timer0.OCF0A_BIT) & 1) and ((timsk0 >> 1) & 1)
        compb_pending = ((tifr0 >> Timer0.OCF0B_BIT) & 1) and ((timsk0 >> 2) & 1)
        ovf_pending = ((tifr0 >> Timer0.TOV0_BIT) & 1) and (timsk0 & 1)
        timer1_capt_pending = ((tifr1 >> Timer1.ICF1_BIT) & 1) and ((timsk1 >> 5) & 1)
        timer1_compa_pending = ((tifr1 >> Timer1.OCF1A_BIT) & 1) and ((timsk1 >> 1) & 1)
        timer1_compb_pending = ((tifr1 >> Timer1.OCF1B_BIT) & 1) and ((timsk1 >> 2) & 1)
        timer1_compc_pending = ((tifr1 >> Timer1.OCF1C_BIT) & 1) and ((timsk1 >> 3) & 1)
        timer1_ovf_pending = ((tifr1 >> Timer1.TOV1_BIT) & 1) and (timsk1 & 1)
        timer2_compa_pending = ((tifr2 >> Timer2.OCF2A_BIT) & 1) and ((timsk2 >> 1) & 1)
        timer2_compb_pending = ((tifr2 >> Timer2.OCF2B_BIT) & 1) and ((timsk2 >> 2) & 1)
        timer2_ovf_pending = ((tifr2 >> Timer2.TOV2_BIT) & 1) and (timsk2 & 1)
        timer3_capt_pending = ((tifr3 >> Timer3.ICF3_BIT) & 1) and ((timsk3 >> 5) & 1)
        timer3_compa_pending = ((tifr3 >> Timer3.OCF3A_BIT) & 1) and ((timsk3 >> 1) & 1)
        timer3_compb_pending = ((tifr3 >> Timer3.OCF3B_BIT) & 1) and ((timsk3 >> 2) & 1)
        timer3_compc_pending = ((tifr3 >> Timer3.OCF3C_BIT) & 1) and ((timsk3 >> 3) & 1)
        timer3_ovf_pending = ((tifr3 >> Timer3.TOV3_BIT) & 1) and (timsk3 & 1)
        timer4_capt_pending = ((tifr4 >> Timer4.ICF4_BIT) & 1) and ((timsk4 >> 5) & 1)
        timer4_compa_pending = ((tifr4 >> Timer4.OCF4A_BIT) & 1) and ((timsk4 >> 1) & 1)
        timer4_compb_pending = ((tifr4 >> Timer4.OCF4B_BIT) & 1) and ((timsk4 >> 2) & 1)
        timer4_compc_pending = ((tifr4 >> Timer4.OCF4C_BIT) & 1) and ((timsk4 >> 3) & 1)
        timer4_ovf_pending = ((tifr4 >> Timer4.TOV4_BIT) & 1) and (timsk4 & 1)
        timer5_capt_pending = ((tifr5 >> Timer5.ICF5_BIT) & 1) and ((timsk5 >> 5) & 1)
        timer5_compa_pending = ((tifr5 >> Timer5.OCF5A_BIT) & 1) and ((timsk5 >> 1) & 1)
        timer5_compb_pending = ((tifr5 >> Timer5.OCF5B_BIT) & 1) and ((timsk5 >> 2) & 1)
        timer5_compc_pending = ((tifr5 >> Timer5.OCF5C_BIT) & 1) and ((timsk5 >> 3) & 1)
        timer5_ovf_pending = ((tifr5 >> Timer5.TOV5_BIT) & 1) and (timsk5 & 1)

        vector = None
        if ext_pending_mask:
            ext_index = 0
            while ext_index < 8 and ((ext_pending_mask >> ext_index) & 1) == 0:
                ext_index += 1
            self.data[0x20 + self.IO_EIFR] &= ~(1 << ext_index)
            vector = self._ext_int_vector(ext_index)
        elif pcint0_pending:
            self.data[0x20 + self.IO_PCIFR] &= ~(1 << 0)
            vector = self.VECTOR_PCINT0
        elif pcint1_pending:
            self.data[0x20 + self.IO_PCIFR] &= ~(1 << 1)
            vector = self.VECTOR_PCINT1
        elif pcint2_pending:
            self.data[0x20 + self.IO_PCIFR] &= ~(1 << 2)
            vector = self.VECTOR_PCINT2
        elif wdt_pending:
            self.watchdog.on_interrupt_serviced(self.data)
            vector = self.VECTOR_WDT
        elif spi_pending:
            self._spi_interrupt_pending = False
            vector = self.VECTOR_SPI_STC
        elif analog_comp_pending:
            self._analog_comp_interrupt_pending = False
            self.data[self.DATA_ACSR] &= ~(1 << self.ACSR_ACI_BIT)
            vector = self.VECTOR_ANALOG_COMP
        elif adc_pending:
            self._adc_interrupt_pending = False
            vector = self.VECTOR_ADC
        elif eeprom_ready_pending:
            self._eeprom_ready_interrupt_pending = False
            vector = self.VECTOR_EEPROM_READY
        elif compa_pending:
            self.data[0x20 + Timer0.IO_TIFR0] &= ~(1 << Timer0.OCF0A_BIT)
            vector = self.VECTOR_TIMER0_COMPA
        elif compb_pending:
            self.data[0x20 + Timer0.IO_TIFR0] &= ~(1 << Timer0.OCF0B_BIT)
            vector = self.VECTOR_TIMER0_COMPB
        elif ovf_pending:
            self.data[0x20 + Timer0.IO_TIFR0] &= ~(1 << Timer0.TOV0_BIT)
            vector = self.VECTOR_TIMER0_OVF
        elif timer1_capt_pending:
            self.data[0x20 + Timer1.IO_TIFR1] &= ~(1 << Timer1.ICF1_BIT)
            vector = self.VECTOR_TIMER1_CAPT
        elif timer1_compa_pending:
            self.data[0x20 + Timer1.IO_TIFR1] &= ~(1 << Timer1.OCF1A_BIT)
            vector = self.VECTOR_TIMER1_COMPA
        elif timer1_compb_pending:
            self.data[0x20 + Timer1.IO_TIFR1] &= ~(1 << Timer1.OCF1B_BIT)
            vector = self.VECTOR_TIMER1_COMPB
        elif timer1_compc_pending:
            self.data[0x20 + Timer1.IO_TIFR1] &= ~(1 << Timer1.OCF1C_BIT)
            vector = self.VECTOR_TIMER1_COMPC
        elif timer1_ovf_pending:
            self.data[0x20 + Timer1.IO_TIFR1] &= ~(1 << Timer1.TOV1_BIT)
            vector = self.VECTOR_TIMER1_OVF
        elif timer2_compa_pending:
            self.data[0x20 + Timer2.IO_TIFR2] &= ~(1 << Timer2.OCF2A_BIT)
            vector = self.VECTOR_TIMER2_COMPA
        elif timer2_compb_pending:
            self.data[0x20 + Timer2.IO_TIFR2] &= ~(1 << Timer2.OCF2B_BIT)
            vector = self.VECTOR_TIMER2_COMPB
        elif timer2_ovf_pending:
            self.data[0x20 + Timer2.IO_TIFR2] &= ~(1 << Timer2.TOV2_BIT)
            vector = self.VECTOR_TIMER2_OVF
        elif timer3_capt_pending:
            self.data[0x20 + Timer3.IO_TIFR3] &= ~(1 << Timer3.ICF3_BIT)
            vector = self.VECTOR_TIMER3_CAPT
        elif timer3_compa_pending:
            self.data[0x20 + Timer3.IO_TIFR3] &= ~(1 << Timer3.OCF3A_BIT)
            vector = self.VECTOR_TIMER3_COMPA
        elif timer3_compb_pending:
            self.data[0x20 + Timer3.IO_TIFR3] &= ~(1 << Timer3.OCF3B_BIT)
            vector = self.VECTOR_TIMER3_COMPB
        elif timer3_compc_pending:
            self.data[0x20 + Timer3.IO_TIFR3] &= ~(1 << Timer3.OCF3C_BIT)
            vector = self.VECTOR_TIMER3_COMPC
        elif timer3_ovf_pending:
            self.data[0x20 + Timer3.IO_TIFR3] &= ~(1 << Timer3.TOV3_BIT)
            vector = self.VECTOR_TIMER3_OVF
        elif timer4_capt_pending:
            self.data[0x20 + Timer4.IO_TIFR4] &= ~(1 << Timer4.ICF4_BIT)
            vector = self.VECTOR_TIMER4_CAPT
        elif timer4_compa_pending:
            self.data[0x20 + Timer4.IO_TIFR4] &= ~(1 << Timer4.OCF4A_BIT)
            vector = self.VECTOR_TIMER4_COMPA
        elif timer4_compb_pending:
            self.data[0x20 + Timer4.IO_TIFR4] &= ~(1 << Timer4.OCF4B_BIT)
            vector = self.VECTOR_TIMER4_COMPB
        elif timer4_compc_pending:
            self.data[0x20 + Timer4.IO_TIFR4] &= ~(1 << Timer4.OCF4C_BIT)
            vector = self.VECTOR_TIMER4_COMPC
        elif timer4_ovf_pending:
            self.data[0x20 + Timer4.IO_TIFR4] &= ~(1 << Timer4.TOV4_BIT)
            vector = self.VECTOR_TIMER4_OVF
        elif timer5_capt_pending:
            self.data[0x20 + Timer5.IO_TIFR5] &= ~(1 << Timer5.ICF5_BIT)
            vector = self.VECTOR_TIMER5_CAPT
        elif timer5_compa_pending:
            self.data[0x20 + Timer5.IO_TIFR5] &= ~(1 << Timer5.OCF5A_BIT)
            vector = self.VECTOR_TIMER5_COMPA
        elif timer5_compb_pending:
            self.data[0x20 + Timer5.IO_TIFR5] &= ~(1 << Timer5.OCF5B_BIT)
            vector = self.VECTOR_TIMER5_COMPB
        elif timer5_compc_pending:
            self.data[0x20 + Timer5.IO_TIFR5] &= ~(1 << Timer5.OCF5C_BIT)
            vector = self.VECTOR_TIMER5_COMPC
        elif timer5_ovf_pending:
            self.data[0x20 + Timer5.IO_TIFR5] &= ~(1 << Timer5.TOV5_BIT)
            vector = self.VECTOR_TIMER5_OVF
        else:
            for index, uart in enumerate(self.uarts):
                ucsra = self.data[uart.DATA_UCSRA]
                ucsrb = self.data[uart.DATA_UCSRB]
                rx_vector, udre_vector, tx_vector = self._uart_vectors(index)

                if ((ucsra >> uart.RXC_BIT) & 1) and ((ucsrb >> uart.RXCIE_BIT) & 1):
                    vector = rx_vector
                    break
                if ((ucsra >> uart.UDRE_BIT) & 1) and ((ucsrb >> uart.UDRIE_BIT) & 1):
                    vector = udre_vector
                    break
                if ((ucsra >> uart.TXC_BIT) & 1) and ((ucsrb >> uart.TXCIE_BIT) & 1):
                    vector = tx_vector
                    break

            if vector is None and twi_pending:
                self._twi_interrupt_pending = False
                vector = self.VECTOR_TWI

        if vector is None:
            return 0

        self._set_flag(self.FLAG_I, 0)
        self._push_return_address(self.pc)
        self.pc = vector
        # Interrupt response: 4 cycles, 5 with a 3-byte PC push (ATmega2560).
        return 4 + self.pc_extra_cycles
