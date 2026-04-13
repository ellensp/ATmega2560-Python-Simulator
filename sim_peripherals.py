"""Peripheral models for the ATmega2560 emulator."""


def _read16(data: bytearray, lo_addr: int, hi_addr: int) -> int:
    return data[lo_addr] | (data[hi_addr] << 8)


def _write16(data: bytearray, lo_addr: int, hi_addr: int, value: int) -> None:
    value &= 0xFFFF
    data[lo_addr] = value & 0xFF
    data[hi_addr] = (value >> 8) & 0xFF


def _set_compare_flags_8bit(
    data: bytearray,
    tifr_idx: int,
    value: int,
    ocr_a: int,
    ocr_b: int,
    ocf_a_bit: int,
    ocf_b_bit: int,
) -> None:
    if value == ocr_b:
        data[tifr_idx] |= 1 << ocf_b_bit
    if value == ocr_a:
        data[tifr_idx] |= 1 << ocf_a_bit


def _set_compare_flags_16bit(
    data: bytearray,
    tifr_idx: int,
    value: int,
    ocr_a: int,
    ocr_b: int,
    ocr_c: int,
    ocf_a_bit: int,
    ocf_b_bit: int,
    ocf_c_bit: int,
) -> None:
    if value == ocr_b:
        data[tifr_idx] |= 1 << ocf_b_bit
    if value == ocr_c:
        data[tifr_idx] |= 1 << ocf_c_bit
    if value == ocr_a:
        data[tifr_idx] |= 1 << ocf_a_bit


class Timer0:
    """Minimal Timer/Counter0 model tied to CPU cycles.

    Implemented behavior:
    - Clock source selection via TCCR0B.CS02:0 (no clock / clk/1/8/64/256/1024)
    - TCNT0 increment according to prescaler
    - OCF0A/OCF0B set in TIFR0 when TCNT0 matches OCR0A/OCR0B
    - TOV0 set in TIFR0 on 0xFF -> 0x00 overflow
    """

    IO_TIFR0 = 0x15
    IO_TCCR0A = 0x24
    IO_TCCR0B = 0x25
    IO_TCNT0 = 0x26
    IO_OCR0A = 0x27
    IO_OCR0B = 0x28

    DATA_TIMSK0 = 0x006E

    TOV0_BIT = 0
    OCF0A_BIT = 1
    OCF0B_BIT = 2

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 64,
        0b100: 256,
        0b101: 1024,
    }

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr0b = data[0x20 + self.IO_TCCR0B]
        cs = tccr0b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        self._prescaler_accum += cycles
        tccr0a = data[0x20 + self.IO_TCCR0A]
        wgm00 = (tccr0a >> 0) & 1
        wgm01 = (tccr0a >> 1) & 1
        wgm02 = (tccr0b >> 3) & 1
        mode = (wgm02 << 2) | (wgm01 << 1) | wgm00
        ctc_mode = mode == 0b010
        fast_pwm_mode = mode in (0b011, 0b111)
        phase_correct_mode = mode in (0b001, 0b101)

        top = 0xFF
        if mode in (0b101, 0b111):
            top = data[0x20 + self.IO_OCR0A]
            if top == 0:
                top = 1

        tcnt_idx = 0x20 + self.IO_TCNT0
        tifr_idx = 0x20 + self.IO_TIFR0

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div
            cur = data[tcnt_idx]
            ocr_a = data[0x20 + self.IO_OCR0A]
            ocr_b = data[0x20 + self.IO_OCR0B]

            if phase_correct_mode:
                if self._count_up:
                    next_val = cur + 1
                    if next_val >= top:
                        next_val = top
                        self._count_up = False
                else:
                    next_val = cur - 1 if cur > 0 else 0
                    if next_val == 0:
                        self._count_up = True
                        data[tifr_idx] |= 1 << self.TOV0_BIT

                next_val &= 0xFF
                data[tcnt_idx] = next_val
                _set_compare_flags_8bit(data, tifr_idx, next_val, ocr_a, ocr_b, self.OCF0A_BIT, self.OCF0B_BIT)
                continue

            raw_next = cur + 1
            next_val = raw_next & 0xFF
            data[tcnt_idx] = next_val
            _set_compare_flags_8bit(data, tifr_idx, next_val, ocr_a, ocr_b, self.OCF0A_BIT, self.OCF0B_BIT)

            if ctc_mode and next_val == ocr_a:
                data[tcnt_idx] = 0
                continue

            if fast_pwm_mode:
                if raw_next > top:
                    data[tcnt_idx] = 0
                    data[tifr_idx] |= 1 << self.TOV0_BIT
                continue

            if next_val == 0:
                data[tifr_idx] |= 1 << self.TOV0_BIT


