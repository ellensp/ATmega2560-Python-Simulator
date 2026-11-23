"""ATmega2560 emulator — GPIO, PCINT, and external interrupt mixin."""


class _GpioMixin:
    # -----------------------------
    # External interrupt helpers
    # -----------------------------

    def _ext_int_isc(self, index: int) -> int:
        if 0 <= index <= 3:
            return (self.data[self.DATA_EICRA] >> (2 * index)) & 0x3
        if 4 <= index <= 7:
            return (self.data[self.DATA_EICRB] >> (2 * (index - 4))) & 0x3
        raise ValueError(f"External interrupt index out of range: {index}")

    def _ext_int_vector(self, index: int) -> int:
        vectors = [
            self.VECTOR_INT0,
            self.VECTOR_INT1,
            self.VECTOR_INT2,
            self.VECTOR_INT3,
            self.VECTOR_INT4,
            self.VECTOR_INT5,
            self.VECTOR_INT6,
            self.VECTOR_INT7,
        ]
        return vectors[index]

    # -----------------------------
    # GPIO port helpers
    # -----------------------------

    def _read_port_level(self, pin_addr: int, ddr_addr: int, port_addr: int) -> int:
        ddr = self.data[ddr_addr]
        port = self.data[port_addr]
        driven_mask = self._gpio_input_driven[pin_addr] & 0xFF
        driven_levels = self._gpio_input_levels[pin_addr] & driven_mask
        floating_mask = (~driven_mask) & 0xFF
        input_pullups = port & (~ddr & 0xFF)
        input_levels = driven_levels | (input_pullups & floating_mask)
        # A connected compare output replaces PORTx on a pin configured as an output.
        oc_mask = self._oc_mask[pin_addr]
        if oc_mask:
            port = (port & ~oc_mask) | (self._oc_value[pin_addr] & oc_mask)
        value = ((port & ddr) | (input_levels & (~ddr & 0xFF))) & 0xFF
        override_mask = self._gpio_output_override_masks[pin_addr] & 0xFF
        override_value = self._gpio_output_override_values[pin_addr] & 0xFF
        return ((value & (~override_mask & 0xFF)) | (override_value & override_mask)) & 0xFF

    def _read_port_by_pin_addr(self, pin_addr: int) -> int | None:
        pair = self.GPIO_PIN_ADDRS.get(pin_addr)
        if pair is None:
            return None
        ddr_addr, port_addr = pair
        return self._read_port_level(pin_addr, ddr_addr, port_addr)

    def _resolve_gpio_pin_addr(self, port: str) -> int:
        key = port.upper()
        if key not in self.GPIO_PORTS:
            raise ValueError(f"Unknown port '{port}'")
        pin_addr, _, _ = self.GPIO_PORTS[key]
        return pin_addr

    def _set_gpio_output_override(self, port: str, bit: int, level: int) -> None:
        pin_addr = self._resolve_gpio_pin_addr(port)
        mask = 1 << bit
        self._gpio_output_override_masks[pin_addr] |= mask
        if level:
            self._gpio_output_override_values[pin_addr] |= mask
        else:
            self._gpio_output_override_values[pin_addr] &= ~mask & 0xFF

    # -----------------------------
    # GPIO alternate-function override (UART TX, SPI, TWI pin states)
    # -----------------------------

    def _compute_gpio_alt_signature(self) -> tuple[int, ...]:
        sig: list[int] = []
        for uart in self.uarts:
            sig.append(self.data[uart.DATA_UCSRB])
            sig.append(1 if uart.is_transmitting() else 0)
        sig.extend(
            [
                self.data[self.DATA_SPCR],
                self.data[self.DATA_SPDR],
                self._spi_transfer_cycles_remaining,
                self._spi_transfer_total_cycles,
                self._spi_transfer_value,
                self.data[self.DATA_TWCR],
                self._twi_operation_cycles_remaining,
                0 if self._twi_operation_kind is None else (1 if self._twi_operation_kind == "start" else 2),
                1 if self._twi_state == "started" else 0,
            ]
        )
        return tuple(sig)

    def _update_gpio_alt_overrides(self) -> None:
        signature = self._compute_gpio_alt_signature()
        if self._gpio_alt_signature == signature:
            return

        prev_pcint_overrides = tuple(
            (
                self._gpio_output_override_masks[pin_addr] & 0xFF,
                self._gpio_output_override_values[pin_addr] & 0xFF,
            )
            for pin_addr in self.PCINT_GROUP_PIN_ADDRS
        )

        for pin_addr in self._gpio_output_override_masks:
            self._gpio_output_override_masks[pin_addr] = 0
            self._gpio_output_override_values[pin_addr] = 0

        for index, uart in enumerate(self.uarts):
            if ((self.data[uart.DATA_UCSRB] >> uart.TXEN_BIT) & 1) == 1:
                port, bit = self.UART_TX_PINS[index]
                # TX pin is idle-high; goes low (start-bit phase) while a byte is pending.
                tx_level = 0 if uart.is_transmitting() else 1
                self._set_gpio_output_override(port, bit, tx_level)

        spcr = self.data[self.DATA_SPCR]
        if ((spcr >> self.SPCR_SPE_BIT) & 1) and ((spcr >> self.SPCR_MSTR_BIT) & 1):
            cpol = (spcr >> self.SPCR_CPOL_BIT) & 1
            dord = (spcr >> self.SPCR_DORD_BIT) & 1
            if self._spi_transfer_cycles_remaining > 0 and self._spi_transfer_total_cycles > 0:
                elapsed = self._spi_transfer_total_cycles - self._spi_transfer_cycles_remaining
                bit_idx = min(7, (elapsed * 8) // self._spi_transfer_total_cycles)
                if dord:
                    mosi_bit = (self._spi_transfer_value >> bit_idx) & 1
                else:
                    mosi_bit = (self._spi_transfer_value >> (7 - bit_idx)) & 1
                sck_val = 1 - cpol
            else:
                mosi_bit = (self.data[self.DATA_SPDR] & 1) if dord else ((self.data[self.DATA_SPDR] >> 7) & 1)
                sck_val = cpol
            port, bit = self.SPI_PIN_SCK
            self._set_gpio_output_override(port, bit, sck_val)
            port, bit = self.SPI_PIN_MOSI
            self._set_gpio_output_override(port, bit, mosi_bit)

        twen = ((self.data[self.DATA_TWCR] >> self.TWCR_TWEN_BIT) & 1) == 1
        if twen:
            port, bit = self.TWI_PIN_SCL
            scl_val = 0 if self._twi_operation_cycles_remaining > 0 else 1
            self._set_gpio_output_override(port, bit, scl_val)
            if self._twi_operation_kind == "start" or self._twi_state == "started":
                port, bit = self.TWI_PIN_SDA
                self._set_gpio_output_override(port, bit, 0)

        new_pcint_overrides = tuple(
            (
                self._gpio_output_override_masks[pin_addr] & 0xFF,
                self._gpio_output_override_values[pin_addr] & 0xFF,
            )
            for pin_addr in self.PCINT_GROUP_PIN_ADDRS
        )
        if new_pcint_overrides != prev_pcint_overrides:
            self._pcint_dirty = True
        self._extint_dirty = True

        self._gpio_alt_signature = signature

    # -----------------------------
    # PCINT helpers
    # -----------------------------

    def _pcint_group_level(self, group: int) -> int:
        if group == 0:
            return self._read_port_by_pin_addr(0x23) or 0
        if group == 1:
            # PCINT8 is PE0, PCINT9..15 are PJ0..PJ6.
            pe = self._read_port_by_pin_addr(0x2C) or 0
            pj = self._read_port_by_pin_addr(0x103) or 0
            return (pe & 0x01) | ((pj & 0x7F) << 1)
        if group == 2:
            return self._read_port_by_pin_addr(0x106) or 0
        return 0

    def _update_pcint_flags(self) -> None:
        if not self._pcint_dirty:
            return

        masks = {
            0: self.data[self.DATA_PCMSK0],
            1: self.data[self.DATA_PCMSK1],
            2: self.data[self.DATA_PCMSK2],
        }
        pcifr_addr = 0x20 + self.IO_PCIFR
        for group in (0, 1, 2):
            current = self._pcint_group_level(group)
            changed = (current ^ self._pcint_last_levels[group]) & masks[group]
            if changed:
                self.data[pcifr_addr] |= 1 << group
            self._pcint_last_levels[group] = current
        self._pcint_dirty = False

    # -----------------------------
    # Public pin-level API
    # -----------------------------

    def set_int0_pin(self, level: int) -> None:
        """Drive INT0 pin level and update EIFR flag based on EICRA mode."""
        self.set_ext_int_pin(0, level)

    def set_ext_int_pin(self, index: int, level: int) -> None:
        """Drive the INTx pin (PD0-3 for INT0-3, PE4-7 for INT4-7)."""
        if index < 0 or index > 7:
            raise ValueError("External interrupt index must be in range 0..7")
        self.set_pin_level("D" if index < 4 else "E", index, level)

    def _update_ext_int_flags(self) -> None:
        """Follow the INT0-7 pins: latch EIFR on the configured edge, and track the
        pins that request a low-level interrupt (those have no flag)."""
        if not self._extint_dirty:
            return
        self._extint_dirty = False
        pd = self._read_port_by_pin_addr(0x29) or 0
        pe = self._read_port_by_pin_addr(0x2C) or 0
        level_mask = 0
        for index in range(8):
            level = ((pd if index < 4 else pe) >> index) & 1
            old = self._ext_int_levels[index]
            isc = self._ext_int_isc(index)
            if isc == 0b00:
                if level == 0:
                    level_mask |= 1 << index
            elif (isc == 0b01 and old != level) or (isc == 0b10 and old == 1 and level == 0) or (isc == 0b11 and old == 0 and level == 1):
                self.data[0x20 + self.IO_EIFR] |= 1 << index
            self._ext_int_levels[index] = level
        self._ext_level_mask = level_mask

        # Timer external clock inputs (T0, T1, T3, T4, T5): one count per selected edge.
        for n, (pin_addr, bit) in self.TIMER_CLOCK_PINS.items():
            level = ((self._read_port_by_pin_addr(pin_addr) or 0) >> bit) & 1
            if level != self._timer_pin_levels[n]:
                self._timer_pin_levels[n] = level
                (self.timer0 if n == 0 else self._timers16[n]).external_edge(bool(level), self.data, self.cycles)

    def set_pin_level(self, port: str, bit: int, level: int) -> None:
        """Drive a simulated external logic level onto a GPIO input pin."""
        if bit < 0 or bit > 7:
            raise ValueError("bit must be in range 0..7")

        pin_addr = self._resolve_gpio_pin_addr(port)
        mask = 1 << bit
        self._gpio_input_driven[pin_addr] |= mask
        if level:
            self._gpio_input_levels[pin_addr] |= mask
            self.data[pin_addr] |= mask
        else:
            self._gpio_input_levels[pin_addr] &= ~mask & 0xFF
            self.data[pin_addr] &= ~mask & 0xFF
        if pin_addr in self.PCINT_GROUP_PIN_ADDRS:
            self._pcint_dirty = True
        if pin_addr in (0x29, 0x2C, 0x100, 0x109):
            self._extint_dirty = True
            self._update_ext_int_flags()

    def release_pin_level(self, port: str, bit: int) -> None:
        """Release a simulated GPIO input pin back to high-impedance/floating state."""
        if bit < 0 or bit > 7:
            raise ValueError("bit must be in range 0..7")

        pin_addr = self._resolve_gpio_pin_addr(port)
        mask = 1 << bit
        self._gpio_input_driven[pin_addr] &= ~mask & 0xFF
        self._gpio_input_levels[pin_addr] &= ~mask & 0xFF
        self.data[pin_addr] &= ~mask & 0xFF
        if pin_addr in self.PCINT_GROUP_PIN_ADDRS:
            self._pcint_dirty = True
        if pin_addr in (0x29, 0x2C, 0x100, 0x109):
            self._extint_dirty = True
            self._update_ext_int_flags()
