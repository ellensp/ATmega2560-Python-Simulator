"""Peripheral models for the ATmega2560 emulator."""


def _read16(data: bytearray, lo_addr: int, hi_addr: int) -> int:
    return data[lo_addr] | (data[hi_addr] << 8)


def _write16(data: bytearray, lo_addr: int, hi_addr: int, value: int) -> None:
    value &= 0xFFFF
    data[lo_addr] = value & 0xFF
    data[hi_addr] = (value >> 8) & 0xFF


class _TimerBase:
    """Clocking, OCR buffering and external clocking shared by all timers.

    Timer0, 1, 3, 4 and 5 count edges of one shared prescaler, so the position
    of a prescaled tick does not depend on when a timer was started. Measured
    on a real ATmega2560: that prescaler only runs while at least one of those
    timers has a clock selected, and keeps its count while they are all stopped.
    The emulator passes its count before the cycles being advanced.

    In the PWM modes a write to OCRnx goes to a buffer and reaches the compare
    register at BOTTOM (fast PWM, phase and frequency correct) or at TOP (phase
    correct); in the normal and CTC modes it takes effect at once (measured).

    Compare outputs (OCnx): each channel keeps an output state that the COM bits
    change on a compare match (and at BOTTOM in fast PWM). The change happens on
    the timer clock after the match, with the compare flag, and the state is
    kept while the output is disconnected (measured on OC0A and OC1C).
    """

    CHANNELS = 2

    SHARED_PRESCALER = True
    EXTERNAL_CLOCK = True  # CS = 6 / 7 count falling / rising edges of the Tn pin

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
        # A write to TCNT blocks the compare match on the next timer clock.
        self._compare_block = False
        # Compare register values in use (A, B, C); data[] holds the OCR buffers.
        self._ocr_active = [0, 0, 0]
        self._was_pwm = False
        # Compare output states (A, B, C) and the emulator's callback for a change.
        self.oc_level = [0, 0, 0]
        self.oc_changed = None  # callable(timer, cycle)

    def reset(self) -> None:
        self._prescaler_accum = 0
        self._count_up = True
        self._compare_block = False
        self._ocr_active = [0, 0, 0]
        self._was_pwm = False
        self.oc_level = [0, 0, 0]

    def _ticks(self, cycles: int, div: int, prescaler: int | None) -> int:
        if div == 1:
            return cycles
        if prescaler is None or not self.SHARED_PRESCALER:
            self._prescaler_accum += cycles
            ticks = self._prescaler_accum // div
            self._prescaler_accum -= ticks * div
            return ticks
        return (prescaler + cycles) // div - prescaler // div

    def _clock_select(self, data: bytearray) -> int:
        raise NotImplementedError

    def _run_ticks(self, ticks: int, data: bytearray) -> None:
        raise NotImplementedError

    def _is_pwm_mode(self, data: bytearray) -> bool:
        raise NotImplementedError

    def mode_written(self, data: bytearray) -> None:
        """TCCRnA/B was written: outside the PWM modes OCR writes are unbuffered again."""
        if not self._is_pwm_mode(data):
            self._was_pwm = False

    def external_edge(self, rising: bool, data: bytearray, now: int = 0) -> None:
        """An edge on the timer's Tn pin: one count if that edge is the clock source."""
        cs = self._clock_select(data)
        if self.EXTERNAL_CLOCK and ((cs == 7 and rising) or (cs == 6 and not rising)):
            self._run_ticks(1, data, now, 1)

    def _first_tick_offset(self, div: int, prescaler: int | None) -> int:
        """Cycles from the start of the span being advanced to its first timer clock."""
        if div == 1:
            return 1
        if prescaler is None or not self.SHARED_PRESCALER:
            return div - (self._prescaler_accum % div)
        return div - (prescaler % div)

    # (on a match counting up, on a match counting down, at the TOP -> BOTTOM wrap):
    # "t" toggle, "c" clear, "s" set, None nothing. None instead of a tuple: disconnected.
    _OC_NON_PWM = {1: ("t", "t", None), 2: ("c", "c", None), 3: ("s", "s", None)}
    _OC_FAST = {2: ("c", "c", "s"), 3: ("s", "s", "c")}
    _OC_PHASE = {2: ("c", "s", None), 3: ("s", "c", None)}

    def _oc_rule(self, kind: str, com: int, toggle_allowed: bool):
        if com == 0:
            return None
        if kind in ("normal", "ctc"):
            return self._OC_NON_PWM[com]
        if com == 1:
            return ("t", "t", None) if toggle_allowed else None
        return (self._OC_FAST if kind == "fast" else self._OC_PHASE)[com]

    def oc_rules(self, data: bytearray) -> list:
        """The compare-output rule of each channel for the current mode (None: disconnected)."""
        raise NotImplementedError

    def _oc_apply(self, channel: int, action: str | None, when: int) -> None:
        if action is None:
            return
        old = self.oc_level[channel]
        new = (old ^ 1) if action == "t" else (0 if action == "c" else 1)
        if new != old:
            self.oc_level[channel] = new
            if self.oc_changed is not None:
                self.oc_changed(self, when)

    def _oc_force(self, channel: int, rule, high: bool, when: int) -> None:
        """Phase-correct modes put a PWM output in the state it must have where the OCR
        buffer is loaded, even without a compare match (measured). `high` is the
        level of a non-inverting output there."""
        if rule is not None and rule[0] != "t":
            inverting = rule[0] == "s"
            self._oc_apply(channel, "s" if high != inverting else "c", when)

    def force_compare(self, channel: int, data: bytearray, when: int) -> None:
        """FOCnx strobe: the compare action without the flag, outside the PWM modes."""
        rule = self.oc_rules(data)[channel]
        if rule is not None and not self._is_pwm_mode(data):
            self._oc_apply(channel, rule[0], when)