class Timer1:
    """Baseline Timer/Counter1 model tied to CPU cycles.

    Implemented behavior:
    - Clock source selection via TCCR1B.CS12:0 (clk/1/8/64/256/1024)
    - 16-bit TCNT1 increment according to prescaler
    - OCF1A/OCF1B/OCF1C set in TIFR1 on OCR1A/B/C compare match
    - TOV1 set in TIFR1 on 0xFFFF -> 0x0000 overflow
    - CTC baseline for WGM13:0 == 0b0100 (clear on OCR1A compare)
    """

    IO_TIFR1 = 0x16
    DATA_TIMSK1 = 0x006F

    DATA_TCCR1A = 0x0080
    DATA_TCCR1B = 0x0081
    DATA_TCNT1L = 0x0084
    DATA_TCNT1H = 0x0085
    DATA_ICR1L = 0x0086
    DATA_ICR1H = 0x0087
    DATA_OCR1AL = 0x0088
    DATA_OCR1AH = 0x0089
    DATA_OCR1BL = 0x008A
    DATA_OCR1BH = 0x008B
    DATA_OCR1CL = 0x008C
    DATA_OCR1CH = 0x008D

    TOV1_BIT = 0
    OCF1A_BIT = 1
    OCF1B_BIT = 2
    OCF1C_BIT = 3
    ICF1_BIT = 5

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 64,
        0b100: 256,
        0b101: 1024,
    }

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr1b = data[self.DATA_TCCR1B]
        cs = tccr1b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        tccr1a = data[self.DATA_TCCR1A]
        wgm10 = (tccr1a >> 0) & 1
        wgm11 = (tccr1a >> 1) & 1
        wgm12 = (tccr1b >> 3) & 1
        wgm13 = (tccr1b >> 4) & 1
        mode = (wgm13 << 3) | (wgm12 << 2) | (wgm11 << 1) | wgm10
        ctc_mode = mode == 0b0100
        fast_pwm_top = {0b0101: 0x00FF, 0b0110: 0x01FF, 0b0111: 0x03FF}.get(mode)
        phase_correct_top = {0b0001: 0x00FF, 0b0010: 0x01FF, 0b0011: 0x03FF}.get(mode)

        tifr1_idx = 0x20 + self.IO_TIFR1
        self._prescaler_accum += cycles

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div

            cur = _read16(data, self.DATA_TCNT1L, self.DATA_TCNT1H)
            ocr1a = _read16(data, self.DATA_OCR1AL, self.DATA_OCR1AH)
            ocr1b = _read16(data, self.DATA_OCR1BL, self.DATA_OCR1BH)
            ocr1c = _read16(data, self.DATA_OCR1CL, self.DATA_OCR1CH)

            if phase_correct_top is not None:
                top = phase_correct_top
                if self._count_up:
                    nxt = cur + 1
                    if nxt >= top:
                        nxt = top
                        self._count_up = False
                else:
                    nxt = cur - 1 if cur > 0 else 0
                    if nxt == 0:
                        self._count_up = True
                        data[tifr1_idx] |= 1 << self.TOV1_BIT
                _write16(data, self.DATA_TCNT1L, self.DATA_TCNT1H, nxt)
                _set_compare_flags_16bit(data, tifr1_idx, nxt, ocr1a, ocr1b, ocr1c, self.OCF1A_BIT, self.OCF1B_BIT, self.OCF1C_BIT)
                continue

            nxt = (cur + 1) & 0xFFFF
            _write16(data, self.DATA_TCNT1L, self.DATA_TCNT1H, nxt)
            _set_compare_flags_16bit(data, tifr1_idx, nxt, ocr1a, ocr1b, ocr1c, self.OCF1A_BIT, self.OCF1B_BIT, self.OCF1C_BIT)

            if ctc_mode and nxt == ocr1a:
                _write16(data, self.DATA_TCNT1L, self.DATA_TCNT1H, 0)
                continue

            if fast_pwm_top is not None:
                if nxt > fast_pwm_top:
                    _write16(data, self.DATA_TCNT1L, self.DATA_TCNT1H, 0)
                    data[tifr1_idx] |= 1 << self.TOV1_BIT
                continue

            if nxt == 0:
                data[tifr1_idx] |= 1 << self.TOV1_BIT


