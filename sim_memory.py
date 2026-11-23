"""ATmega2560 emulator — data memory, I/O, stack, and program-load mixin."""

from typing import Iterable, List

from hex_loader import load_hex_bytes
from sim_peripherals import Timer0, Timer1, Timer2, Timer3, Timer4, Timer5, WatchdogTimer


class _MemoryMixin:
    # -----------------------------
    # Data-memory validation
    # -----------------------------

    @staticmethod
    def _is_valid_data_addr(addr: int) -> bool:
        # Register file + I/O + ext I/O + internal SRAM (0x0000–0x21FF).
        return 0 <= addr <= 0x21FF

    # -----------------------------
    # Data-space read / write
    # -----------------------------

    def _data_read(self, addr: int, pre: int = 1) -> int:
        """Read data space. `pre` is how many cycles into the current instruction
        an I/O register is sampled: the start of the last cycle (1 for the
        2-cycle LD/LDD/LDS, 0 for IN)."""
        addr &= 0xFFFF
        if not self._is_valid_data_addr(addr):
            return 0
        self._profile_record_ram_read(addr)

        if addr >= self.DATA_SRAM_START:
            return self.data[addr]
        if addr < 0x20:
            return self.reg[addr]
        if self._step_pre is not None:
            self._step_sync(pre)

        pin_level = self._read_port_by_pin_addr(addr)
        if pin_level is not None:
            # The input synchroniser: a read sees the pin one cycle late, so an OUT to
            # PORTx needs a NOP before IN PINx returns the new level (measured).
            if self._step_pre is not None and self.cycles - self._pin_change_at[addr] < 1:
                return self._pin_prev[addr]
            return pin_level

        if addr == self.DATA_SPL:
            return self.sp & 0xFF

        if addr == self.DATA_SPH:
            return (self.sp >> 8) & 0xFF

        if addr == self.DATA_SREG:
            return self.sreg & 0xFF

        if addr == self.DATA_ADCL:
            # Reading ADCL locks the result registers until ADCH is read.
            self._adc_locked = True
            return self.data[addr]
        if addr == self.DATA_ADCH:
            self._adc_locked = False
            return self.data[addr]

        if 0x84 <= addr <= 0x12D:
            # 16-bit timer registers share a TEMP high byte per timer: reading
            # TCNTnL/ICRnL latches the high byte, which TCNTnH/ICRnH then return.
            latch = self._t16_low_read.get(addr)
            if latch is not None:
                self._t16_temp[latch[0]] = self.data[latch[1]]
                return self.data[addr]
            timer = self._t16_high_read.get(addr)
            if timer is not None:
                return self._t16_temp[timer]

        if addr == self.DATA_SPDR:
            value = self.data[addr]
            self.data[self.DATA_SPSR] &= ~(1 << self.SPSR_SPIF_BIT)
            self._spi_interrupt_pending = False
            self._update_gpio_alt_overrides()
            return value

        uart, register_name = self._find_uart_by_addr(addr)
        if uart is not None and register_name == "udr":
            return uart.read_udr(self.data)

        return self.data[addr]

    def _read_pin_io_level(self, io_addr: int) -> int | None:
        return self._read_port_by_pin_addr(0x20 + io_addr)

    def _data_write(self, addr: int, value: int, pre: int = 2) -> None:
        """Write data space. An I/O register write takes effect at the end of the
        instruction: `pre` is the instruction's length in cycles (2 for
        ST/STD/STS/SBI/CBI, 1 for OUT)."""
        addr &= 0xFFFF
        value &= 0xFF

        if not self._is_valid_data_addr(addr):
            return
        self._profile_record_ram_write(addr)

        if addr >= self.DATA_SRAM_START:
            self.data[addr] = value
            return
        if addr < 0x20:
            self.reg[addr] = value
            return
        if self._step_pre is not None:
            self._step_sync_write(pre)

        if addr == self.DATA_SREG:
            self.sreg = value
            return

        if addr == self.DATA_GTCCR:
            # PSRSYNC resets the prescaler of Timer0/1/3/4/5 and reads back as 0;
            # with TSM set the prescaler is held in reset until TSM is cleared.
            tsm = value & 0x80
            if value & 0x01:
                self._prescaler = 0
            self._prescaler_hold = bool(tsm and (value & 0x01))
            self.data[addr] = (value & 0x83) if tsm else 0
            return

        foc = self.FOC_REGS.get(addr)
        if foc is not None:
            # FOCnx strobes read as zero and force the compare action of their channel.
            n, top_bit = foc
            timer = self._timers[n]
            for channel in range(timer.CHANNELS):
                if (value >> (top_bit - channel)) & 1:
                    timer.force_compare(channel, self.data, self.cycles)
            value &= ~(((1 << timer.CHANNELS) - 1) << (top_bit + 1 - timer.CHANNELS)) & 0xFF

        timer = self._timer_by_tccr.get(addr)
        if timer is not None:
            self.data[addr] = value
            timer.mode_written(self.data)
            self._oc_changed(timer, self.cycles)  # outputs may connect or disconnect
            return
        if foc is not None:
            self.data[addr] = value
            return

        pin_reg = self._gpio_reg_to_pin.get(addr)
        if pin_reg is not None and self._step_pre is not None:
            self._pin_snapshot(pin_reg, self.cycles)

        if addr == 0x46:
            self.timer0._compare_block = True
        elif addr == 0xB2:
            self.timer2._compare_block = True

        if addr in self.EXTINT_RELEVANT_DATA_ADDRS:
            self._extint_dirty = True

        if 0x84 <= addr <= 0x12D:
            # 16-bit timer registers: the high byte goes to the timer's TEMP
            # register and reaches the register when the low byte is written.
            timer = self._t16_high_write.get(addr)
            if timer is not None:
                self._t16_temp[timer] = value
                return
            latch = self._t16_low_write.get(addr)
            if latch is not None:
                self.data[latch[1]] = self._t16_temp[latch[0]]
                self.data[addr] = value
                if addr in self._t16_low_read and (addr & 0x0F) == 0x04:  # TCNTnL
                    self._timers16[latch[0]]._compare_block = True
                return

        if addr == (0x20 + Timer0.IO_TIFR0):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + Timer1.IO_TIFR1):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + Timer2.IO_TIFR2):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + Timer3.IO_TIFR3):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + Timer4.IO_TIFR4):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + Timer5.IO_TIFR5):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + self.IO_PCIFR):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == (0x20 + self.IO_EIFR):
            self.data[addr] = self.data[addr] & (~value & 0xFF)
            return

        if addr == WatchdogTimer.DATA_WDTCSR:
            self.watchdog.write_wdtcsr(value, self.data)
            return

        if addr == self.DATA_SPL:
            self.sp = (self.sp & 0xFF00) | value
            return

        if addr == self.DATA_SPH:
            self.sp = (self.sp & 0x00FF) | (value << 8)
            return

        if addr == self.DATA_EEARL:
            self.data[addr] = value
            return

        if addr == self.DATA_EEARH:
            self.data[addr] = value & 0x0F
            return

        if addr == self.DATA_EEDR:
            self.data[addr] = value
            return

        if addr == self.DATA_SPCR:
            self._write_spcr(value)
            return

        if addr == self.DATA_SPSR:
            self._write_spsr(value)
            return

        if addr == self.DATA_SPDR:
            self._write_spdr(value)
            return

        if addr == self.DATA_ADCL or addr == self.DATA_ADCH:
            return  # read-only

        if addr == self.DATA_ACSR:
            self._write_acsr(value)
            return

        if addr == self.DATA_TWBR:
            self.data[addr] = value
            return

        if addr == self.DATA_TWSR:
            self._write_twsr(value)
            return

        if addr == self.DATA_TWAR:
            self.data[addr] = value & 0xFE
            return

        if addr == self.DATA_TWDR:
            self.data[addr] = value
            return

        if addr == self.DATA_TWCR:
            self._write_twcr(value)
            return

        if addr == self.DATA_TWAMR:
            self.data[addr] = value & 0xFE
            return

        if addr == self.DATA_ADMUX:
            self.data[addr] = value
            return

        if addr == self.DATA_ADCSRB:
            self.data[addr] = value
            return

        if addr == self.DATA_ADCSRA:
            self._write_adcsra(value)
            return

        gpio_pair = self.GPIO_PIN_ADDRS.get(addr)
        if gpio_pair is not None:
            _, port_addr = gpio_pair
            self.data[port_addr] ^= value
            if addr in self.PCINT_GROUP_PIN_ADDRS:
                self._pcint_dirty = True
            return

        if uart_ubrr := self._uart_by_ubrrl.get(addr):
            self.data[addr] = value
            uart_ubrr.restart_baud_generator()
            return

        if addr == self.DATA_EECR:
            self._write_eecr(value)
            return

        uart, register_name = self._find_uart_by_addr(addr)
        if uart is not None and register_name == "ucsra":
            txc_mask = 1 << uart.TXC_BIT
            if value & txc_mask:
                self.data[addr] &= ~txc_mask
            # U2Xn and MPCMn are the only other writable bits.
            self.data[addr] = (self.data[addr] & ~0x03) | (value & 0x03)
            self._update_gpio_alt_overrides()
            return

        if uart is not None and register_name == "ucsrb":
            self.data[addr] = value
            self._update_gpio_alt_overrides()
            return

        if uart is not None and register_name == "udr":
            uart.write_udr(value, self.data)
            self._update_gpio_alt_overrides()
            return

        self.data[addr] = value
        if addr == 0x25 and (self._oc_mask[0x23] & 0x80):
            self._oc_changed(self.timer0, self.cycles)
        if addr in self.PCINT_RELEVANT_DATA_ADDRS:
            self._pcint_dirty = True

    # -----------------------------
    # Stack helpers
    # -----------------------------

    def _push_byte(self, value: int) -> None:
        # AVR push uses post-decrement stack semantics.
        self.data[self.sp] = value & 0xFF
        self.sp = self._clamp_u16(self.sp - 1)

    def _pop_byte(self) -> int:
        # AVR pop uses pre-increment stack semantics.
        self.sp = self._clamp_u16(self.sp + 1)
        value = self.data[self.sp]
        return value

    def _push_return_address(self, addr_word: int) -> None:
        # Devices with >64K words of flash (including ATmega2560) use 3-byte
        # PC stack entries for CALL/RCALL/ICALL/EICALL and interrupt entry.
        stack_bytes = 3 if self.PC_WORD_MASK > 0xFFFF else 2
        for shift in range(0, stack_bytes * 8, 8):
            self._push_byte((addr_word >> shift) & 0xFF)

    def _pop_return_address(self) -> int:
        stack_bytes = 3 if self.PC_WORD_MASK > 0xFFFF else 2
        addr = 0
        for shift in range((stack_bytes - 1) * 8, -1, -8):
            addr |= (self._pop_byte() & 0xFF) << shift
        # Hardware ignores address bits above the device's program counter width.
        return addr & self.PC_WORD_MASK

    # -----------------------------
    # Pointer-register helpers (X, Y, Z)
    # -----------------------------

    def _get_ptr(self, name: str) -> int:
        if name == "X":
            return self.reg[26] | (self.reg[27] << 8)
        if name == "Y":
            return self.reg[28] | (self.reg[29] << 8)
        if name == "Z":
            return self.reg[30] | (self.reg[31] << 8)
        raise ValueError(f"Unknown pointer register '{name}'")

    def _set_ptr(self, name: str, value: int) -> None:
        value &= 0xFFFF
        lo = value & 0xFF
        hi = (value >> 8) & 0xFF
        if name == "X":
            self.reg[26] = lo
            self.reg[27] = hi
            return
        if name == "Y":
            self.reg[28] = lo
            self.reg[29] = hi
            return
        if name == "Z":
            self.reg[30] = lo
            self.reg[31] = hi
            return
        raise ValueError(f"Unknown pointer register '{name}'")

    # -----------------------------
    # I/O space read / write
    # -----------------------------

    def _io_read(self, io_addr: int, pre: int = 0) -> int:
        io_addr &= 0x3F
        if io_addr == 0x3F:
            return self.sreg & 0xFF
        if io_addr == 0x3D:
            return self.sp & 0xFF
        if io_addr == 0x3E:
            return (self.sp >> 8) & 0xFF

        return self._data_read(0x20 + io_addr, pre)

    def _build_io_name_map(self) -> dict[int, str]:
        io_map: dict[int, str] = {}

        for name, value in vars(self.__class__).items():
            if not isinstance(value, int):
                continue

            if name.startswith("IO_") and 0 <= value <= 0x3F:
                io_map[value] = name[3:]

            if name.startswith("DATA_") and 0x20 <= value <= 0x5F:
                io_map[value - 0x20] = name[5:]

        for port, (pin_addr, ddr_addr, port_addr) in self.GPIO_PORTS.items():
            if 0x20 <= pin_addr <= 0x5F:
                io_map[pin_addr - 0x20] = f"PIN{port}"
            if 0x20 <= ddr_addr <= 0x5F:
                io_map[ddr_addr - 0x20] = f"DDR{port}"
            if 0x20 <= port_addr <= 0x5F:
                io_map[port_addr - 0x20] = f"PORT{port}"

        for io_addr, reg_name in self.IO_NAME_OVERRIDES.items():
            io_map[io_addr & 0x3F] = reg_name

        return io_map

    def _format_io_operand(self, io_addr: int) -> str:
        io_addr &= 0x3F
        name = self._io_name_map.get(io_addr)
        if name is not None:
            return name
        return f"0x{io_addr:02X}"

    def _io_write(self, io_addr: int, value: int, pre: int = 1) -> None:
        io_addr &= 0x3F
        value &= 0xFF
        if io_addr == 0x3F:
            self.sreg = value
            return
        if io_addr == 0x3D:
            self.sp = (self.sp & 0xFF00) | value
            return
        if io_addr == 0x3E:
            self.sp = (self.sp & 0x00FF) | (value << 8)
            return
        self._data_write(0x20 + io_addr, value, pre)

    # -----------------------------
    # Program loading
    # -----------------------------

    def load_program_words(self, words: Iterable[int]) -> None:
        self.program = [w & 0xFFFF for w in words]
        self.pc = 0
        self.halted = False
        self._resize_flash_profile_counters()

    def load_program_bytes(self, image: bytes) -> None:
        if len(image) % 2 != 0:
            raise ValueError("Program image length must be even (16-bit words).")

        words: List[int] = []
        for i in range(0, len(image), 2):
            # AVR flash words are little-endian in byte streams.
            words.append(image[i] | (image[i + 1] << 8))

        self.load_program_words(words)

    def load_program_hex(self, path: str) -> None:
        image = load_hex_bytes(path)
        # HEX files are often sparse; model full ATmega2560 flash so legal jumps
        # into otherwise-unmentioned regions do not immediately halt as out-of-range.
        if len(image) < self.FLASH_SIZE_BYTES:
            image = image + (b"\xFF" * (self.FLASH_SIZE_BYTES - len(image)))
        elif len(image) > self.FLASH_SIZE_BYTES:
            image = image[: self.FLASH_SIZE_BYTES]
        self.load_program_bytes(image)

    def load_program_file(self, path: str) -> None:
        lower = path.lower()
        if lower.endswith(".hex") or lower.endswith(".hx"):
            self.load_program_hex(path)
            return
        if lower.endswith(".bin"):
            with open(path, "rb") as f:
                self.load_program_bytes(f.read())
            return
        raise ValueError("Unsupported file type. Use .hex/.hx or .bin")

    # -----------------------------
    # State snapshot
    # -----------------------------

    def snapshot_state(self) -> dict[str, object]:
        flags = {
            "C": self._get_flag(self.FLAG_C),
            "Z": self._get_flag(self.FLAG_Z),
            "N": self._get_flag(self.FLAG_N),
            "V": self._get_flag(self.FLAG_V),
            "S": self._get_flag(self.FLAG_S),
            "H": self._get_flag(self.FLAG_H),
            "T": self._get_flag(self.FLAG_T),
            "I": self._get_flag(self.FLAG_I),
        }
        return {
            "pc": self.pc,
            "sp": self.sp,
            "cycles": self.cycles,
            "total_cycles": self.total_cycles,
            "reset_count": self.reset_count,
            "watchdog_reset_count": self.watchdog_reset_count,
            "sreg": self.sreg,
            "flags": flags,
            "halted": self.halted,
            "regs": self.reg[:],
        }