class _Timer8(_TimerBase):
    """8-bit timer: normal, CTC, fast PWM and phase-correct PWM counting.

    Compare flags are set on the timer clock after the match, so the counter
    stays at TOP for a full clock and a period is TOP + 1 clocks (2 * TOP in the
    phase-correct modes). TOV is set at the MAX/TOP wrap, or at BOTTOM in the
    phase-correct modes. The OCnx output pins are not modelled.
    """

    _ASYNC_SCALE = 1
    # Data-space addresses, set by the subclass: TCCRnA, TCCRnB, TCNTn, OCRnA, OCRnB, TIFRn.
    _REGS = (0, 0, 0, 0, 0, 0)

    def _clock_select(self, data: bytearray) -> int:
        return data[self._REGS[1]] & 0x7

    def _divisor(self, data: bytearray) -> int | None:
        return self._PRESCALE.get(data[self._REGS[1]] & 0x7)

    def _is_pwm_mode(self, data: bytearray) -> bool:
        return (data[self._REGS[0]] & 0x01) != 0  # WGMn0 is set in every PWM mode

    def advance(self, cycles: int, data: bytearray, prescaler: int | None = None, now: int = 0) -> None:
        if cycles <= 0:
            return
        div = self._divisor(data)
        if div is None:
            return
        first = self._first_tick_offset(div, prescaler)
        ticks = self._ticks(cycles, div, prescaler)
        if ticks:
            self._run_ticks(ticks, data, now + first, div)

    def oc_rules(self, data: bytearray) -> list:
        tccra, tccrb = self._REGS[0], self._REGS[1]
        mode = (((data[tccrb] >> 3) & 1) << 2) | (data[tccra] & 0x03)
        kind = "ctc" if mode == 0b010 else "fast" if mode in (0b011, 0b111) else "phase" if mode in (0b001, 0b101) else "normal"
        a = data[tccra]
        # COMnA = 1 in a PWM mode toggles OCnA only when OCRnA is TOP (WGMn2 set).
        return [
            self._oc_rule(kind, (a >> 6) & 3, mode in (0b101, 0b111)),
            self._oc_rule(kind, (a >> 4) & 3, False),
        ]

    def _run_ticks(self, ticks: int, data: bytearray, when: int = 0, step: int = 1) -> None:
        tccra, tccrb, tcnt, ocra, ocrb, tifr = self._REGS
        mode = (((data[tccrb] >> 3) & 1) << 2) | (data[tccra] & 0x03)
        ctc = mode == 0b010
        fast = mode in (0b011, 0b111)
        phase = mode in (0b001, 0b101)
        ocra_top = mode in (0b101, 0b111)
        pwm = fast or phase
        rule_a, rule_b = self.oc_rules(data) if data[tccra] & 0xF0 else (None, None)
        outputs = rule_a is not None or rule_b is not None
        active = self._ocr_active
        if not pwm or not self._was_pwm:
            active[0] = data[ocra]
            active[1] = data[ocrb]
        self._was_pwm = pwm

        for _ in range(ticks):
            cur = data[tcnt]
            if not pwm:
                active[0] = data[ocra]
                active[1] = data[ocrb]
            ocra_val = active[0]
            top = ocra_val if ocra_top else 0xFF
            if phase:
                # The direction turns at BOTTOM and TOP before the compare outputs act,
                # so OCR = TOP counts as a match on the way down.
                if cur == 0:
                    data[tifr] |= 0x01
                    self._count_up = True
                turned = self._count_up and cur >= top
                if turned:
                    self._count_up = False
            if self._compare_block:
                self._compare_block = False
            else:
                if cur == active[1]:
                    data[tifr] |= 0x04
                    if rule_b is not None:
                        self._oc_apply(1, rule_b[0 if self._count_up or not phase else 1], when)
                if cur == ocra_val:
                    data[tifr] |= 0x02
                    if rule_a is not None:
                        self._oc_apply(0, rule_a[0 if self._count_up or not phase else 1], when)

            if phase:
                if turned:
                    if outputs:
                        self._oc_force(0, rule_a, ocra_val >= top, when)
                        self._oc_force(1, rule_b, active[1] >= top, when)
                    active[0] = data[ocra]  # OCR buffers are loaded at TOP
                    active[1] = data[ocrb]
                if self._count_up:
                    data[tcnt] = cur + 1
                else:
                    data[tcnt] = cur - 1 if cur > 0 else 0
            elif ctc and cur == ocra_val:
                data[tcnt] = 0
            elif fast:
                if cur >= top:
                    data[tcnt] = 0
                    data[tifr] |= 0x01
                    if outputs:
                        if rule_a is not None:
                            self._oc_apply(0, rule_a[2], when)
                        if rule_b is not None:
                            self._oc_apply(1, rule_b[2], when)
                    active[0] = data[ocra]  # OCR buffers are loaded at BOTTOM
                    active[1] = data[ocrb]
                else:
                    data[tcnt] = cur + 1
            else:
                nxt = (cur + 1) & 0xFF
                data[tcnt] = nxt
                if nxt == 0:
                    data[tifr] |= 0x01
            when += step