class Timer2:
    """Baseline Timer/Counter2 model tied to CPU cycles.

    Implemented behavior:
    - Clock source selection via TCCR2B.CS22:0 (clk/1/8/32/64/128/256/1024)
    - 8-bit TCNT2 increment according to prescaler
    - OCF2A/OCF2B set in TIFR2 on OCR2A/OCR2B compare match
    - TOV2 set in TIFR2 on 0xFF -> 0x00 overflow
    - CTC baseline for WGM22:0 == 0b010 (clear on OCR2A compare)
    """

    IO_TIFR2 = 0x17
    DATA_TIMSK2 = 0x0070

    DATA_TCCR2A = 0x00B0
    DATA_TCCR2B = 0x00B1
    DATA_TCNT2 = 0x00B2
    DATA_OCR2A = 0x00B3
    DATA_OCR2B = 0x00B4
    DATA_ASSR = 0x00B6

    AS2_BIT = 3

    TOV2_BIT = 0
    OCF2A_BIT = 1
    OCF2B_BIT = 2

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 32,
        0b100: 64,
        0b101: 128,
        0b110: 256,
        0b111: 1024,
    }

    # Baseline approximation for asynchronous Timer2 domain versus CPU cycles.
    _ASYNC_SCALE = 128

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr2b = data[self.DATA_TCCR2B]
        cs = tccr2b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        if ((data[self.DATA_ASSR] >> self.AS2_BIT) & 1) == 1:
            div *= self._ASYNC_SCALE

        tccr2a = data[self.DATA_TCCR2A]
        wgm20 = (tccr2a >> 0) & 1
        wgm21 = (tccr2a >> 1) & 1
        wgm22 = (tccr2b >> 3) & 1
        mode = (wgm22 << 2) | (wgm21 << 1) | wgm20
        ctc_mode = mode == 0b010
        fast_pwm_mode = mode in (0b011, 0b111)
        phase_correct_mode = mode in (0b001, 0b101)

        top = 0xFF
        if mode in (0b101, 0b111):
            top = data[self.DATA_OCR2A]
            if top == 0:
                top = 1

        tifr2_idx = 0x20 + self.IO_TIFR2
        self._prescaler_accum += cycles

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div

            cur = data[self.DATA_TCNT2]
            ocr_a = data[self.DATA_OCR2A]
            ocr_b = data[self.DATA_OCR2B]

            if phase_correct_mode:
                if self._count_up:
                    nxt = cur + 1
                    if nxt >= top:
                        nxt = top
                        self._count_up = False
                else:
                    nxt = cur - 1 if cur > 0 else 0
                    if nxt == 0:
                        self._count_up = True
                        data[tifr2_idx] |= 1 << self.TOV2_BIT

                nxt &= 0xFF
                data[self.DATA_TCNT2] = nxt
                _set_compare_flags_8bit(data, tifr2_idx, nxt, ocr_a, ocr_b, self.OCF2A_BIT, self.OCF2B_BIT)
                continue

            raw_next = cur + 1
            nxt = raw_next & 0xFF
            data[self.DATA_TCNT2] = nxt
            _set_compare_flags_8bit(data, tifr2_idx, nxt, ocr_a, ocr_b, self.OCF2A_BIT, self.OCF2B_BIT)

            if ctc_mode and nxt == ocr_a:
                data[self.DATA_TCNT2] = 0
                continue

            if fast_pwm_mode:
                if raw_next > top:
                    data[self.DATA_TCNT2] = 0
                    data[tifr2_idx] |= 1 << self.TOV2_BIT
                continue

            if nxt == 0:
                data[tifr2_idx] |= 1 << self.TOV2_BIT


