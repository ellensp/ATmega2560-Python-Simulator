"""ATmega2560 emulator — peripheral control mixin.

Covers: ADC, analog comparator, SPI, TWI/I2C, EEPROM, UART helpers,
and timer input-capture triggers.
"""

from typing import Iterable, List

from sim_peripherals import Timer1, Timer3, Timer4, Timer5, UARTBase


class _PeripheralsCtrlMixin:
    # -----------------------------
    # ADC
    # -----------------------------

    def set_adc_channel_value(self, channel: int, value: int) -> None:
        if channel < 0 or channel >= len(self._adc_channel_values):
            raise ValueError("ADC channel must be in range 0..15")
        self._adc_channel_values[channel] = value & 0x3FF

    def _adc_selected_channel(self) -> int:
        mux = self.data[self.DATA_ADMUX] & 0x1F
        mux5 = (self.data[self.DATA_ADCSRB] >> 3) & 1
        return (mux5 << 3) | (mux & 0x07)

    def _adc_clock_divisor(self) -> int:
        prescaler = self.data[self.DATA_ADCSRA] & self.ADC_ADPS_MASK
        return 2 if prescaler == 0 else 1 << prescaler  # ADPS 0 and 1 both select /2

    def _adc_conversion_cycles(self) -> int:
        """Cycles from the ADSC write to ADIF. The ADC prescaler runs freely from the
        moment ADEN is set; a conversion starts on its next edge and takes 13 ADC
        clocks, 25 for the first one after enabling (measured on a real ATmega2560)."""
        scale = self._adc_clock_divisor()
        clocks = 25 if self._adc_first_conversion else self.ADC_BASE_CONVERSION_CYCLES
        wait = scale - (self._adc_clock_cycles % scale)
        return wait + clocks * scale + 1

    def _start_adc_conversion(self) -> None:
        self._adc_conversion_channel = self._adc_selected_channel()
        self._adc_conversion_cycles_remaining = self._adc_conversion_cycles()
        self._adc_first_conversion = False
        self.data[self.DATA_ADCSRA] |= 1 << self.ADC_ADSC_BIT

    def _write_adcsra(self, value: int) -> None:
        value &= 0xFF
        cur = self.data[self.DATA_ADCSRA]

        # ADIF is write-one-to-clear.
        if (value >> self.ADC_ADIF_BIT) & 1:
            cur &= ~(1 << self.ADC_ADIF_BIT)
            self._adc_interrupt_pending = False

        control_mask = (
            (1 << self.ADC_ADEN_BIT)
            | (1 << self.ADC_ADSC_BIT)
            | (1 << self.ADC_ADATE_BIT)
            | (1 << self.ADC_ADIE_BIT)
            | self.ADC_ADPS_MASK
        )
        if ((value >> self.ADC_ADEN_BIT) & 1) and not ((cur >> self.ADC_ADEN_BIT) & 1):
            self._adc_first_conversion = True
            self._adc_clock_cycles = self.ADC_ENABLE_PHASE
        cur = (cur & ~control_mask) | (value & control_mask)
        self.data[self.DATA_ADCSRA] = cur & 0xFF

        adsc_req = ((value >> self.ADC_ADSC_BIT) & 1) == 1
        aden = ((self.data[self.DATA_ADCSRA] >> self.ADC_ADEN_BIT) & 1) == 1
        if adsc_req and aden and self._adc_conversion_cycles_remaining == 0:
            self._start_adc_conversion()
        elif not aden:
            self._adc_conversion_cycles_remaining = 0
            self.data[self.DATA_ADCSRA] &= ~(1 << self.ADC_ADSC_BIT)

    def _adc_commit_result(self) -> None:
        result = self._adc_channel_values[self._adc_conversion_channel] & 0x3FF
        adlar = (self.data[self.DATA_ADMUX] >> self.ADC_ADLAR_BIT) & 1

        # A result that completes between the ADCL and ADCH reads is lost.
        if not self._adc_locked:
            if adlar:
                self.data[self.DATA_ADCH] = (result >> 2) & 0xFF
                self.data[self.DATA_ADCL] = (result & 0x03) << 6
            else:
                self.data[self.DATA_ADCL] = result & 0xFF
                self.data[self.DATA_ADCH] = (result >> 8) & 0x03

        self.data[self.DATA_ADCSRA] &= ~(1 << self.ADC_ADSC_BIT)
        self.data[self.DATA_ADCSRA] |= 1 << self.ADC_ADIF_BIT
        self._adc_interrupt_pending = True

        # Free-running mode: ADATE with trigger source 0 starts the next conversion.
        adcsra = self.data[self.DATA_ADCSRA]
        if ((adcsra >> self.ADC_ADATE_BIT) & 1) and ((adcsra >> self.ADC_ADEN_BIT) & 1) and (self.data[self.DATA_ADCSRB] & 0x07) == 0:
            self._start_adc_conversion()
            # Back to back: exactly 13 ADC clocks from one result to the next.
            self._adc_conversion_cycles_remaining = self.ADC_BASE_CONVERSION_CYCLES * self._adc_clock_divisor()

    # Flag that starts a conversion on its rising edge, by ADTS2:0 (1..7).
    def _adc_trigger_level(self, source: int) -> int:
        data = self.data
        if source == 1:
            return self._analog_comp_output
        if source == 2:
            return data[0x20 + self.IO_EIFR] & 0x01
        if source == 3:
            return (data[0x35] >> 1) & 1   # OCF0A
        if source == 4:
            return data[0x35] & 1          # TOV0
        if source == 5:
            return (data[0x36] >> 2) & 1   # OCF1B
        if source == 6:
            return data[0x36] & 1          # TOV1
        return (data[0x36] >> 5) & 1       # ICF1

    def _advance_adc(self, cycles: int) -> None:
        if cycles <= 0:
            return
        adcsra = self.data[self.DATA_ADCSRA]
        if (adcsra >> self.ADC_ADEN_BIT) & 1:
            self._adc_clock_cycles += cycles
            source = self.data[self.DATA_ADCSRB] & 0x07
            if source and ((adcsra >> self.ADC_ADATE_BIT) & 1):
                level = self._adc_trigger_level(source)
                if level and not self._adc_trigger_last and self._adc_conversion_cycles_remaining == 0:
                    self._start_adc_conversion()
                self._adc_trigger_last = level
        if self._adc_conversion_cycles_remaining <= 0:
            return
        overshoot = cycles - self._adc_conversion_cycles_remaining
        self._adc_conversion_cycles_remaining = max(0, -overshoot)
        if self._adc_conversion_cycles_remaining == 0:
            self._adc_commit_result()
            if self._adc_conversion_cycles_remaining > 0:
                # A free-running conversion started on time, not at the end of this step.
                self._adc_conversion_cycles_remaining = max(1, self._adc_conversion_cycles_remaining - overshoot)

    # -----------------------------
    # Analog comparator
    # -----------------------------

    def set_analog_comparator_inputs(self, positive: int, negative: int) -> None:
        self._analog_comp_positive_input = int(positive)
        self._analog_comp_negative_input = int(negative)
        self._refresh_analog_comparator()

    def _analog_comp_positive_value(self) -> int:
        if (self.data[self.DATA_ACSR] >> self.ACSR_ACBG_BIT) & 1:
            return self.ANALOG_COMPARATOR_BANDGAP_LEVEL
        return self._analog_comp_positive_input

    def _analog_comp_current_output(self) -> int:
        if (self.data[self.DATA_ACSR] >> self.ACSR_ACD_BIT) & 1:
            return 0
        return int(self._analog_comp_positive_value() > self._analog_comp_negative_input)

    def _analog_comp_interrupt_matches(self, old: int, new: int) -> bool:
        mode = self.data[self.DATA_ACSR] & 0x03
        if mode in (0b00, 0b01):
            return old != new
        if mode == 0b10:
            return old == 1 and new == 0
        return old == 0 and new == 1

    def _analog_comp_capture_matches(self, old: int, new: int) -> bool:
        tccr1b = self.data[Timer1.DATA_TCCR1B]
        rising_edge = ((tccr1b >> 6) & 1) == 1
        if rising_edge:
            return old == 0 and new == 1
        return old == 1 and new == 0

    def _refresh_analog_comparator(self) -> None:
        old = self._analog_comp_output
        new = self._analog_comp_current_output()
        self._analog_comp_output = new

        if new:
            self.data[self.DATA_ACSR] |= 1 << self.ACSR_ACO_BIT
        else:
            self.data[self.DATA_ACSR] &= ~(1 << self.ACSR_ACO_BIT)

        if old == new:
            return

        if self._analog_comp_interrupt_matches(old, new):
            self.data[self.DATA_ACSR] |= 1 << self.ACSR_ACI_BIT
            self._analog_comp_interrupt_pending = True

        if ((self.data[self.DATA_ACSR] >> self.ACSR_ACIC_BIT) & 1) and self._analog_comp_capture_matches(old, new):
            self.trigger_timer1_capture()

    def _write_acsr(self, value: int) -> None:
        value &= 0xFF
        current = self.data[self.DATA_ACSR]

        if (value >> self.ACSR_ACI_BIT) & 1:
            current &= ~(1 << self.ACSR_ACI_BIT)
            self._analog_comp_interrupt_pending = False

        writable_mask = (
            (1 << self.ACSR_ACIS0_BIT)
            | (1 << self.ACSR_ACIS1_BIT)
            | (1 << self.ACSR_ACIC_BIT)
            | (1 << self.ACSR_ACIE_BIT)
            | (1 << self.ACSR_ACBG_BIT)
            | (1 << self.ACSR_ACD_BIT)
        )
        current = (current & ~writable_mask) | (value & writable_mask)
        self.data[self.DATA_ACSR] = current & 0xFF
        self._refresh_analog_comparator()

    # -----------------------------
    # SPI
    # -----------------------------

    def queue_spi_response_bytes(self, values: Iterable[int]) -> None:
        self._spi_rx_queue.extend(v & 0xFF for v in values)

    def _spi_transfer_cycles(self) -> int:
        spr = self.data[self.DATA_SPCR] & 0x03
        spi2x = (self.data[self.DATA_SPSR] >> self.SPSR_SPI2X_BIT) & 1
        div = {0: 4, 1: 16, 2: 64, 3: 128}[spr]
        if spi2x:
            div = max(1, div // 2)
        # Eight SCK periods of `div` CPU cycles plus one cycle before SPIF can be
        # read as set. Measured on a real ATmega2560 at f/2, f/4, f/8, f/16 and f/64.
        return 8 * div + 1

    def _start_spi_transfer(self, value: int) -> None:
        self._spi_transfer_value = value & 0xFF
        total = self._spi_transfer_cycles()
        self._spi_transfer_total_cycles = total
        self._spi_transfer_cycles_remaining = total
        self.data[self.DATA_SPDR] = value & 0xFF
        self.data[self.DATA_SPSR] &= ~(1 << self.SPSR_SPIF_BIT)

    def _advance_spi(self, cycles: int) -> None:
        if cycles <= 0 or self._spi_transfer_cycles_remaining <= 0:
            return
        self._spi_transfer_cycles_remaining = max(0, self._spi_transfer_cycles_remaining - cycles)
        if self._spi_transfer_cycles_remaining != 0:
            self._update_gpio_alt_overrides()
            return

        self.spi_transmitted_bytes.append(self._spi_transfer_value & 0xFF)
        received = self._spi_rx_queue.pop(0) if self._spi_rx_queue else 0xFF
        self.data[self.DATA_SPDR] = received & 0xFF
        self.data[self.DATA_SPSR] |= 1 << self.SPSR_SPIF_BIT
        self._spi_interrupt_pending = True
        self._update_gpio_alt_overrides()

    def _write_spcr(self, value: int) -> None:
        self.data[self.DATA_SPCR] = value & 0xFF
        if ((value >> self.SPCR_SPE_BIT) & 1) == 0:
            self._spi_transfer_cycles_remaining = 0
            self._spi_transfer_total_cycles = 0
            self._spi_interrupt_pending = False
            self.data[self.DATA_SPSR] &= ~((1 << self.SPSR_SPIF_BIT) | (1 << self.SPSR_WCOL_BIT))
        self._update_gpio_alt_overrides()

    def _write_spsr(self, value: int) -> None:
        current = self.data[self.DATA_SPSR]
        current = (current & ~1) | (value & 1)
        self.data[self.DATA_SPSR] = current & 0xFF
        self._update_gpio_alt_overrides()

    def _write_spdr(self, value: int) -> None:
        self.data[self.DATA_SPDR] = value & 0xFF
        spcr = self.data[self.DATA_SPCR]
        enabled = ((spcr >> self.SPCR_SPE_BIT) & 1) == 1
        master = ((spcr >> self.SPCR_MSTR_BIT) & 1) == 1
        if not enabled or not master:
            self._update_gpio_alt_overrides()
            return
        if self._spi_transfer_cycles_remaining > 0:
            self.data[self.DATA_SPSR] |= 1 << self.SPSR_WCOL_BIT
            return
        self.data[self.DATA_SPSR] &= ~(1 << self.SPSR_WCOL_BIT)
        self._start_spi_transfer(value)
        self._update_gpio_alt_overrides()

    # -----------------------------
    # TWI / I2C
    # -----------------------------

    def queue_twi_read_bytes(self, values: Iterable[int]) -> None:
        self._twi_read_queue.extend(v & 0xFF for v in values)

    def _twi_set_status(self, status: int) -> None:
        self.data[self.DATA_TWSR] = (status & 0xF8) | (self.data[self.DATA_TWSR] & 0x03)

    def set_twi_devices(self, addresses) -> None:
        """Set the 7-bit slave addresses that acknowledge (None: every address does)."""
        self.twi_devices = None if addresses is None else {a & 0x7F for a in addresses}

    def _twi_bit_cycles(self) -> int:
        prescale = 4 ** (self.data[self.DATA_TWSR] & 0x03)
        return 16 + 2 * self.data[self.DATA_TWBR] * prescale

    def _twi_operation_cycles(self, kind: str = "data") -> int:
        # Measured on a real ATmega2560 (TWBR 12 and 72): one SCL period plus 6
        # cycles for a START condition, nine periods plus 1 cycle for a byte and
        # its ACK bit.
        bit = self._twi_bit_cycles()
        return bit + 6 if kind == "start" else 9 * bit + 1

    def _twi_complete_start(self) -> None:
        repeated = self._twi_state != "idle"
        self._twi_state = "started"
        self.data[self.DATA_TWCR] &= ~(1 << self.TWCR_TWSTA_BIT)
        self._twi_set_status(self.TWI_STATUS_REP_START if repeated else self.TWI_STATUS_START)
        self._update_gpio_alt_overrides()

    def _twi_complete_address(self) -> None:
        value = self.data[self.DATA_TWDR] & 0xFF
        self._twi_last_address = (value >> 1) & 0x7F
        self._twi_rw = value & 1
        if self.twi_devices is not None and self._twi_last_address not in self.twi_devices:
            # Nobody answers: SLA+R / SLA+W transmitted, NACK received.
            self._twi_state = "nack"
            self._twi_set_status(0x48 if self._twi_rw else 0x20)
            self._update_gpio_alt_overrides()
            return
        if self._twi_rw:
            self._twi_state = "mr_addressed"
            self._twi_set_status(self.TWI_STATUS_MR_SLA_ACK)
        else:
            self._twi_state = "mt_addressed"
            self._twi_set_status(self.TWI_STATUS_MT_SLA_ACK)
        self._update_gpio_alt_overrides()

    def _twi_complete_write_data(self) -> None:
        self.twi_transmitted_bytes.append(self.data[self.DATA_TWDR] & 0xFF)
        self._twi_state = "mt_data"
        self._twi_set_status(self.TWI_STATUS_MT_DATA_ACK)
        self._update_gpio_alt_overrides()

    def _twi_complete_read_data(self) -> None:
        value = self._twi_read_queue.pop(0) if self._twi_read_queue else 0xFF
        self.data[self.DATA_TWDR] = value & 0xFF
        ack = ((self.data[self.DATA_TWCR] >> self.TWCR_TWEA_BIT) & 1) == 1
        self._twi_state = "mr_data"
        self._twi_set_status(self.TWI_STATUS_MR_DATA_ACK if ack else self.TWI_STATUS_MR_DATA_NACK)
        self._update_gpio_alt_overrides()

    def _twi_complete_operation(self) -> None:
        kind = self._twi_operation_kind
        self._twi_operation_kind = None
        if kind == "start":
            self._twi_complete_start()
        elif kind == "address":
            self._twi_complete_address()
        elif kind == "write_data":
            self._twi_complete_write_data()
        elif kind == "read_data":
            self._twi_complete_read_data()

        self.data[self.DATA_TWCR] |= 1 << self.TWCR_TWINT_BIT
        self._twi_interrupt_pending = True

    def _advance_twi(self, cycles: int) -> None:
        if cycles <= 0 or self._twi_operation_cycles_remaining <= 0:
            return
        self._twi_operation_cycles_remaining = max(0, self._twi_operation_cycles_remaining - cycles)
        if self._twi_operation_cycles_remaining == 0:
            self._twi_complete_operation()

    def _write_twsr(self, value: int) -> None:
        self.data[self.DATA_TWSR] = (self.data[self.DATA_TWSR] & 0xF8) | (value & 0x03)

    def _start_twi_operation(self, kind: str) -> None:
        self._twi_operation_kind = kind
        self._twi_operation_cycles_remaining = self._twi_operation_cycles(kind)
        self.data[self.DATA_TWCR] &= ~(1 << self.TWCR_TWINT_BIT)

    def _write_twcr(self, value: int) -> None:
        value &= 0xFF
        current = self.data[self.DATA_TWCR]
        writable_mask = (
            (1 << self.TWCR_TWIE_BIT)
            | (1 << self.TWCR_TWEN_BIT)
            | (1 << self.TWCR_TWSTO_BIT)
            | (1 << self.TWCR_TWSTA_BIT)
            | (1 << self.TWCR_TWEA_BIT)
            | (1 << self.TWCR_TWINT_BIT)
        )
        current = (current & ~writable_mask) | (value & writable_mask)
        self.data[self.DATA_TWCR] = current & 0xFF

        if ((current >> self.TWCR_TWEN_BIT) & 1) == 0:
            self._twi_operation_cycles_remaining = 0
            self._twi_operation_kind = None
            self._twi_interrupt_pending = False
            self._twi_state = "idle"
            self._twi_set_status(0xF8)
            self._update_gpio_alt_overrides()
            return

        if (value >> self.TWCR_TWSTO_BIT) & 1:
            self._twi_state = "idle"
            self.data[self.DATA_TWCR] &= ~(1 << self.TWCR_TWSTO_BIT)
            self._twi_operation_cycles_remaining = 0
            self._twi_operation_kind = None
            self._twi_set_status(0xF8)
            self._update_gpio_alt_overrides()
            return

        if ((value >> self.TWCR_TWINT_BIT) & 1) == 0:
            self._update_gpio_alt_overrides()
            return

        if (value >> self.TWCR_TWSTA_BIT) & 1:
            self._start_twi_operation("start")
            self._update_gpio_alt_overrides()
            return

        if self._twi_state == "started":
            self._start_twi_operation("address")
            self._update_gpio_alt_overrides()
            return

        if self._twi_state in ("mt_addressed", "mt_data"):
            self._start_twi_operation("write_data")
            self._update_gpio_alt_overrides()
            return

        if self._twi_state in ("mr_addressed", "mr_data"):
            self._start_twi_operation("read_data")
            self._update_gpio_alt_overrides()
            return

        self._update_gpio_alt_overrides()

    # -----------------------------
    # EEPROM
    # -----------------------------

    def _eeprom_addr(self) -> int:
        raw = self.data[self.DATA_EEARL] | ((self.data[self.DATA_EEARH] & 0x0F) << 8)
        return raw & self.EEPROM_ADDR_MASK

    def _write_eecr(self, value: int) -> None:
        value &= 0xFF
        current = self.data[self.DATA_EECR]
        mode_mask = (1 << self.EECR_EEPM0_BIT) | (1 << self.EECR_EEPM1_BIT)

        next_ctrl = current & ((1 << self.EECR_EEPE_BIT) | (1 << self.EECR_EEMPE_BIT))
        next_ctrl |= value & ((1 << self.EECR_EERIE_BIT) | mode_mask)

        write_busy = self._eeprom_write_cycles_remaining > 0
        if write_busy:
            # The programming mode can't be changed during a write.
            next_ctrl = (next_ctrl & ~mode_mask) | (current & mode_mask)

        if (value >> self.EECR_EEMPE_BIT) & 1 and not write_busy:
            next_ctrl |= 1 << self.EECR_EEMPE_BIT
            self._eeprom_eempe_window_cycles = self.EEPROM_EEMPE_WINDOW_CYCLES

        if (value >> self.EECR_EERE_BIT) & 1 and not write_busy:
            addr = self._eeprom_addr()
            self._profile_record_eeprom_read(addr)
            self.data[self.DATA_EEDR] = self.eeprom[addr]
            if self._step_pre is not None:
                self._step_halt_cycles += self.EEPROM_READ_HALT_CYCLES

        eempe_active = ((next_ctrl >> self.EECR_EEMPE_BIT) & 1) == 1 and self._eeprom_eempe_window_cycles > 0
        if (value >> self.EECR_EEPE_BIT) & 1 and eempe_active and not write_busy:
            mode = (next_ctrl >> self.EECR_EEPM0_BIT) & 0x03
            self._eeprom_write_addr = self._eeprom_addr()
            self._eeprom_write_value = self.data[self.DATA_EEDR] & 0xFF
            self._eeprom_write_mode = mode
            self._eeprom_write_cycles_remaining = self.EEPROM_WRITE_CYCLES if mode == 0 else self.EEPROM_HALF_WRITE_CYCLES
            next_ctrl |= 1 << self.EECR_EEPE_BIT
            next_ctrl &= ~(1 << self.EECR_EEMPE_BIT)
            self._eeprom_eempe_window_cycles = 0
            if self._step_pre is not None:
                self._step_halt_cycles += self.EEPROM_WRITE_HALT_CYCLES

        self.data[self.DATA_EECR] = next_ctrl & 0xFF

    def _advance_eeprom(self, cycles: int) -> None:
        if cycles <= 0:
            return

        if self._eeprom_eempe_window_cycles > 0:
            self._eeprom_eempe_window_cycles = max(0, self._eeprom_eempe_window_cycles - cycles)
            if self._eeprom_eempe_window_cycles == 0:
                self.data[self.DATA_EECR] &= ~(1 << self.EECR_EEMPE_BIT)

        if self._eeprom_write_cycles_remaining <= 0:
            return

        self._eeprom_write_cycles_remaining = max(0, self._eeprom_write_cycles_remaining - cycles)
        if self._eeprom_write_cycles_remaining == 0:
            self._profile_record_eeprom_write(self._eeprom_write_addr)
            # EEPM: 0 erase and write, 1 erase only, 2 write only (can only clear bits).
            mode = getattr(self, "_eeprom_write_mode", 0)
            if mode == 1:
                self.eeprom[self._eeprom_write_addr] = 0xFF
            elif mode == 2:
                self.eeprom[self._eeprom_write_addr] &= self._eeprom_write_value
            else:
                self.eeprom[self._eeprom_write_addr] = self._eeprom_write_value
            self.data[self.DATA_EECR] &= ~(1 << self.EECR_EEPE_BIT)
            self._eeprom_ready_interrupt_pending = True

    # -----------------------------
    # UART helpers
    # -----------------------------

    def get_uart(self, index: int) -> UARTBase:
        if not 0 <= index < len(self.uarts):
            raise ValueError(f"Unsupported UART index {index}")
        return self.uarts[index]

    def inject_uart_rx_byte(self, index: int, value: int) -> None:
        self.get_uart(index).inject_rx_byte(value, self.data)

    def inject_uart0_rx_byte(self, value: int) -> None:
        self.inject_uart_rx_byte(0, value)

    def _uart_vectors(self, index: int) -> tuple[int, int, int]:
        vector_map = {
            0: (self.VECTOR_USART0_RX, self.VECTOR_USART0_UDRE, self.VECTOR_USART0_TX),
            1: (self.VECTOR_USART1_RX, self.VECTOR_USART1_UDRE, self.VECTOR_USART1_TX),
            2: (self.VECTOR_USART2_RX, self.VECTOR_USART2_UDRE, self.VECTOR_USART2_TX),
            3: (self.VECTOR_USART3_RX, self.VECTOR_USART3_UDRE, self.VECTOR_USART3_TX),
        }
        return vector_map[index]

    def _find_uart_by_addr(self, addr: int) -> tuple[UARTBase | None, str | None]:
        for uart in self.uarts:
            if addr == uart.DATA_UDR:
                return uart, "udr"
            if addr == uart.DATA_UCSRA:
                return uart, "ucsra"
            if addr == uart.DATA_UCSRB:
                return uart, "ucsrb"
        return None, None

    # -----------------------------
    # Timer input-capture triggers
    # -----------------------------

    def trigger_timer1_capture(self, captured_value: int | None = None) -> None:
        """Latch a Timer1 capture value and set ICF1 flag.

        If ``captured_value`` is None, current TCNT1 is captured.
        """
        if captured_value is None:
            captured_value = self.data[Timer1.DATA_TCNT1L] | (self.data[Timer1.DATA_TCNT1H] << 8)
        captured_value &= 0xFFFF
        self.data[Timer1.DATA_ICR1L] = captured_value & 0xFF
        self.data[Timer1.DATA_ICR1H] = (captured_value >> 8) & 0xFF
        self.data[0x20 + Timer1.IO_TIFR1] |= 1 << Timer1.ICF1_BIT

    def trigger_timer3_capture(self, captured_value: int | None = None) -> None:
        """Latch a Timer3 capture value and set ICF3 flag.

        If ``captured_value`` is None, current TCNT3 is captured.
        """
        if captured_value is None:
            captured_value = self.data[Timer3.DATA_TCNT3L] | (self.data[Timer3.DATA_TCNT3H] << 8)
        captured_value &= 0xFFFF
        self.data[Timer3.DATA_ICR3L] = captured_value & 0xFF
        self.data[Timer3.DATA_ICR3H] = (captured_value >> 8) & 0xFF
        self.data[0x20 + Timer3.IO_TIFR3] |= 1 << Timer3.ICF3_BIT

    def trigger_timer4_capture(self, captured_value: int | None = None) -> None:
        """Latch a Timer4 capture value and set ICF4 flag."""
        if captured_value is None:
            captured_value = self.data[Timer4.DATA_TCNT4L] | (self.data[Timer4.DATA_TCNT4H] << 8)
        captured_value &= 0xFFFF
        self.data[Timer4.DATA_ICR4L] = captured_value & 0xFF
        self.data[Timer4.DATA_ICR4H] = (captured_value >> 8) & 0xFF
        self.data[0x20 + Timer4.IO_TIFR4] |= 1 << Timer4.ICF4_BIT

    def trigger_timer5_capture(self, captured_value: int | None = None) -> None:
        """Latch a Timer5 capture value and set ICF5 flag."""
        if captured_value is None:
            captured_value = self.data[Timer5.DATA_TCNT5L] | (self.data[Timer5.DATA_TCNT5H] << 8)
        captured_value &= 0xFFFF
        self.data[Timer5.DATA_ICR5L] = captured_value & 0xFF
        self.data[Timer5.DATA_ICR5H] = (captured_value >> 8) & 0xFF
        self.data[0x20 + Timer5.IO_TIFR5] |= 1 << Timer5.ICF5_BIT