class _Timer16(_TimerBase):
    """16-bit timer covering all sixteen waveform generation modes: counting
    sequence, the TOV, OCF and ICF flags and the OCR double buffering of the
    PWM modes. The OCnx output pins are not modelled.

    Measured on a real ATmega2560: every mode has a period of TOP + 1 timer
    clocks (2 * TOP in the phase-correct modes), compare flags are set on the
    clock after the match, and a TCNT write blocks the match on the next clock.
    """

    _N = 1
    CHANNELS = 3

    # WGMn3:0 -> (counting, TOP, where the OCR buffers are loaded): TOP is a fixed
    # value, "ocra" or "icr".
    _MODES = {
        0: ("normal", None, None),
        1: ("phase", 0x00FF, "top"),
        2: ("phase", 0x01FF, "top"),
        3: ("phase", 0x03FF, "top"),
        4: ("ctc", "ocra", None),
        5: ("fast", 0x00FF, "bottom"),
        6: ("fast", 0x01FF, "bottom"),
        7: ("fast", 0x03FF, "bottom"),
        8: ("phase", "icr", "bottom"),
        9: ("phase", "ocra", "bottom"),
        10: ("phase", "icr", "top"),
        11: ("phase", "ocra", "top"),
        12: ("ctc", "icr", None),
        13: ("normal", None, None),
        14: ("fast", "icr", "bottom"),
        15: ("fast", "ocra", "bottom"),
    }

    def __init__(self) -> None:
        super().__init__()
        n = self._N
        self._tccra = getattr(self, f"DATA_TCCR{n}A")
        self._tccrb = getattr(self, f"DATA_TCCR{n}B")
        self._tcnt = getattr(self, f"DATA_TCNT{n}L")
        self._icr = getattr(self, f"DATA_ICR{n}L")
        self._ocra = getattr(self, f"DATA_OCR{n}AL")
        self._ocrb = getattr(self, f"DATA_OCR{n}BL")
        self._ocrc = getattr(self, f"DATA_OCR{n}CL")
        self._tifr = 0x20 + getattr(self, f"IO_TIFR{n}")

    def _clock_select(self, data: bytearray) -> int:
        return data[self._tccrb] & 0x7

    def advance(self, cycles: int, data: bytearray, prescaler: int | None = None, now: int = 0) -> None:
        if cycles <= 0:
            return
        div = self._PRESCALE.get(data[self._tccrb] & 0x7)
        if div is None:
            return
        first = self._first_tick_offset(div, prescaler)
        ticks = self._ticks(cycles, div, prescaler)
        if ticks:
            self._run_ticks(ticks, data, now + first, div)

    def oc_rules(self, data: bytearray) -> list:
        wgm = (((data[self._tccrb] >> 3) & 0x3) << 2) | (data[self._tccra] & 0x3)
        kind = self._MODES[wgm][0]
        a = data[self._tccra]
        # COMnA = 1 in a PWM mode toggles OCnA in modes 9, 11, 14 and 15 only.
        return [
            self._oc_rule(kind, (a >> 6) & 3, wgm in (9, 11, 14, 15)),
            self._oc_rule(kind, (a >> 4) & 3, False),
            self._oc_rule(kind, (a >> 2) & 3, False),
        ]

    def _is_pwm_mode(self, data: bytearray) -> bool:
        return self._MODES[(((data[self._tccrb] >> 3) & 0x3) << 2) | (data[self._tccra] & 0x3)][2] is not None

    def _load_ocr(self, data: bytearray) -> None:
        active = self._ocr_active
        ocra, ocrb, ocrc = self._ocra, self._ocrb, self._ocrc
        active[0] = data[ocra] | (data[ocra + 1] << 8)
        active[1] = data[ocrb] | (data[ocrb + 1] << 8)
        active[2] = data[ocrc] | (data[ocrc + 1] << 8)

    def _run_ticks(self, ticks: int, data: bytearray, when: int = 0, step: int = 1) -> None:
        kind, top_src, update = self._MODES[(((data[self._tccrb] >> 3) & 0x3) << 2) | (data[self._tccra] & 0x3)]
        rules = self.oc_rules(data) if data[self._tccra] & 0xFC else None
        phase = kind == "phase"
        tcnt = self._tcnt
        tifr = self._tifr
        icr = self._icr
        icr_top = top_src == "icr"
        pwm = update is not None
        active = self._ocr_active
        if not pwm or not self._was_pwm:
            self._load_ocr(data)
        self._was_pwm = pwm

        for _ in range(ticks):
            cur = data[tcnt] | (data[tcnt + 1] << 8)
            if not pwm:
                self._load_ocr(data)
            ocra_val = active[0]
            if kind != "normal":
                if top_src == "ocra":
                    top = ocra_val
                elif icr_top:
                    top = data[icr] | (data[icr + 1] << 8)
                else:
                    top = top_src
            turned = False
            if phase:
                # The direction turns at BOTTOM and TOP before the compare outputs act,
                # so OCR = TOP counts as a match on the way down.
                if cur == 0:
                    data[tifr] |= 0x01
                    self._count_up = True
                    if update == "bottom":
                        self._load_ocr(data)
                        ocra_val = active[0]
                        if rules is not None:
                            for channel in (0, 1, 2):
                                self._oc_force(channel, rules[channel], True, when)
                turned = self._count_up and cur >= top
                if turned:
                    self._count_up = False
                    if icr_top:
                        data[tifr] |= 0x20
            if self._compare_block:
                self._compare_block = False
            else:
                direction = 0 if self._count_up or not phase else 1
                if cur == ocra_val:
                    data[tifr] |= 0x02
                    if rules is not None and rules[0] is not None:
                        self._oc_apply(0, rules[0][direction], when)
                if cur == active[1]:
                    data[tifr] |= 0x04
                    if rules is not None and rules[1] is not None:
                        self._oc_apply(1, rules[1][direction], when)
                if cur == active[2]:
                    data[tifr] |= 0x08
                    if rules is not None and rules[2] is not None:
                        self._oc_apply(2, rules[2][direction], when)

            if kind == "normal":
                nxt = (cur + 1) & 0xFFFF
                if nxt == 0:
                    data[tifr] |= 0x01
            elif kind == "ctc":
                if cur == top:
                    nxt = 0
                    if icr_top:
                        data[tifr] |= 0x20
                else:
                    nxt = (cur + 1) & 0xFFFF
                    if nxt == 0:
                        data[tifr] |= 0x01
            elif kind == "fast":
                if cur >= top:
                    nxt = 0
                    data[tifr] |= 0x01
                    if icr_top:
                        data[tifr] |= 0x20
                    if rules is not None:
                        for channel in (0, 1, 2):
                            if rules[channel] is not None:
                                self._oc_apply(channel, rules[channel][2], when)
                    self._load_ocr(data)
                else:
                    nxt = cur + 1
            else:  # phase-correct: up to TOP, down to BOTTOM
                if turned and update == "top":
                    if rules is not None:
                        for channel in (0, 1, 2):
                            self._oc_force(channel, rules[channel], active[channel] >= top, when)
                    self._load_ocr(data)
                if self._count_up:
                    nxt = cur + 1
                else:
                    nxt = cur - 1 if cur > 0 else 0

            data[tcnt] = nxt & 0xFF
            data[tcnt + 1] = (nxt >> 8) & 0xFF
            when += step