class Timer3:
    """Baseline Timer/Counter3 model tied to CPU cycles.

    Implemented behavior:
    - Clock source selection via TCCR3B.CS32:0 (clk/1/8/64/256/1024)
    - 16-bit TCNT3 increment according to prescaler
    - OCF3A/OCF3B/OCF3C set in TIFR3 on OCR3A/B/C compare match
    - TOV3 set in TIFR3 on 0xFFFF -> 0x0000 overflow
    - CTC baseline for WGM33:0 == 0b0100 (clear on OCR3A compare)
    """

    IO_TIFR3 = 0x18
    DATA_TIMSK3 = 0x0071

    DATA_TCCR3A = 0x0090
    DATA_TCCR3B = 0x0091
    DATA_TCNT3L = 0x0094
    DATA_TCNT3H = 0x0095
    DATA_ICR3L = 0x0096
    DATA_ICR3H = 0x0097
    DATA_OCR3AL = 0x0098
    DATA_OCR3AH = 0x0099
    DATA_OCR3BL = 0x009A
    DATA_OCR3BH = 0x009B
    DATA_OCR3CL = 0x009C
    DATA_OCR3CH = 0x009D

    TOV3_BIT = 0
    OCF3A_BIT = 1
    OCF3B_BIT = 2
    OCF3C_BIT = 3
    ICF3_BIT = 5

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 64,
        0b100: 256,
        0b101: 1024,
    }

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr3b = data[self.DATA_TCCR3B]
        cs = tccr3b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        tccr3a = data[self.DATA_TCCR3A]
        wgm30 = (tccr3a >> 0) & 1
        wgm31 = (tccr3a >> 1) & 1
        wgm32 = (tccr3b >> 3) & 1
        wgm33 = (tccr3b >> 4) & 1
        mode = (wgm33 << 3) | (wgm32 << 2) | (wgm31 << 1) | wgm30
        ctc_mode = mode == 0b0100
        fast_pwm_top = {0b0101: 0x00FF, 0b0110: 0x01FF, 0b0111: 0x03FF}.get(mode)
        phase_correct_top = {0b0001: 0x00FF, 0b0010: 0x01FF, 0b0011: 0x03FF}.get(mode)

        tifr3_idx = 0x20 + self.IO_TIFR3
        self._prescaler_accum += cycles

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div

            cur = _read16(data, self.DATA_TCNT3L, self.DATA_TCNT3H)
            ocr3a = _read16(data, self.DATA_OCR3AL, self.DATA_OCR3AH)
            ocr3b = _read16(data, self.DATA_OCR3BL, self.DATA_OCR3BH)
            ocr3c = _read16(data, self.DATA_OCR3CL, self.DATA_OCR3CH)

            if phase_correct_top is not None:
                top = phase_correct_top
                if self._count_up:
                    nxt = cur + 1
                    if nxt >= top:
                        nxt = top
                        self._count_up = False
                else:
                    nxt = cur - 1 if cur > 0 else 0
                    if nxt == 0:
                        self._count_up = True
                        data[tifr3_idx] |= 1 << self.TOV3_BIT
                _write16(data, self.DATA_TCNT3L, self.DATA_TCNT3H, nxt)
                _set_compare_flags_16bit(data, tifr3_idx, nxt, ocr3a, ocr3b, ocr3c, self.OCF3A_BIT, self.OCF3B_BIT, self.OCF3C_BIT)
                continue

            nxt = (cur + 1) & 0xFFFF
            _write16(data, self.DATA_TCNT3L, self.DATA_TCNT3H, nxt)
            _set_compare_flags_16bit(data, tifr3_idx, nxt, ocr3a, ocr3b, ocr3c, self.OCF3A_BIT, self.OCF3B_BIT, self.OCF3C_BIT)

            if ctc_mode and nxt == ocr3a:
                _write16(data, self.DATA_TCNT3L, self.DATA_TCNT3H, 0)
                continue

            if fast_pwm_top is not None:
                if nxt > fast_pwm_top:
                    _write16(data, self.DATA_TCNT3L, self.DATA_TCNT3H, 0)
                    data[tifr3_idx] |= 1 << self.TOV3_BIT
                continue

            if nxt == 0:
                data[tifr3_idx] |= 1 << self.TOV3_BIT


