from dataclasses import dataclass
from typing import Iterable, List, Optional

from avr_encoding import add, brbs, cpi, ldi, rjmp
from hex_loader import load_hex_bytes
from sim_peripherals import Timer0, Timer1, Timer2, Timer3, Timer4, Timer5, UART0, UART1, UART2, UART3, UARTBase, WatchdogTimer

from sim_constants import _EmulatorConstants
from sim_alu import _AluMixin
from sim_decode import _DecodeMixin, DisassemblyLine
from sim_gpio import _GpioMixin
from sim_memory import _MemoryMixin
from sim_interrupts import _InterruptsMixin
from sim_peripherals_ctrl import _PeripheralsCtrlMixin


@dataclass
class StepResult:
    pc_before: int
    opcode: int
    cycles: int
    description: str


# Re-exported for backward compatibility.
__all__ = ["ATmega2560Emulator", "StepResult", "DisassemblyLine"]


class ATmega2560Emulator(
    _EmulatorConstants,
    _AluMixin,
    _DecodeMixin,
    _GpioMixin,
    _MemoryMixin,
    _InterruptsMixin,
    _PeripheralsCtrlMixin,
):
    """ATmega2560 emulator core, built in stages toward full coverage.

    Notes:
    - Program memory is stored as 16-bit words (word-addressed PC).
    - Data memory is a flat 64 KiB map. This keeps the model simple while
      allowing future expansion of SRAM + I/O + external memory mapping.
        - The current implementation includes a focused instruction subset.
        - The intended end state is full instruction-set coverage plus device
            behavior needed for realistic firmware execution.
    """

    def __init__(self) -> None:
        self.reg: List[int] = [0] * 32
        self.sreg: int = 0
        self.pc: int = 0  # Word-addressed program counter
        self.cycles: int = 0
        self.total_cycles: int = 0
        self.reset_count: int = 0
        self.watchdog_reset_count: int = 0

        # Keep RAM model simple for now.
        self.data: bytearray = bytearray(65536)

        # Stack pointer starts at top of internal SRAM (ATmega2560 SRAM end 0x21FF).
        self.sp: int = 0x21FF

        self.program: List[int] = []
        self.halted: bool = False
        self.halt_reason: Optional[str] = None
        self.eeprom: bytearray = bytearray(self.EEPROM_SIZE)
        self.profile_ram_reads: list[int] = []
        self.profile_ram_writes: list[int] = []
        self.profile_flash_reads: list[int] = []
        self.profile_flash_writes: list[int] = []
        self.profile_eeprom_reads: list[int] = []
        self.profile_eeprom_writes: list[int] = []
        self.timer0 = Timer0()
        self.timer1 = Timer1()
        self.timer2 = Timer2()
        self.timer3 = Timer3()
        self.timer4 = Timer4()
        self.timer5 = Timer5()
        self.uart0 = UART0()
        self.uart1 = UART1()
        self.uart2 = UART2()
        self.uart3 = UART3()
        self.uarts: List[UARTBase] = [self.uart0, self.uart1, self.uart2, self.uart3]
        self.watchdog = WatchdogTimer()
        self._ext_int_levels: List[int] = [1] * 8
        self._eeprom_write_cycles_remaining = 0
        self._eeprom_write_addr = 0
        self._eeprom_write_value = 0
        self._eeprom_eempe_window_cycles = 0
        self._eeprom_ready_interrupt_pending = False
        self._pcint_last_levels: dict[int, int] = {0: 0, 1: 0, 2: 0}
        self._adc_channel_values: List[int] = [0] * 16
        self._adc_conversion_cycles_remaining = 0
        self._adc_conversion_channel = 0
        self._adc_interrupt_pending = False
        self._analog_comp_positive_input = 0
        self._analog_comp_negative_input = 0
        self._analog_comp_output = 0
        self._analog_comp_interrupt_pending = False
        self._spi_transfer_cycles_remaining = 0
        self._spi_transfer_total_cycles = 0
        self._spi_transfer_value = 0
        self._spi_interrupt_pending = False
        self._spi_rx_queue: List[int] = []
        self.spi_transmitted_bytes: List[int] = []
        self._twi_operation_cycles_remaining = 0
        self._twi_operation_kind: str | None = None
        self._twi_interrupt_pending = False
        self._twi_read_queue: List[int] = []
        self.twi_transmitted_bytes: List[int] = []
        self._twi_state = "idle"
        self._twi_last_address = 0
        self._twi_rw = 0
        self._gpio_input_levels: dict[int, int] = {pin_addr: 0 for pin_addr, _, _ in self.GPIO_PORTS.values()}
        self._gpio_input_driven: dict[int, int] = {pin_addr: 0 for pin_addr, _, _ in self.GPIO_PORTS.values()}
        self._gpio_output_override_values: dict[int, int] = {pin_addr: 0 for pin_addr, _, _ in self.GPIO_PORTS.values()}
        self._gpio_output_override_masks: dict[int, int] = {pin_addr: 0 for pin_addr, _, _ in self.GPIO_PORTS.values()}
        self._gpio_alt_signature: tuple[int, ...] | None = None
        self._pcint_dirty = True
        self._interrupt_inhibit_once = False
        self._io_name_map = self._build_io_name_map()
        self._reset_runtime_state(watchdog_reset=False, count_reset=False)

    # -----------------------------
    # Program loading / reset
    # -----------------------------
    def _reset_runtime_state(self, watchdog_reset: bool = False, count_reset: bool = True) -> None:
        if count_reset:
            self.reset_count += 1
            if watchdog_reset:
                self.watchdog_reset_count += 1
        self.reg = [0] * 32
        self.sreg = 0
        self.pc = 0
        self.cycles = 0
        self.data[:] = b"\x00" * len(self.data)
        self.sp = 0x21FF
        self.halted = False
        self.halt_reason = None
        self.timer0.reset()
        self.timer1.reset()
        self.timer2.reset()
        self.timer3.reset()
        self.timer4.reset()
        self.timer5.reset()
        for uart in self.uarts:
            uart.reset(self.data)
        self.watchdog.reset(self.data, watchdog_reset=watchdog_reset)
        self._eeprom_write_cycles_remaining = 0
        self._eeprom_write_addr = 0
        self._eeprom_write_value = 0
        self._eeprom_eempe_window_cycles = 0
        self._eeprom_ready_interrupt_pending = False
        self._pcint_last_levels = {
            0: self._pcint_group_level(0),
            1: self._pcint_group_level(1),
            2: self._pcint_group_level(2),
        }
        self._pcint_dirty = True
        self._interrupt_inhibit_once = False
        self._adc_conversion_cycles_remaining = 0
        self._adc_conversion_channel = 0
        self._adc_interrupt_pending = False
        self.data[self.DATA_ADCSRA] = 0
        self.data[self.DATA_ADCSRB] = 0
        self.data[self.DATA_ADMUX] = 0
        self.data[self.DATA_ADCL] = 0
        self.data[self.DATA_ADCH] = 0
        self._analog_comp_positive_input = 0
        self._analog_comp_negative_input = 0
        self._analog_comp_output = 0
        self._analog_comp_interrupt_pending = False
        self.data[self.DATA_ACSR] = 0
        self._spi_transfer_cycles_remaining = 0
        self._spi_transfer_total_cycles = 0
        self._spi_transfer_value = 0
        self._spi_interrupt_pending = False
        self._spi_rx_queue = []
        self.spi_transmitted_bytes = []
        self.data[self.DATA_SPCR] = 0
        self.data[self.DATA_SPSR] = 0
        self.data[self.DATA_SPDR] = 0
        self._twi_operation_cycles_remaining = 0
        self._twi_operation_kind = None
        self._twi_interrupt_pending = False
        self._twi_read_queue = []
        self.twi_transmitted_bytes = []
        self._twi_state = "idle"
        self._twi_last_address = 0
        self._twi_rw = 0
        self.data[self.DATA_TWBR] = 0
        self.data[self.DATA_TWSR] = 0xF8
        self.data[self.DATA_TWAR] = 0
        self.data[self.DATA_TWDR] = 0
        self.data[self.DATA_TWCR] = 0
        self.data[self.DATA_TWAMR] = 0
        for pin_addr in self._gpio_input_levels:
            self._gpio_input_levels[pin_addr] = 0
            self._gpio_input_driven[pin_addr] = 0
            self._gpio_output_override_values[pin_addr] = 0
            self._gpio_output_override_masks[pin_addr] = 0
        self._ext_int_levels = [1] * 8
        self._update_gpio_alt_overrides()
        self._reset_profile_counters()

    # -----------------------------
    # Access profiling helpers
    # -----------------------------

    def _reset_profile_counters(self) -> None:
        self.profile_ram_reads = [0] * (self.DATA_SRAM_END + 1)
        self.profile_ram_writes = [0] * (self.DATA_SRAM_END + 1)
        flash_bytes = max(1, len(self.program) * 2)
        self.profile_flash_reads = [0] * flash_bytes
        self.profile_flash_writes = [0] * flash_bytes
        self.profile_eeprom_reads = [0] * self.EEPROM_SIZE
        self.profile_eeprom_writes = [0] * self.EEPROM_SIZE

    def _resize_flash_profile_counters(self) -> None:
        flash_bytes = max(1, len(self.program) * 2)
        self.profile_flash_reads = [0] * flash_bytes
        self.profile_flash_writes = [0] * flash_bytes

    def _profile_record_ram_read(self, addr: int) -> None:
        if 0 <= addr <= self.DATA_SRAM_END:
            self.profile_ram_reads[addr] += 1

    def _profile_record_ram_write(self, addr: int) -> None:
        if 0 <= addr <= self.DATA_SRAM_END:
            self.profile_ram_writes[addr] += 1

    def _profile_record_flash_byte_read(self, byte_addr: int) -> None:
        if 0 <= byte_addr < len(self.profile_flash_reads):
            self.profile_flash_reads[byte_addr] += 1

    def _profile_record_flash_byte_write(self, byte_addr: int) -> None:
        if 0 <= byte_addr < len(self.profile_flash_writes):
            self.profile_flash_writes[byte_addr] += 1

    def _profile_record_flash_word_read(self, word_addr: int) -> None:
        base = word_addr * 2
        self._profile_record_flash_byte_read(base)
        self._profile_record_flash_byte_read(base + 1)

    def _profile_record_flash_word_write(self, word_addr: int) -> None:
        base = word_addr * 2
        self._profile_record_flash_byte_write(base)
        self._profile_record_flash_byte_write(base + 1)

    def _profile_record_eeprom_read(self, addr: int) -> None:
        if 0 <= addr < self.EEPROM_SIZE:
            self.profile_eeprom_reads[addr] += 1

    def _profile_record_eeprom_write(self, addr: int) -> None:
        if 0 <= addr < self.EEPROM_SIZE:
            self.profile_eeprom_writes[addr] += 1

    def reset(self) -> None:
        self._reset_runtime_state(watchdog_reset=False)

    def _perform_watchdog_reset(self) -> None:
        self._reset_runtime_state(watchdog_reset=True)

    # Execute
    # -----------------------------
    def fetch(self) -> int:
        if self.pc < 0 or self.pc >= len(self.program):
            self.halt_reason = f"PC out of program bounds: 0x{self.pc:06X}"
            self.halted = True
            return 0x0000

        self._profile_record_flash_word_read(self.pc)
        opcode = self.program[self.pc]
        self.pc += 1
        return opcode

    def step(self) -> StepResult:
        if self.halted:
            return StepResult(self.pc, 0x0000, 0, "HALT")

        pc_before = self.pc
        opcode = self.fetch()
        desc = "UNIMPLEMENTED"
        used_cycles = 1

        # NOP: 0000 0000 0000 0000
        if opcode == 0x0000:
            desc = "NOP"

        # MOV: 0010 11rd dddd rrrr
        elif (opcode & 0xFC00) == 0x2C00:
            rd, rr = self._decode_rd_rr(opcode)
            self.reg[rd] = self.reg[rr]
            desc = f"MOV r{rd}, r{rr}"

        # MOVW: 0000 0001 dddd rrrr
        elif (opcode & 0xFF00) == 0x0100:
            d = (opcode >> 4) & 0x0F
            r = opcode & 0x0F
            rd = d * 2
            rr = r * 2
            self.reg[rd] = self.reg[rr]
            self.reg[rd + 1] = self.reg[rr + 1]
            desc = f"MOVW r{rd}:r{rd + 1}, r{rr}:r{rr + 1}"

        # ADD: 0000 11rd dddd rrrr
        elif (opcode & 0xFC00) == 0x0C00:
            rd, rr = self._decode_rd_rr(opcode)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val + rr_val) & 0xFF
            self.reg[rd] = result
            self._write_add_flags(rd_val, rr_val, result)
            if rd == rr:
                desc = f"LSL r{rd}"
            else:
                desc = f"ADD r{rd}, r{rr}"

        # ADC: 0001 11rd dddd rrrr
        elif (opcode & 0xFC00) == 0x1C00:
            rd, rr = self._decode_rd_rr(opcode)
            c_in = self._get_flag(self.FLAG_C)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val + rr_val + c_in) & 0xFF
            self.reg[rd] = result
            self._write_adc_flags(rd_val, rr_val, c_in, result)
            if rd == rr:
                desc = f"ROL r{rd}"
            else:
                desc = f"ADC r{rd}, r{rr}"

        # SUB: 0001 10rd dddd rrrr
        elif (opcode & 0xFC00) == 0x1800:
            rd, rr = self._decode_rd_rr(opcode)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val - rr_val) & 0xFF
            self.reg[rd] = result
            self._write_sub_flags(rd_val, rr_val, result)
            desc = f"SUB r{rd}, r{rr}"

        # SBC: 0000 10rd dddd rrrr
        elif (opcode & 0xFC00) == 0x0800:
            rd, rr = self._decode_rd_rr(opcode)
            c_in = self._get_flag(self.FLAG_C)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val - rr_val - c_in) & 0xFF
            self.reg[rd] = result
            self._write_sbc_flags(rd_val, rr_val, c_in, result, preserve_z=True)
            desc = f"SBC r{rd}, r{rr}"

        # CPC: 0000 01rd dddd rrrr
        elif (opcode & 0xFC00) == 0x0400:
            rd, rr = self._decode_rd_rr(opcode)
            c_in = self._get_flag(self.FLAG_C)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val - rr_val - c_in) & 0xFF
            self._write_sbc_flags(rd_val, rr_val, c_in, result, preserve_z=True)
            desc = f"CPC r{rd}, r{rr}"

        # AND: 0010 00rd dddd rrrr
        elif (opcode & 0xFC00) == 0x2000:
            rd, rr = self._decode_rd_rr(opcode)
            result = self.reg[rd] & self.reg[rr]
            self.reg[rd] = result
            self._write_logic_flags(result)
            desc = f"AND r{rd}, r{rr}"

        # OR: 0010 10rd dddd rrrr
        elif (opcode & 0xFC00) == 0x2800:
            rd, rr = self._decode_rd_rr(opcode)
            result = self.reg[rd] | self.reg[rr]
            self.reg[rd] = result
            self._write_logic_flags(result)
            desc = f"OR r{rd}, r{rr}"

        # EOR: 0010 01rd dddd rrrr
        elif (opcode & 0xFC00) == 0x2400:
            rd, rr = self._decode_rd_rr(opcode)
            result = self.reg[rd] ^ self.reg[rr]
            self.reg[rd] = result
            self._write_logic_flags(result)
            desc = f"EOR r{rd}, r{rr}"

        # LDI: 1110 KKKK dddd KKKK  (d=16..31)
        elif (opcode & 0xF000) == 0xE000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            self.reg[rd] = k
            desc = f"LDI r{rd}, 0x{k:02X}"

        # SUBI: 0101 KKKK dddd KKKK (d=16..31)
        elif (opcode & 0xF000) == 0x5000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            rd_val = self.reg[rd]
            result = (rd_val - k) & 0xFF
            self.reg[rd] = result
            self._write_sub_flags(rd_val, k, result)
            desc = f"SUBI r{rd}, 0x{k:02X}"

        # SBCI: 0100 KKKK dddd KKKK (d=16..31)
        elif (opcode & 0xF000) == 0x4000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            c_in = self._get_flag(self.FLAG_C)
            rd_val = self.reg[rd]
            result = (rd_val - k - c_in) & 0xFF
            self.reg[rd] = result
            self._write_sbc_flags(rd_val, k, c_in, result, preserve_z=True)
            desc = f"SBCI r{rd}, 0x{k:02X}"

        # ANDI: 0111 KKKK dddd KKKK (d=16..31)
        elif (opcode & 0xF000) == 0x7000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            result = self.reg[rd] & k
            self.reg[rd] = result
            self._write_logic_flags(result)
            desc = f"ANDI r{rd}, 0x{k:02X}"

        # ORI: 0110 KKKK dddd KKKK (d=16..31)
        elif (opcode & 0xF000) == 0x6000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            result = self.reg[rd] | k
            self.reg[rd] = result
            self._write_logic_flags(result)
            desc = f"ORI r{rd}, 0x{k:02X}"

        # ADIW: 1001 0110 KKdd KKKK (dd selects r24,r26,r28,r30 pairs)
        elif (opcode & 0xFF00) == 0x9600:
            d = (opcode >> 4) & 0x3
            k = ((opcode >> 2) & 0x30) | (opcode & 0x0F)
            rd = 24 + (d * 2)
            rdw = self.reg[rd] | (self.reg[rd + 1] << 8)
            result = (rdw + k) & 0xFFFF
            self.reg[rd] = result & 0xFF
            self.reg[rd + 1] = (result >> 8) & 0xFF

            rd15 = (rdw >> 15) & 1
            r15 = (result >> 15) & 1
            v = (1 - rd15) & r15
            c = (1 - r15) & rd15
            self._set_flag(self.FLAG_V, v)
            self._set_flag(self.FLAG_N, r15)
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, c)
            self._update_sign_flag()
            used_cycles = 2
            desc = f"ADIW r{rd}:r{rd + 1}, {k}"

        # SBIW: 1001 0111 KKdd KKKK (dd selects r24,r26,r28,r30 pairs)
        elif (opcode & 0xFF00) == 0x9700:
            d = (opcode >> 4) & 0x3
            k = ((opcode >> 2) & 0x30) | (opcode & 0x0F)
            rd = 24 + (d * 2)
            rdw = self.reg[rd] | (self.reg[rd + 1] << 8)
            result = (rdw - k) & 0xFFFF
            self.reg[rd] = result & 0xFF
            self.reg[rd + 1] = (result >> 8) & 0xFF

            rd15 = (rdw >> 15) & 1
            r15 = (result >> 15) & 1
            v = rd15 & (1 - r15)
            c = (1 - rd15) & r15
            self._set_flag(self.FLAG_V, v)
            self._set_flag(self.FLAG_N, r15)
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, c)
            self._update_sign_flag()
            used_cycles = 2
            desc = f"SBIW r{rd}:r{rd + 1}, {k}"

        # INC: 1001 010d dddd 0011
        elif (opcode & 0xFE0F) == 0x9403:
            rd = (opcode >> 4) & 0x1F
            result = (self.reg[rd] + 1) & 0xFF
            self.reg[rd] = result
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_N, (result >> 7) & 1)
            self._set_flag(self.FLAG_V, int(result == 0x80))
            self._update_sign_flag()
            desc = f"INC r{rd}"

        # DEC: 1001 010d dddd 1010
        elif (opcode & 0xFE0F) == 0x940A:
            rd = (opcode >> 4) & 0x1F
            result = (self.reg[rd] - 1) & 0xFF
            self.reg[rd] = result
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_N, (result >> 7) & 1)
            self._set_flag(self.FLAG_V, int(result == 0x7F))
            self._update_sign_flag()
            desc = f"DEC r{rd}"

        # LSR: 1001 010d dddd 0110
        elif (opcode & 0xFE0F) == 0x9406:
            rd = (opcode >> 4) & 0x1F
            old = self.reg[rd]
            c = old & 1
            result = (old >> 1) & 0x7F
            self.reg[rd] = result
            self._set_flag(self.FLAG_C, c)
            self._set_flag(self.FLAG_N, 0)
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_V, c)
            self._update_sign_flag()
            desc = f"LSR r{rd}"

        # ASR: 1001 010d dddd 0101
        elif (opcode & 0xFE0F) == 0x9405:
            rd = (opcode >> 4) & 0x1F
            old = self.reg[rd]
            c = old & 1
            result = ((old >> 1) | (old & 0x80)) & 0xFF
            self.reg[rd] = result
            n = (result >> 7) & 1
            self._set_flag(self.FLAG_C, c)
            self._set_flag(self.FLAG_N, n)
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_V, n ^ c)
            self._update_sign_flag()
            desc = f"ASR r{rd}"

        # ROR: 1001 010d dddd 0111
        elif (opcode & 0xFE0F) == 0x9407:
            rd = (opcode >> 4) & 0x1F
            old = self.reg[rd]
            c_in = self._get_flag(self.FLAG_C)
            c_out = old & 1
            result = ((old >> 1) | (c_in << 7)) & 0xFF
            self.reg[rd] = result
            n = (result >> 7) & 1
            self._set_flag(self.FLAG_C, c_out)
            self._set_flag(self.FLAG_N, n)
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_V, n ^ c_out)
            self._update_sign_flag()
            desc = f"ROR r{rd}"

        # SWAP: 1001 010d dddd 0010
        elif (opcode & 0xFE0F) == 0x9402:
            rd = (opcode >> 4) & 0x1F
            old = self.reg[rd]
            self.reg[rd] = ((old & 0x0F) << 4) | ((old & 0xF0) >> 4)
            desc = f"SWAP r{rd}"

        # COM: 1001 010d dddd 0000
        elif (opcode & 0xFE0F) == 0x9400:
            rd = (opcode >> 4) & 0x1F
            result = (~self.reg[rd]) & 0xFF
            self.reg[rd] = result
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_N, (result >> 7) & 1)
            self._set_flag(self.FLAG_V, 0)
            self._set_flag(self.FLAG_C, 1)
            self._update_sign_flag()
            desc = f"COM r{rd}"

        # NEG: 1001 010d dddd 0001
        elif (opcode & 0xFE0F) == 0x9401:
            rd = (opcode >> 4) & 0x1F
            old = self.reg[rd]
            result = (-old) & 0xFF
            self.reg[rd] = result
            self._write_sub_flags(0, old, result)
            desc = f"NEG r{rd}"

        # MUL: 1001 11rd dddd rrrr
        elif (opcode & 0xFC00) == 0x9C00:
            rd, rr = self._decode_rd_rr(opcode)
            result = (self.reg[rd] * self.reg[rr]) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"MUL r{rd}, r{rr}"

        # MULS: 0000 0010 dddd rrrr (d,r map to r16..r31)
        elif (opcode & 0xFF00) == 0x0200:
            d = (opcode >> 4) & 0x0F
            r = opcode & 0x0F
            rd = 16 + d
            rr = 16 + r
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            rd_s = rd_val if rd_val < 0x80 else rd_val - 0x100
            rr_s = rr_val if rr_val < 0x80 else rr_val - 0x100
            result = (rd_s * rr_s) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"MULS r{rd}, r{rr}"

        # MULSU: 0000 0011 0ddd 0rrr (d in r16..r23, r in r16..r23)
        elif (opcode & 0xFF88) == 0x0300:
            d = (opcode >> 4) & 0x07
            r = opcode & 0x07
            rd = 16 + d
            rr = 16 + r
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            rd_s = rd_val if rd_val < 0x80 else rd_val - 0x100
            result = (rd_s * rr_val) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"MULSU r{rd}, r{rr}"

        # FMUL: 0000 0011 0ddd 1rrr (r16..r23, unsigned * unsigned, <<1)
        elif (opcode & 0xFF88) == 0x0308:
            d = (opcode >> 4) & 0x07
            r = opcode & 0x07
            rd = 16 + d
            rr = 16 + r
            result = ((self.reg[rd] * self.reg[rr]) << 1) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"FMUL r{rd}, r{rr}"

        # FMULS: 0000 0011 1ddd 0rrr (r16..r23, signed * signed, <<1)
        elif (opcode & 0xFF88) == 0x0380:
            d = (opcode >> 4) & 0x07
            r = opcode & 0x07
            rd = 16 + d
            rr = 16 + r
            rd_s = self.reg[rd] if self.reg[rd] < 0x80 else self.reg[rd] - 0x100
            rr_s = self.reg[rr] if self.reg[rr] < 0x80 else self.reg[rr] - 0x100
            result = ((rd_s * rr_s) << 1) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"FMULS r{rd}, r{rr}"

        # FMULSU: 0000 0011 1ddd 1rrr (r16..r23, signed * unsigned, <<1)
        elif (opcode & 0xFF88) == 0x0388:
            d = (opcode >> 4) & 0x07
            r = opcode & 0x07
            rd = 16 + d
            rr = 16 + r
            rd_s = self.reg[rd] if self.reg[rd] < 0x80 else self.reg[rd] - 0x100
            result = ((rd_s * self.reg[rr]) << 1) & 0xFFFF
            self.reg[0] = result & 0xFF
            self.reg[1] = (result >> 8) & 0xFF
            self._set_flag(self.FLAG_Z, int(result == 0))
            self._set_flag(self.FLAG_C, (result >> 15) & 1)
            used_cycles = 2
            desc = f"FMULSU r{rd}, r{rr}"

        # CPI: 0011 KKKK dddd KKKK (d=16..31)
        elif (opcode & 0xF000) == 0x3000:
            rd = self._decode_rd_high(opcode)
            k = self._decode_k8(opcode)
            rd_val = self.reg[rd]
            result = (rd_val - k) & 0xFF
            self._write_sub_flags(rd_val, k, result)
            desc = f"CPI r{rd}, 0x{k:02X}"

        # CP: 0001 01rd dddd rrrr
        elif (opcode & 0xFC00) == 0x1400:
            rd, rr = self._decode_rd_rr(opcode)
            rd_val = self.reg[rd]
            rr_val = self.reg[rr]
            result = (rd_val - rr_val) & 0xFF
            self._write_sub_flags(rd_val, rr_val, result)
            desc = f"CP r{rd}, r{rr}"

        # CPSE: 0001 00rd dddd rrrr
        elif (opcode & 0xFC00) == 0x1000:
            rd, rr = self._decode_rd_rr(opcode)
            if self.reg[rd] == self.reg[rr]:
                skip_words = self._instruction_words_at_pc(self.pc)
                self.pc += skip_words
                used_cycles = 1 + skip_words
            else:
                used_cycles = 1
            desc = f"CPSE r{rd}, r{rr}"

        # SBRC: 1111 110r rrrr 0bbb
        elif (opcode & 0xFE08) == 0xFC00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            if ((self.reg[rr] >> b) & 1) == 0:
                skip_words = self._instruction_words_at_pc(self.pc)
                self.pc += skip_words
                used_cycles = 1 + skip_words
            else:
                used_cycles = 1
            desc = f"SBRC r{rr}, {b}"

        # SBRS: 1111 111r rrrr 0bbb
        elif (opcode & 0xFE08) == 0xFE00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            if ((self.reg[rr] >> b) & 1) == 1:
                skip_words = self._instruction_words_at_pc(self.pc)
                self.pc += skip_words
                used_cycles = 1 + skip_words
            else:
                used_cycles = 1
            desc = f"SBRS r{rr}, {b}"

        # SBIC: 1001 1001 AAAA Abbb
        elif (opcode & 0xFF00) == 0x9900:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            if ((self._io_read(a) >> b) & 1) == 0:
                skip_words = self._instruction_words_at_pc(self.pc)
                self.pc += skip_words
                used_cycles = 1 + skip_words
            else:
                used_cycles = 1
            desc = f"SBIC 0x{a:02X}, {b}"

        # SBIS: 1001 1011 AAAA Abbb
        elif (opcode & 0xFF00) == 0x9B00:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            if ((self._io_read(a) >> b) & 1) == 1:
                skip_words = self._instruction_words_at_pc(self.pc)
                self.pc += skip_words
                used_cycles = 1 + skip_words
            else:
                used_cycles = 1
            desc = f"SBIS 0x{a:02X}, {b}"

        # LD Rd, X: 1001 000d dddd 1100
        elif (opcode & 0xFE0F) == 0x900C:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("X")
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, X"

        # LDD Rd, Y+q / Z+q: 10q0 qq0d dddd yqqq (y=1->Y, y=0->Z)
        elif (opcode & 0xD200) == 0x8000:
            rd = (opcode >> 4) & 0x1F
            ptr_name = "Y" if (opcode & 0x0008) else "Z"
            q = ((opcode >> 8) & 0x20) | ((opcode >> 7) & 0x18) | (opcode & 0x7)
            addr = (self._get_ptr(ptr_name) + q) & 0xFFFF
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LDD r{rd}, {ptr_name}+{q}"

        # LD Rd, X+: 1001 000d dddd 1101
        elif (opcode & 0xFE0F) == 0x900D:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("X")
            self.reg[rd] = self._data_read(addr)
            self._set_ptr("X", addr + 1)
            used_cycles = 2
            desc = f"LD r{rd}, X+"

        # LD Rd, -X: 1001 000d dddd 1110
        elif (opcode & 0xFE0F) == 0x900E:
            rd = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("X") - 1) & 0xFFFF
            self._set_ptr("X", addr)
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, -X"

        # LD Rd, Y: 1000 000d dddd 1000
        elif (opcode & 0xFE0F) == 0x8008:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Y")
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, Y"

        # LD Rd, Y+: 1001 000d dddd 1001
        elif (opcode & 0xFE0F) == 0x9009:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Y")
            self.reg[rd] = self._data_read(addr)
            self._set_ptr("Y", addr + 1)
            used_cycles = 2
            desc = f"LD r{rd}, Y+"

        # LD Rd, -Y: 1001 000d dddd 1010
        elif (opcode & 0xFE0F) == 0x900A:
            rd = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("Y") - 1) & 0xFFFF
            self._set_ptr("Y", addr)
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, -Y"

        # LD Rd, Z: 1000 000d dddd 0000
        elif (opcode & 0xFE0F) == 0x8000:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, Z"

        # LD Rd, Z+: 1001 000d dddd 0001
        elif (opcode & 0xFE0F) == 0x9001:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            self.reg[rd] = self._data_read(addr)
            self._set_ptr("Z", addr + 1)
            used_cycles = 2
            desc = f"LD r{rd}, Z+"

        # LD Rd, -Z: 1001 000d dddd 0010
        elif (opcode & 0xFE0F) == 0x9002:
            rd = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("Z") - 1) & 0xFFFF
            self._set_ptr("Z", addr)
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LD r{rd}, -Z"

        # LPM: 1001 0101 1100 1000 (R0 <- (Z))
        elif opcode == 0x95C8:
            z = self._get_ptr("Z")
            word_index = z >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[0] = (w & 0xFF) if (z & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[0] = 0
            used_cycles = 3
            desc = "LPM"

        # ELPM: 1001 0101 1101 1000 (R0 <- (RAMPZ:Z))
        elif opcode == 0x95D8:
            z = self._get_ptr("Z")
            rampz = self._data_read(self.DATA_RAMPZ) & 0xFF
            byte_addr = ((rampz << 16) | z) & 0xFFFFFF
            word_index = byte_addr >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[0] = (w & 0xFF) if (byte_addr & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[0] = 0
            used_cycles = 3
            desc = "ELPM"

        # LPM Rd, Z: 1001 000d dddd 0100
        elif (opcode & 0xFE0F) == 0x9004:
            rd = (opcode >> 4) & 0x1F
            z = self._get_ptr("Z")
            word_index = z >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[rd] = (w & 0xFF) if (z & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[rd] = 0
            used_cycles = 3
            desc = f"LPM r{rd}, Z"

        # LPM Rd, Z+: 1001 000d dddd 0101
        elif (opcode & 0xFE0F) == 0x9005:
            rd = (opcode >> 4) & 0x1F
            z = self._get_ptr("Z")
            word_index = z >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[rd] = (w & 0xFF) if (z & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[rd] = 0
            self._set_ptr("Z", z + 1)
            used_cycles = 3
            desc = f"LPM r{rd}, Z+"

        # ELPM Rd, Z: 1001 000d dddd 0110
        elif (opcode & 0xFE0F) == 0x9006:
            rd = (opcode >> 4) & 0x1F
            z = self._get_ptr("Z")
            rampz = self._data_read(self.DATA_RAMPZ) & 0xFF
            byte_addr = ((rampz << 16) | z) & 0xFFFFFF
            word_index = byte_addr >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[rd] = (w & 0xFF) if (byte_addr & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[rd] = 0
            used_cycles = 3
            desc = f"ELPM r{rd}, Z"

        # ELPM Rd, Z+: 1001 000d dddd 0111
        elif (opcode & 0xFE0F) == 0x9007:
            rd = (opcode >> 4) & 0x1F
            z = self._get_ptr("Z")
            rampz = self._data_read(self.DATA_RAMPZ) & 0xFF
            byte_addr = ((rampz << 16) | z) & 0xFFFFFF
            word_index = byte_addr >> 1
            if 0 <= word_index < len(self.program):
                self._profile_record_flash_word_read(word_index)
                w = self.program[word_index]
                self.reg[rd] = (w & 0xFF) if (byte_addr & 1) == 0 else ((w >> 8) & 0xFF)
            else:
                self.reg[rd] = 0
            self._set_ptr("Z", z + 1)
            used_cycles = 3
            desc = f"ELPM r{rd}, Z+"

        # ST X, Rr: 1001 001r rrrr 1100
        elif (opcode & 0xFE0F) == 0x920C:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("X")
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST X, r{rr}"

        # XCH Z, Rd: 1001 001d dddd 0100
        elif (opcode & 0xFE0F) == 0x9204:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            old_mem = self._data_read(addr)
            self._data_write(addr, self.reg[rd])
            self.reg[rd] = old_mem
            used_cycles = 2
            desc = f"XCH Z, r{rd}"

        # LAS Z, Rd: 1001 001d dddd 0101
        elif (opcode & 0xFE0F) == 0x9205:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            old_mem = self._data_read(addr)
            self._data_write(addr, old_mem | self.reg[rd])
            self.reg[rd] = old_mem
            used_cycles = 2
            desc = f"LAS Z, r{rd}"

        # LAC Z, Rd: 1001 001d dddd 0110
        elif (opcode & 0xFE0F) == 0x9206:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            old_mem = self._data_read(addr)
            self._data_write(addr, old_mem & (~self.reg[rd] & 0xFF))
            self.reg[rd] = old_mem
            used_cycles = 2
            desc = f"LAC Z, r{rd}"

        # LAT Z, Rd: 1001 001d dddd 0111
        elif (opcode & 0xFE0F) == 0x9207:
            rd = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            old_mem = self._data_read(addr)
            self._data_write(addr, old_mem ^ self.reg[rd])
            self.reg[rd] = old_mem
            used_cycles = 2
            desc = f"LAT Z, r{rd}"

        # STD Y+q / Z+q, Rr: 10q0 qq1r rrrr yqqq (y=1->Y, y=0->Z)
        elif (opcode & 0xD200) == 0x8200:
            rr = (opcode >> 4) & 0x1F
            ptr_name = "Y" if (opcode & 0x0008) else "Z"
            q = ((opcode >> 8) & 0x20) | ((opcode >> 7) & 0x18) | (opcode & 0x7)
            addr = (self._get_ptr(ptr_name) + q) & 0xFFFF
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"STD {ptr_name}+{q}, r{rr}"

        # ST X+, Rr: 1001 001r rrrr 1101
        elif (opcode & 0xFE0F) == 0x920D:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("X")
            self._data_write(addr, self.reg[rr])
            self._set_ptr("X", addr + 1)
            used_cycles = 2
            desc = f"ST X+, r{rr}"

        # ST -X, Rr: 1001 001r rrrr 1110
        elif (opcode & 0xFE0F) == 0x920E:
            rr = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("X") - 1) & 0xFFFF
            self._set_ptr("X", addr)
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST -X, r{rr}"

        # ST Y, Rr: 1000 001r rrrr 1000
        elif (opcode & 0xFE0F) == 0x8208:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Y")
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST Y, r{rr}"

        # ST Y+, Rr: 1001 001r rrrr 1001
        elif (opcode & 0xFE0F) == 0x9209:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Y")
            self._data_write(addr, self.reg[rr])
            self._set_ptr("Y", addr + 1)
            used_cycles = 2
            desc = f"ST Y+, r{rr}"

        # ST -Y, Rr: 1001 001r rrrr 1010
        elif (opcode & 0xFE0F) == 0x920A:
            rr = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("Y") - 1) & 0xFFFF
            self._set_ptr("Y", addr)
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST -Y, r{rr}"

        # ST Z, Rr: 1000 001r rrrr 0000
        elif (opcode & 0xFE0F) == 0x8200:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST Z, r{rr}"

        # ST Z+, Rr: 1001 001r rrrr 0001
        elif (opcode & 0xFE0F) == 0x9201:
            rr = (opcode >> 4) & 0x1F
            addr = self._get_ptr("Z")
            self._data_write(addr, self.reg[rr])
            self._set_ptr("Z", addr + 1)
            used_cycles = 2
            desc = f"ST Z+, r{rr}"

        # ST -Z, Rr: 1001 001r rrrr 0010
        elif (opcode & 0xFE0F) == 0x9202:
            rr = (opcode >> 4) & 0x1F
            addr = (self._get_ptr("Z") - 1) & 0xFFFF
            self._set_ptr("Z", addr)
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"ST -Z, r{rr}"

        # LDS Rd, k: 1001 000d dddd 0000 + kkkk kkkk kkkk kkkk
        elif (opcode & 0xFE0F) == 0x9000:
            rd = (opcode >> 4) & 0x1F
            addr = self._fetch_next_word()
            self.reg[rd] = self._data_read(addr)
            used_cycles = 2
            desc = f"LDS r{rd}, 0x{addr:04X}"

        # CBI: 1001 1000 AAAA Abbb
        elif (opcode & 0xFF00) == 0x9800:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            if (0x20 + a) not in self.GPIO_PIN_ADDRS:  # CBI on a PINx register has no effect
                self._io_write(a, self._io_read(a) & ~(1 << b))
            used_cycles = 2
            desc = f"CBI 0x{a:02X}, {b}"

        # SBI: 1001 1010 AAAA Abbb
        elif (opcode & 0xFF00) == 0x9A00:
            a = (opcode >> 3) & 0x1F
            b = opcode & 0x7
            if (0x20 + a) in self.GPIO_PIN_ADDRS:  # SBI on a PINx register toggles only that bit
                self._io_write(a, 1 << b)
            else:
                self._io_write(a, self._io_read(a) | (1 << b))
            used_cycles = 2
            desc = f"SBI 0x{a:02X}, {b}"

        # STS k, Rr: 1001 001r rrrr 0000 + kkkk kkkk kkkk kkkk
        elif (opcode & 0xFE0F) == 0x9200:
            rr = (opcode >> 4) & 0x1F
            addr = self._fetch_next_word()
            self._data_write(addr, self.reg[rr])
            used_cycles = 2
            desc = f"STS 0x{addr:04X}, r{rr}"

        # IN: 1011 0AAd dddd AAAA
        elif (opcode & 0xF800) == 0xB000:
            rd = (opcode >> 4) & 0x1F
            a = (opcode & 0x0F) | ((opcode >> 5) & 0x30)
            self.reg[rd] = self._io_read(a)
            desc = f"IN r{rd}, {self._format_io_operand(a)}"

        # OUT: 1011 1AAr rrrr AAAA
        elif (opcode & 0xF800) == 0xB800:
            rr = (opcode >> 4) & 0x1F
            a = (opcode & 0x0F) | ((opcode >> 5) & 0x30)
            self._io_write(a, self.reg[rr])
            desc = f"OUT {self._format_io_operand(a)}, r{rr}"

        # RJMP: 1100 kkkk kkkk kkkk
        elif (opcode & 0xF000) == 0xC000:
            k = self._sign_extend(opcode & 0x0FFF, 12)
            self.pc = self.pc + k
            used_cycles = 2
            desc = f"RJMP {k:+d}"

        # RCALL: 1101 kkkk kkkk kkkk
        elif (opcode & 0xF000) == 0xD000:
            k = self._sign_extend(opcode & 0x0FFF, 12)
            return_addr = self.pc
            self._push_return_address(return_addr)
            self.pc = self.pc + k
            used_cycles = 3
            desc = f"RCALL {k:+d}"

        # JMP k: 1001 010k kkkk 110k + kkkk kkkk kkkk kkkk
        elif (opcode & 0xFE0E) == 0x940C:
            low = self._fetch_next_word()
            target = self._decode_long_target(opcode, low)
            self.pc = target
            used_cycles = 3
            desc = f"JMP 0x{target:06X}"

        # CALL k: 1001 010k kkkk 111k + kkkk kkkk kkkk kkkk
        elif (opcode & 0xFE0E) == 0x940E:
            low = self._fetch_next_word()
            target = self._decode_long_target(opcode, low)
            return_addr = self.pc
            self._push_return_address(return_addr)
            self.pc = target
            used_cycles = 4
            desc = f"CALL 0x{target:06X}"

        # IJMP: 1001 0100 0000 1001
        elif opcode == 0x9409:
            self.pc = self._get_ptr("Z")
            used_cycles = 2
            desc = "IJMP"

        # EIJMP: 1001 0100 0001 1001
        elif opcode == 0x9419:
            eind = self._data_read(self.DATA_EIND) & 0x3F
            self.pc = ((eind << 16) | self._get_ptr("Z")) & 0x3FFFFF
            used_cycles = 2
            desc = "EIJMP"

        # ICALL: 1001 0101 0000 1001
        elif opcode == 0x9509:
            return_addr = self.pc
            self._push_return_address(return_addr)
            self.pc = self._get_ptr("Z")
            used_cycles = 3
            desc = "ICALL"

        # EICALL: 1001 0101 0001 1001
        elif opcode == 0x9519:
            return_addr = self.pc
            self._push_return_address(return_addr)
            eind = self._data_read(self.DATA_EIND) & 0x3F
            self.pc = ((eind << 16) | self._get_ptr("Z")) & 0x3FFFFF
            used_cycles = 4
            desc = "EICALL"

        # PUSH: 1001 001d dddd 1111
        elif (opcode & 0xFE0F) == 0x920F:
            rr = (opcode >> 4) & 0x1F
            self._push_byte(self.reg[rr])
            used_cycles = 2
            desc = f"PUSH r{rr}"

        # POP: 1001 000d dddd 1111
        elif (opcode & 0xFE0F) == 0x900F:
            rd = (opcode >> 4) & 0x1F
            self.reg[rd] = self._pop_byte()
            used_cycles = 2
            desc = f"POP r{rd}"

        # RET: 1001 0101 0000 1000
        elif opcode == 0x9508:
            self.pc = self._pop_return_address()
            used_cycles = 4
            desc = "RET"

        # RETI: 1001 0101 0001 1000
        elif opcode == 0x9518:
            self.pc = self._pop_return_address()
            self._set_flag(self.FLAG_I, 1)
            used_cycles = 4
            desc = "RETI"

        # SLEEP: 1001 0101 1000 1000
        elif opcode == 0x9588:
            self.halt_reason = f"SLEEP at PC=0x{pc_before:06X}"
            self.halted = True
            desc = "SLEEP"

        # BREAK: 1001 0101 1001 1000
        elif opcode == 0x9598:
            self.halt_reason = f"BREAK at PC=0x{pc_before:06X}"
            self.halted = True
            desc = "BREAK"

        # WDR: 1001 0101 1010 1000
        elif opcode == 0x95A8:
            self.watchdog.kick(self.data)
            desc = "WDR"

        # SPM: 1001 0101 1110 1000
        elif opcode == 0x95E8:
            z = self._get_ptr("Z")
            word_index = z >> 1
            value = (self.reg[0] & 0xFF) | ((self.reg[1] & 0xFF) << 8)
            if 0 <= word_index < len(self.program):
                self.program[word_index] = value
                self._profile_record_flash_word_write(word_index)
            used_cycles = 4
            desc = "SPM"

        # SPM Z+: 1001 0101 1111 1000
        elif opcode == 0x95F8:
            z = self._get_ptr("Z")
            word_index = z >> 1
            value = (self.reg[0] & 0xFF) | ((self.reg[1] & 0xFF) << 8)
            if 0 <= word_index < len(self.program):
                self.program[word_index] = value
                self._profile_record_flash_word_write(word_index)
            self._set_ptr("Z", z + 2)
            used_cycles = 4
            desc = "SPM Z+"

        # Explicit flag-control aliases for clearer decode traces.
        elif opcode == 0x9408:
            self._set_flag(self.FLAG_C, 1)
            desc = "SEC"
        elif opcode == 0x9488:
            self._set_flag(self.FLAG_C, 0)
            desc = "CLC"
        elif opcode == 0x9418:
            self._set_flag(self.FLAG_Z, 1)
            desc = "SEZ"
        elif opcode == 0x9498:
            self._set_flag(self.FLAG_Z, 0)
            desc = "CLZ"
        elif opcode == 0x9428:
            self._set_flag(self.FLAG_N, 1)
            desc = "SEN"
        elif opcode == 0x94A8:
            self._set_flag(self.FLAG_N, 0)
            desc = "CLN"
        elif opcode == 0x9438:
            self._set_flag(self.FLAG_V, 1)
            desc = "SEV"
        elif opcode == 0x94B8:
            self._set_flag(self.FLAG_V, 0)
            desc = "CLV"
        elif opcode == 0x9448:
            self._set_flag(self.FLAG_S, 1)
            desc = "SES"
        elif opcode == 0x94C8:
            self._set_flag(self.FLAG_S, 0)
            desc = "CLS"
        elif opcode == 0x9458:
            self._set_flag(self.FLAG_H, 1)
            desc = "SEH"
        elif opcode == 0x94D8:
            self._set_flag(self.FLAG_H, 0)
            desc = "CLH"
        elif opcode == 0x9468:
            self._set_flag(self.FLAG_T, 1)
            desc = "SET"
        elif opcode == 0x94E8:
            self._set_flag(self.FLAG_T, 0)
            desc = "CLT"
        elif opcode == 0x9478:
            self._set_flag(self.FLAG_I, 1)
            # AVR accepts interrupts after the instruction following SEI.
            self._interrupt_inhibit_once = True
            desc = "SEI"
        elif opcode == 0x94F8:
            self._set_flag(self.FLAG_I, 0)
            desc = "CLI"

        # BSET: 1001 0100 0sss 1000
        elif (opcode & 0xFF8F) == 0x9408:
            s = (opcode >> 4) & 0x7
            self._set_flag(s, 1)
            desc = f"BSET {s}"

        # BCLR: 1001 0100 1sss 1000
        elif (opcode & 0xFF8F) == 0x9488:
            s = (opcode >> 4) & 0x7
            self._set_flag(s, 0)
            desc = f"BCLR {s}"

        # BLD: 1111 100d dddd 0bbb
        elif (opcode & 0xFE08) == 0xF800:
            rd = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            mask = 1 << b
            if self._get_flag(self.FLAG_T):
                self.reg[rd] |= mask
            else:
                self.reg[rd] &= ~mask & 0xFF
            desc = f"BLD r{rd}, {b}"

        # BST: 1111 101d dddd 0bbb
        elif (opcode & 0xFE08) == 0xFA00:
            rr = (opcode >> 4) & 0x1F
            b = opcode & 0x7
            self._set_flag(self.FLAG_T, (self.reg[rr] >> b) & 1)
            desc = f"BST r{rr}, {b}"

        # BRBS / BRBC share encoding group 1111 00/01kk kkkk ksss
        # BRBS: 1111 00kk kkkk ksss
        elif (opcode & 0xFC00) == 0xF000:
            s = opcode & 0x7
            k = self._sign_extend((opcode >> 3) & 0x7F, 7)
            if self._get_flag(s):
                self.pc = self.pc + k
                used_cycles = 2
            else:
                used_cycles = 1
            brbs_alias = {
                self.FLAG_C: "BRCS",
                self.FLAG_Z: "BREQ",
                self.FLAG_N: "BRMI",
                self.FLAG_V: "BRVS",
                self.FLAG_S: "BRLT",
                self.FLAG_H: "BRHS",
                self.FLAG_T: "BRTS",
                self.FLAG_I: "BRIE",
            }
            mnemonic = brbs_alias.get(s, f"BRBS s{s}")
            desc = f"{mnemonic} {k:+d}"

        # BRBC: 1111 01kk kkkk ksss
        elif (opcode & 0xFC00) == 0xF400:
            s = opcode & 0x7
            k = self._sign_extend((opcode >> 3) & 0x7F, 7)
            if not self._get_flag(s):
                self.pc = self.pc + k
                used_cycles = 2
            else:
                used_cycles = 1
            brbc_alias = {
                self.FLAG_C: "BRCC",
                self.FLAG_Z: "BRNE",
                self.FLAG_N: "BRPL",
                self.FLAG_V: "BRVC",
                self.FLAG_S: "BRGE",
                self.FLAG_H: "BRHC",
                self.FLAG_T: "BRTC",
                self.FLAG_I: "BRID",
            }
            mnemonic = brbc_alias.get(s, f"BRBC s{s}")
            desc = f"{mnemonic} {k:+d}"

        else:
            raise NotImplementedError(f"Opcode 0x{opcode:04X} not implemented at PC={pc_before}")

        self.timer0.advance(used_cycles, self.data)
        self.timer1.advance(used_cycles, self.data)
        self.timer2.advance(used_cycles, self.data)
        self.timer3.advance(used_cycles, self.data)
        self.timer4.advance(used_cycles, self.data)
        self.timer5.advance(used_cycles, self.data)
        self._advance_spi(used_cycles)
        self._advance_adc(used_cycles)
        self._advance_eeprom(used_cycles)
        self._advance_twi(used_cycles)
        self._update_pcint_flags()
        uart_tx_before = (
            bool(self.uart0._pending_tx)
            or bool(self.uart1._pending_tx)
            or bool(self.uart2._pending_tx)
            or bool(self.uart3._pending_tx)
        )
        for uart in self.uarts:
            uart.advance(used_cycles, self.data)
        uart_tx_after = (
            bool(self.uart0._pending_tx)
            or bool(self.uart1._pending_tx)
            or bool(self.uart2._pending_tx)
            or bool(self.uart3._pending_tx)
        )
        if uart_tx_before != uart_tx_after:
            self._update_gpio_alt_overrides()
        watchdog_event = self.watchdog.advance(used_cycles, self.data)
        self.cycles += used_cycles
        self.total_cycles += used_cycles
        if watchdog_event == "reset":
            self._perform_watchdog_reset()
            return StepResult(pc_before, opcode, used_cycles, desc)
        if self._interrupt_inhibit_once:
            self._interrupt_inhibit_once = False
        else:
            self._service_interrupts()
        return StepResult(pc_before, opcode, used_cycles, desc)

    def run(self, max_steps: Optional[int] = None) -> int:
        steps = 0
        while not self.halted:
            if max_steps is not None and steps >= max_steps:
                break
            self.step()
            steps += 1
        return steps


if __name__ == "__main__":
    # Tiny smoke test program (word opcodes), assembled via helpers.
    program = [
        ldi(16, 0x05),
        ldi(17, 0x03),
        add(16, 17),
        cpi(16, 0x08),
        brbs(1, 1),
        rjmp(-2),
        0x0000,
    ]

    emu = ATmega2560Emulator()
    emu.load_program_words(program)

    for _ in range(7):
        result = emu.step()
        print(
            f"PC={result.pc_before:04X} OP={result.opcode:04X} CYC={result.cycles} "
            f"{result.description}"
        )

    print(f"r16={emu.reg[16]:02X} r17={emu.reg[17]:02X} SREG={emu.sreg:08b} cycles={emu.cycles}")