class Timer0(_Timer8):
    """Timer/Counter0 (8-bit, see _Timer8)."""

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

    _REGS = (0x20 + IO_TCCR0A, 0x20 + IO_TCCR0B, 0x20 + IO_TCNT0, 0x20 + IO_OCR0A, 0x20 + IO_OCR0B, 0x20 + IO_TIFR0)


class Timer1(_Timer16):
    """Timer/Counter1 (16-bit, see _Timer16)."""

    _N = 1

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


class Timer2(_Timer8):
    """Timer/Counter2 (8-bit, see _Timer8). It has its own prescaler; with ASSR.AS2
    set the 32.768 kHz crystal clock is approximated as CPU clock / 128."""

    SHARED_PRESCALER = False

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

    EXTERNAL_CLOCK = False  # CS = 6 / 7 are clk/256 and clk/1024 on Timer2
    _REGS = (DATA_TCCR2A, DATA_TCCR2B, DATA_TCNT2, DATA_OCR2A, DATA_OCR2B, 0x20 + IO_TIFR2)

    def _divisor(self, data: bytearray) -> int | None:
        div = self._PRESCALE.get(data[self.DATA_TCCR2B] & 0x7)
        if div is not None and ((data[self.DATA_ASSR] >> self.AS2_BIT) & 1) == 1:
            div *= self._ASYNC_SCALE
        return div

    def advance(self, cycles: int, data: bytearray, prescaler: int | None = None, now: int = 0) -> None:
        super().advance(cycles, data, None, now)