class Timer4:
    """Baseline Timer/Counter4 model tied to CPU cycles."""

    IO_TIFR4 = 0x19
    DATA_TIMSK4 = 0x0072

    DATA_TCCR4A = 0x00A0
    DATA_TCCR4B = 0x00A1
    DATA_TCNT4L = 0x00A4
    DATA_TCNT4H = 0x00A5
    DATA_ICR4L = 0x00A6
    DATA_ICR4H = 0x00A7
    DATA_OCR4AL = 0x00A8
    DATA_OCR4AH = 0x00A9
    DATA_OCR4BL = 0x00AA
    DATA_OCR4BH = 0x00AB
    DATA_OCR4CL = 0x00AC
    DATA_OCR4CH = 0x00AD

    TOV4_BIT = 0
    OCF4A_BIT = 1
    OCF4B_BIT = 2
    OCF4C_BIT = 3
    ICF4_BIT = 5

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 64,
        0b100: 256,
        0b101: 1024,
    }

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr4b = data[self.DATA_TCCR4B]
        cs = tccr4b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        tccr4a = data[self.DATA_TCCR4A]
        wgm40 = (tccr4a >> 0) & 1
        wgm41 = (tccr4a >> 1) & 1
        wgm42 = (tccr4b >> 3) & 1
        wgm43 = (tccr4b >> 4) & 1
        mode = (wgm43 << 3) | (wgm42 << 2) | (wgm41 << 1) | wgm40
        ctc_mode = mode == 0b0100
        fast_pwm_top = {0b0101: 0x00FF, 0b0110: 0x01FF, 0b0111: 0x03FF}.get(mode)
        phase_correct_top = {0b0001: 0x00FF, 0b0010: 0x01FF, 0b0011: 0x03FF}.get(mode)

        tifr4_idx = 0x20 + self.IO_TIFR4
        self._prescaler_accum += cycles

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div

            cur = _read16(data, self.DATA_TCNT4L, self.DATA_TCNT4H)
            ocr4a = _read16(data, self.DATA_OCR4AL, self.DATA_OCR4AH)
            ocr4b = _read16(data, self.DATA_OCR4BL, self.DATA_OCR4BH)
            ocr4c = _read16(data, self.DATA_OCR4CL, self.DATA_OCR4CH)

            if phase_correct_top is not None:
                top = phase_correct_top
                if self._count_up:
                    nxt = cur + 1
                    if nxt >= top:
                        nxt = top
                        self._count_up = False
                else:
                    nxt = cur - 1 if cur > 0 else 0
                    if nxt == 0:
                        self._count_up = True
                        data[tifr4_idx] |= 1 << self.TOV4_BIT
                _write16(data, self.DATA_TCNT4L, self.DATA_TCNT4H, nxt)
                _set_compare_flags_16bit(data, tifr4_idx, nxt, ocr4a, ocr4b, ocr4c, self.OCF4A_BIT, self.OCF4B_BIT, self.OCF4C_BIT)
                continue

            nxt = (cur + 1) & 0xFFFF
            _write16(data, self.DATA_TCNT4L, self.DATA_TCNT4H, nxt)
            _set_compare_flags_16bit(data, tifr4_idx, nxt, ocr4a, ocr4b, ocr4c, self.OCF4A_BIT, self.OCF4B_BIT, self.OCF4C_BIT)

            if ctc_mode and nxt == ocr4a:
                _write16(data, self.DATA_TCNT4L, self.DATA_TCNT4H, 0)
                continue

            if fast_pwm_top is not None:
                if nxt > fast_pwm_top:
                    _write16(data, self.DATA_TCNT4L, self.DATA_TCNT4H, 0)
                    data[tifr4_idx] |= 1 << self.TOV4_BIT
                continue

            if nxt == 0:
                data[tifr4_idx] |= 1 << self.TOV4_BIT


class Timer5:
    """Baseline Timer/Counter5 model tied to CPU cycles."""

    IO_TIFR5 = 0x1A
    DATA_TIMSK5 = 0x0073

    DATA_TCCR5A = 0x0120
    DATA_TCCR5B = 0x0121
    DATA_TCNT5L = 0x0124
    DATA_TCNT5H = 0x0125
    DATA_ICR5L = 0x0126
    DATA_ICR5H = 0x0127
    DATA_OCR5AL = 0x0128
    DATA_OCR5AH = 0x0129
    DATA_OCR5BL = 0x012A
    DATA_OCR5BH = 0x012B
    DATA_OCR5CL = 0x012C
    DATA_OCR5CH = 0x012D

    TOV5_BIT = 0
    OCF5A_BIT = 1
    OCF5B_BIT = 2
    OCF5C_BIT = 3
    ICF5_BIT = 5

    _PRESCALE = {
        0b001: 1,
        0b010: 8,
        0b011: 64,
        0b100: 256,
        0b101: 1024,
    }

    def __init__(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return

        tccr5b = data[self.DATA_TCCR5B]
        cs = tccr5b & 0x7
        div = self._PRESCALE.get(cs)
        if div is None:
            return

        tccr5a = data[self.DATA_TCCR5A]
        wgm50 = (tccr5a >> 0) & 1
        wgm51 = (tccr5a >> 1) & 1
        wgm52 = (tccr5b >> 3) & 1
        wgm53 = (tccr5b >> 4) & 1
        mode = (wgm53 << 3) | (wgm52 << 2) | (wgm51 << 1) | wgm50
        ctc_mode = mode == 0b0100
        fast_pwm_top = {0b0101: 0x00FF, 0b0110: 0x01FF, 0b0111: 0x03FF}.get(mode)
        phase_correct_top = {0b0001: 0x00FF, 0b0010: 0x01FF, 0b0011: 0x03FF}.get(mode)

        tifr5_idx = 0x20 + self.IO_TIFR5
        self._prescaler_accum += cycles

        while self._prescaler_accum >= div:
            self._prescaler_accum -= div

            cur = _read16(data, self.DATA_TCNT5L, self.DATA_TCNT5H)
            ocr5a = _read16(data, self.DATA_OCR5AL, self.DATA_OCR5AH)
            ocr5b = _read16(data, self.DATA_OCR5BL, self.DATA_OCR5BH)
            ocr5c = _read16(data, self.DATA_OCR5CL, self.DATA_OCR5CH)

            if phase_correct_top is not None:
                top = phase_correct_top
                if self._count_up:
                    nxt = cur + 1
                    if nxt >= top:
                        nxt = top
                        self._count_up = False
                else:
                    nxt = cur - 1 if cur > 0 else 0
                    if nxt == 0:
                        self._count_up = True
                        data[tifr5_idx] |= 1 << self.TOV5_BIT
                _write16(data, self.DATA_TCNT5L, self.DATA_TCNT5H, nxt)
                _set_compare_flags_16bit(data, tifr5_idx, nxt, ocr5a, ocr5b, ocr5c, self.OCF5A_BIT, self.OCF5B_BIT, self.OCF5C_BIT)
                continue

            nxt = (cur + 1) & 0xFFFF
            _write16(data, self.DATA_TCNT5L, self.DATA_TCNT5H, nxt)
            _set_compare_flags_16bit(data, tifr5_idx, nxt, ocr5a, ocr5b, ocr5c, self.OCF5A_BIT, self.OCF5B_BIT, self.OCF5C_BIT)

            if ctc_mode and nxt == ocr5a:
                _write16(data, self.DATA_TCNT5L, self.DATA_TCNT5H, 0)
                continue

            if fast_pwm_top is not None:
                if nxt > fast_pwm_top:
                    _write16(data, self.DATA_TCNT5L, self.DATA_TCNT5H, 0)
                    data[tifr5_idx] |= 1 << self.TOV5_BIT
                continue

            if nxt == 0:
                data[tifr5_idx] |= 1 << self.TOV5_BIT


class WatchdogTimer:
    """Baseline watchdog timer model.

    Implemented behavior:
    - WDTCSR timed change sequence (WDCE+WDE then update within 4 CPU cycles)
    - WDP timeout selection and watchdog countdown
    - Interrupt-only mode (WDIE)
    - Reset mode (WDE)
    - Combined interrupt+reset mode (first timeout interrupt, second reset)
    - WDR servicing hook and MCUSR.WDRF reset-cause flag
    """

    DATA_MCUSR = 0x0054
    DATA_WDTCSR = 0x0060

    WDRF_BIT = 3

    WDIF_BIT = 7
    WDIE_BIT = 6
    WDP3_BIT = 5
    WDCE_BIT = 4
    WDE_BIT = 3

    # Atmega2560 watchdog minimum period is ~16 ms.
    # With F_CPU=16 MHz this is about 256,000 CPU cycles.
    _BASE_TIMEOUT_CYCLES = 256000
    _WDP_MULT = {
        0: 1,
        1: 2,
        2: 4,
        3: 8,
        4: 16,
        5: 32,
        6: 64,
        7: 128,
        8: 256,
        9: 512,
    }

    def __init__(self) -> None:
        self._counter_cycles = self._BASE_TIMEOUT_CYCLES
        self._cfg_window_cycles = 0
        self._combined_second_stage = False

    def reset(self, data: bytearray, watchdog_reset: bool = False) -> None:
        self._cfg_window_cycles = 0
        self._combined_second_stage = False
        data[self.DATA_WDTCSR] = 0

        if watchdog_reset:
            data[self.DATA_MCUSR] |= 1 << self.WDRF_BIT
        else:
            data[self.DATA_MCUSR] &= ~(1 << self.WDRF_BIT)

        self._counter_cycles = self._timeout_cycles(data)

    @staticmethod
    def _wdp_index(wdtcsr: int) -> int:
        low = wdtcsr & 0x7
        high = (wdtcsr >> WatchdogTimer.WDP3_BIT) & 0x1
        return low | (high << 3)

    def _timeout_cycles(self, data: bytearray) -> int:
        wdtcsr = data[self.DATA_WDTCSR]
        idx = self._wdp_index(wdtcsr)
        mult = self._WDP_MULT.get(idx, self._WDP_MULT[0])
        return self._BASE_TIMEOUT_CYCLES * mult

    def kick(self, data: bytearray) -> None:
        self._combined_second_stage = False
        self._counter_cycles = self._timeout_cycles(data)

    def write_wdtcsr(self, value: int, data: bytearray) -> None:
        value &= 0xFF
        cur = data[self.DATA_WDTCSR]

        # WDIF is cleared by writing logic one.
        if value & (1 << self.WDIF_BIT):
            cur &= ~(1 << self.WDIF_BIT)

        # Start timed configuration window.
        if (value & ((1 << self.WDCE_BIT) | (1 << self.WDE_BIT))) == ((1 << self.WDCE_BIT) | (1 << self.WDE_BIT)):
            cur |= (1 << self.WDCE_BIT) | (1 << self.WDE_BIT)
            data[self.DATA_WDTCSR] = cur
            self._cfg_window_cycles = 4
            return

        # During active window, allow updates to WDIE/WDE/WDP bits.
        if self._cfg_window_cycles > 0:
            keep = cur & (1 << self.WDIF_BIT)
            nxt = keep
            nxt |= value & (1 << self.WDIE_BIT)
            nxt |= value & (1 << self.WDE_BIT)
            nxt |= value & (1 << self.WDP3_BIT)
            nxt |= value & 0x07
            data[self.DATA_WDTCSR] = nxt

            self._cfg_window_cycles = 0
            if ((nxt >> self.WDE_BIT) & 1) == 0:
                self._combined_second_stage = False
            self._counter_cycles = self._timeout_cycles(data)
            return

        # Outside timed window, only WDIF clear takes effect.
        data[self.DATA_WDTCSR] = cur

    def advance(self, cycles: int, data: bytearray) -> str | None:
        if cycles <= 0:
            return None

        if self._cfg_window_cycles > 0:
            self._cfg_window_cycles = max(0, self._cfg_window_cycles - cycles)
            if self._cfg_window_cycles == 0:
                data[self.DATA_WDTCSR] &= ~(1 << self.WDCE_BIT)

        wdtcsr = data[self.DATA_WDTCSR]
        wde = (wdtcsr >> self.WDE_BIT) & 1
        wdie = (wdtcsr >> self.WDIE_BIT) & 1

        if not wde and not wdie:
            return None

        self._counter_cycles -= cycles
        if self._counter_cycles > 0:
            return None

        self._counter_cycles = self._timeout_cycles(data)

        if wdie and (not wde or not self._combined_second_stage):
            data[self.DATA_WDTCSR] |= 1 << self.WDIF_BIT
            if wde:
                self._combined_second_stage = True
            return "interrupt"

        self._combined_second_stage = False
        return "reset"

    def on_interrupt_serviced(self, data: bytearray) -> None:
        data[self.DATA_WDTCSR] &= ~(1 << self.WDIF_BIT)


class UARTBase:
    """Minimal USART TX/RX model shared across USART0..USART3."""

    DATA_UCSRA = 0
    DATA_UCSRB = 0
    DATA_UDR = 0

    UDRE_BIT = 5
    TXC_BIT = 6
    RXC_BIT = 7
    RXCIE_BIT = 7
    TXCIE_BIT = 6
    UDRIE_BIT = 5
    TXEN_BIT = 3
    RXEN_BIT = 4

    def __init__(self) -> None:
        self.tx_log: list[int] = []
        self._pending_tx: list[int] = []
        self._rx_fifo: list[int] = []

    def reset(self, data: bytearray) -> None:
        self.tx_log.clear()
        self._pending_tx.clear()
        self._rx_fifo.clear()
        data[self.DATA_UCSRA] |= 1 << self.UDRE_BIT

    def write_udr(self, value: int, data: bytearray) -> None:
        data[self.DATA_UDR] = value & 0xFF

        if ((data[self.DATA_UCSRB] >> self.TXEN_BIT) & 1) == 0:
            return

        data[self.DATA_UCSRA] &= ~(1 << self.UDRE_BIT)
        data[self.DATA_UCSRA] &= ~(1 << self.TXC_BIT)
        self._pending_tx.append(value & 0xFF)

    def read_udr(self, data: bytearray) -> int:
        current = data[self.DATA_UDR]

        if self._rx_fifo:
            nxt = self._rx_fifo.pop(0)
            data[self.DATA_UDR] = nxt
            data[self.DATA_UCSRA] |= 1 << self.RXC_BIT
        else:
            data[self.DATA_UCSRA] &= ~(1 << self.RXC_BIT)

        return current

    def inject_rx_byte(self, value: int, data: bytearray) -> None:
        if ((data[self.DATA_UCSRB] >> self.RXEN_BIT) & 1) == 0:
            return

        value &= 0xFF
        rxc_set = ((data[self.DATA_UCSRA] >> self.RXC_BIT) & 1) == 1
        if not rxc_set:
            data[self.DATA_UDR] = value
            data[self.DATA_UCSRA] |= 1 << self.RXC_BIT
            return

        self._rx_fifo.append(value)

    def is_transmitting(self) -> bool:
        """Return True while a byte is queued to be shifted out."""
        return bool(self._pending_tx)

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return
        if not self._pending_tx:
            return

        # Minimal timing model: one queued byte completes on the next CPU step.
        byte = self._pending_tx.pop(0)
        self.tx_log.append(byte)
        data[self.DATA_UCSRA] |= 1 << self.UDRE_BIT
        data[self.DATA_UCSRA] |= 1 << self.TXC_BIT


class UART0(UARTBase):
    DATA_UCSRA = DATA_UCSR0A = 0x00C0
    DATA_UCSRB = DATA_UCSR0B = 0x00C1
    DATA_UDR = DATA_UDR0 = 0x00C6

    UDRE_BIT = UDRE0_BIT = 5
    TXC_BIT = TXC0_BIT = 6
    RXC_BIT = RXC0_BIT = 7
    RXCIE_BIT = RXCIE0_BIT = 7
    TXCIE_BIT = TXCIE0_BIT = 6
    UDRIE_BIT = UDRIE0_BIT = 5
    TXEN_BIT = TXEN0_BIT = 3
    RXEN_BIT = RXEN0_BIT = 4


class UART1(UARTBase):
    DATA_UCSRA = DATA_UCSR1A = 0x00C8
    DATA_UCSRB = DATA_UCSR1B = 0x00C9
    DATA_UDR = DATA_UDR1 = 0x00CE

    UDRE_BIT = UDRE1_BIT = 5
    TXC_BIT = TXC1_BIT = 6
    RXC_BIT = RXC1_BIT = 7
    RXCIE_BIT = RXCIE1_BIT = 7
    TXCIE_BIT = TXCIE1_BIT = 6
    UDRIE_BIT = UDRIE1_BIT = 5
    TXEN_BIT = TXEN1_BIT = 3
    RXEN_BIT = RXEN1_BIT = 4


class UART2(UARTBase):
    DATA_UCSRA = DATA_UCSR2A = 0x00D0
    DATA_UCSRB = DATA_UCSR2B = 0x00D1
    DATA_UDR = DATA_UDR2 = 0x00D6

    UDRE_BIT = UDRE2_BIT = 5
    TXC_BIT = TXC2_BIT = 6
    RXC_BIT = RXC2_BIT = 7
    RXCIE_BIT = RXCIE2_BIT = 7
    TXCIE_BIT = TXCIE2_BIT = 6
    UDRIE_BIT = UDRIE2_BIT = 5
    TXEN_BIT = TXEN2_BIT = 3
    RXEN_BIT = RXEN2_BIT = 4


class UART3(UARTBase):
    DATA_UCSRA = DATA_UCSR3A = 0x0130
    DATA_UCSRB = DATA_UCSR3B = 0x0131
    DATA_UDR = DATA_UDR3 = 0x0136

    UDRE_BIT = UDRE3_BIT = 5
    TXC_BIT = TXC3_BIT = 6
    RXC_BIT = RXC3_BIT = 7
    RXCIE_BIT = RXCIE3_BIT = 7
    TXCIE_BIT = TXCIE3_BIT = 6
    UDRIE_BIT = UDRIE3_BIT = 5
    TXEN_BIT = TXEN3_BIT = 3
    RXEN_BIT = RXEN3_BIT = 4