class Timer3(_Timer16):
    """Timer/Counter3 (16-bit, see _Timer16)."""

    _N = 3

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


class Timer4(_Timer16):
    """Timer/Counter4 (16-bit, see _Timer16)."""

    _N = 4

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


class Timer5(_Timer16):
    """Timer/Counter5 (16-bit, see _Timer16)."""

    _N = 5

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
        # After a watchdog reset the watchdog stays enabled at the shortest timeout:
        # WDRF forces WDE until the firmware clears MCUSR.
        data[self.DATA_WDTCSR] = (1 << self.WDE_BIT) if watchdog_reset else 0

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
            if data[self.DATA_MCUSR] & (1 << self.WDRF_BIT):
                nxt |= 1 << self.WDE_BIT  # WDE can't be cleared while WDRF is set
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
    """USART transmitter with real frame timing, and a simple receiver.

    The baud-rate generator divides the CPU clock by UBRR + 1 and restarts when
    UBRRnL is written. A byte written to UDR moves to the shift register at once
    if that is idle (UDRE stays set); its start bit begins on the next generator
    tick and each bit lasts 16 ticks (8 with U2X). TXC is set at the end of the
    frame when no further byte is waiting. Received bytes are injected whole.
    """

    DATA_UCSRA = 0
    DATA_UCSRB = 0
    DATA_UCSRC = 0
    DATA_UBRRL = 0
    DATA_UBRRH = 0
    DATA_UDR = 0

    UDRE_BIT = 5
    TXC_BIT = 6
    RXC_BIT = 7
    RXCIE_BIT = 7
    TXCIE_BIT = 6
    UDRIE_BIT = 5
    TXEN_BIT = 3
    RXEN_BIT = 4

    # Fitted to a real ATmega2560 (examples/hwcheck, uf2_*, ut_* and uq_*): the
    # generator restarts two cycles after the UBRRnL write, a byte written less
    # than two cycles before a tick waits for the next one, and a byte waiting
    # in UDR moves to the shift register (setting UDRE) three cycles before TXC
    # time. Frame length and tick alignment match the chip; the exact cycle on
    # which a polled write lands after earlier output does not always.
    BAUD_RESTART_OFFSET = 2
    TX_MIN_WAIT = 2
    UDRE_LEAD_CYCLES = 3

    def __init__(self) -> None:
        self.tx_log: list[int] = []
        self._shift_queue: list[int] = []  # byte being shifted out, then the one handed over
        self._udr_byte: int | None = None  # byte waiting in UDR
        self._tx_remaining = 0
        self._baud_cycles = 0  # cycles since the baud-rate generator restarted
        self._rx_fifo: list[int] = []

    @property
    def _pending_tx(self) -> list[int]:
        """Bytes still in the transmitter (shift register first)."""
        return self._shift_queue + ([] if self._udr_byte is None else [self._udr_byte])

    def reset(self, data: bytearray) -> None:
        self.tx_log.clear()
        self._shift_queue.clear()
        self._udr_byte = None
        self._tx_remaining = 0
        self._baud_cycles = 0
        self._rx_fifo.clear()
        data[self.DATA_UCSRA] |= 1 << self.UDRE_BIT
        data[self.DATA_UCSRC] = 0x06  # 8 data bits

    def restart_baud_generator(self) -> None:
        self._baud_cycles = self.BAUD_RESTART_OFFSET

    def _tick_cycles(self, data: bytearray) -> int:
        return (data[self.DATA_UBRRL] | ((data[self.DATA_UBRRH] & 0x0F) << 8)) + 1

    def frame_cycles(self, data: bytearray) -> int:
        """CPU cycles of one frame with the current UCSRnA/B/C and UBRR settings."""
        ucsrc = data[self.DATA_UCSRC]
        size = ((ucsrc >> 1) & 0x03) | (((data[self.DATA_UCSRB] >> 2) & 1) << 2)
        data_bits = {0: 5, 1: 6, 2: 7, 3: 8, 7: 9}.get(size, 8)
        bits = 1 + data_bits + (1 if (ucsrc >> 4) & 0x03 else 0) + (2 if (ucsrc >> 3) & 1 else 1)
        ticks_per_bit = 8 if (data[self.DATA_UCSRA] >> 1) & 1 else 16
        return bits * ticks_per_bit * self._tick_cycles(data)

    def write_udr(self, value: int, data: bytearray) -> None:
        data[self.DATA_UDR] = value & 0xFF

        if ((data[self.DATA_UCSRB] >> self.TXEN_BIT) & 1) == 0:
            return

        if not self._shift_queue:
            # Idle: straight into the shift register; the frame starts on the next tick.
            tick = self._tick_cycles(data)
            wait = (tick - self._baud_cycles % tick) % tick
            if wait < self.TX_MIN_WAIT:
                wait += tick
            self._shift_queue.append(value & 0xFF)
            self._tx_remaining = wait + self.frame_cycles(data)
        else:
            self._udr_byte = value & 0xFF
            data[self.DATA_UCSRA] &= ~(1 << self.UDRE_BIT)

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
        """Return True while a byte is being shifted out."""
        return bool(self._shift_queue)

    def advance(self, cycles: int, data: bytearray) -> None:
        if cycles <= 0:
            return
        self._baud_cycles += cycles
        if not self._shift_queue:
            return

        self._tx_remaining -= cycles
        if self._udr_byte is not None and self._tx_remaining <= self.UDRE_LEAD_CYCLES:
            # The waiting byte follows without a gap.
            self._shift_queue.append(self._udr_byte)
            self._udr_byte = None
            data[self.DATA_UCSRA] |= 1 << self.UDRE_BIT
        while self._shift_queue and self._tx_remaining <= 0:
            self.tx_log.append(self._shift_queue.pop(0))
            if self._shift_queue:
                self._tx_remaining += self.frame_cycles(data)
            else:
                data[self.DATA_UCSRA] |= 1 << self.TXC_BIT


class UART0(UARTBase):
    DATA_UCSRA = DATA_UCSR0A = 0x00C0
    DATA_UCSRB = DATA_UCSR0B = 0x00C1
    DATA_UCSRC = DATA_UCSR0C = 0x00C2
    DATA_UBRRL = DATA_UBRR0L = 0x00C4
    DATA_UBRRH = DATA_UBRR0H = 0x00C5
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
    DATA_UCSRC = DATA_UCSR1C = 0x00CA
    DATA_UBRRL = DATA_UBRR1L = 0x00CC
    DATA_UBRRH = DATA_UBRR1H = 0x00CD
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
    DATA_UCSRC = DATA_UCSR2C = 0x00D2
    DATA_UBRRL = DATA_UBRR2L = 0x00D4
    DATA_UBRRH = DATA_UBRR2H = 0x00D5
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
    DATA_UCSRC = DATA_UCSR3C = 0x0132
    DATA_UBRRL = DATA_UBRR3L = 0x0134
    DATA_UBRRH = DATA_UBRR3H = 0x0135
    DATA_UDR = DATA_UDR3 = 0x0136

    UDRE_BIT = UDRE3_BIT = 5
    TXC_BIT = TXC3_BIT = 6
    RXC_BIT = RXC3_BIT = 7
    RXCIE_BIT = RXCIE3_BIT = 7
    TXCIE_BIT = TXCIE3_BIT = 6
    UDRIE_BIT = UDRIE3_BIT = 5
    TXEN_BIT = TXEN3_BIT = 3
    RXEN_BIT = RXEN3_BIT = 4
