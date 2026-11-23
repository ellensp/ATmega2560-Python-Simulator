import unittest

from sim import ATmega2560Emulator


class TestInterrupts(unittest.TestCase):
    def test_interrupt_entry_pushes_three_byte_return_address_and_adds_latency(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFF  # overflow on next tick
        emu.data[0x006E] = 0x01       # TIMSK0 TOIE0

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_OVF)
        self.assertEqual(emu.cycles, 6)  # 1 cycle NOP + 5 cycle interrupt latency (3-byte PC push)
        self.assertEqual(emu.sp, 0x21FC)
        self.assertEqual(emu.data[0x21FF], 0x01)  # return PC low byte
        self.assertEqual(emu.data[0x21FE], 0x00)  # return PC middle byte
        self.assertEqual(emu.data[0x21FD], 0x00)  # return PC high byte

    def test_timer0_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        # Ensure vector target exists in flash image.
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFE  # TCNT0 near overflow
        emu.data[0x006E] = 0x01       # TIMSK0 TOIE0

        emu.step()  # TCNT0 -> 0xFF
        self.assertEqual(emu.pc, 1)

        emu.step()  # TCNT0 -> 0x00 => TOV0 pending => service interrupt
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_OVF)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.sp, 0x21FC)

    def test_timer0_compa_has_priority_over_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFF  # next tick wraps to 0x00
        emu.data[0x20 + 0x27] = 0x00  # OCR0A
        emu.data[0x006E] = 0x03       # TIMSK0 OCIE0A + TOIE0

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)
        tifr0 = emu.data[0x20 + 0x15]
        self.assertEqual((tifr0 >> 1) & 1, 0)  # OCF0A cleared by service
        self.assertEqual(tifr0 & 1, 1)         # TOV0 remains pending

    def test_timer0_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0x00  # TCNT0
        emu.data[0x20 + 0x28] = 0x01  # OCR0B
        emu.data[0x006E] = 0x04       # TIMSK0 OCIE0B

        emu.step()  # TCNT0 -> 1 => OCF0B => service interrupt

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPB)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.sp, 0x21FC)

    def test_timer0_compa_compb_ovf_priority(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 64)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFF  # next tick wraps to 0x00
        emu.data[0x20 + 0x27] = 0x00  # OCR0A
        emu.data[0x20 + 0x28] = 0x00  # OCR0B
        emu.data[0x006E] = 0x07       # TIMSK0 OCIE0A + OCIE0B + TOIE0

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)
        tifr0 = emu.data[0x20 + 0x15]
        self.assertEqual((tifr0 >> 1) & 1, 0)  # OCF0A cleared by service
        self.assertEqual((tifr0 >> 2) & 1, 1)  # OCF0B still pending
        self.assertEqual(tifr0 & 1, 1)         # TOV0 still pending

    def test_reti_restores_pc_and_sets_i(self) -> None:
        emu = ATmega2560Emulator()
        # Vector has RETI, main line has NOP at return address.
        program = [0x0000] * 64
        program[emu.VECTOR_TIMER0_OVF] = 0x9518  # RETI
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x20 + 0x25] = 0x01  # TCCR0B clk/1
        emu.data[0x20 + 0x26] = 0xFF  # overflow on next tick
        emu.data[0x006E] = 0x01       # TIMSK0 TOIE0

        emu.step()  # Executes NOP at PC=0, then services overflow interrupt.
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_OVF)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

        emu.step()  # RETI
        self.assertEqual(emu.pc, 1)  # resume after interrupted instruction
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 1)

    def test_pending_interrupt_does_not_nest_without_sei(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x006E] = 0x02  # TIMSK0 OCIE0A
        emu.data[0x006F] = 0x01  # TIMSK1 TOIE1
        emu.data[0x20 + 0x15] |= 1 << 1  # OCF0A
        emu.data[0x20 + 0x16] |= 1 << 0  # TOV1

        emu.step()  # service Timer0 COMPA first
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)

        emu.step()  # execute ISR NOP with I=0, should not nest into Timer1
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA + 1)
        self.assertEqual((emu.data[0x20 + 0x16] >> 0) & 1, 1)  # TOV1 still pending

    def test_interrupt_can_nest_after_sei_inside_isr(self) -> None:
        emu = ATmega2560Emulator()
        program = [0x0000] * 128
        program[emu.VECTOR_TIMER0_COMPA] = 0x9478  # SEI
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x006E] = 0x02  # TIMSK0 OCIE0A
        emu.data[0x006F] = 0x01  # TIMSK1 TOIE1
        emu.data[0x20 + 0x15] |= 1 << 1  # OCF0A
        emu.data[0x20 + 0x16] |= 1 << 0  # TOV1

        emu.step()  # Timer0 COMPA
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)
        self.assertEqual(emu.sp, 0x21FC)

        emu.step()  # SEI executes; nested interrupt is deferred one instruction.
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA + 1)
        self.assertEqual(emu.sp, 0x21FC)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 1)

        emu.step()  # Next ISR instruction runs, then Timer1 OVF nests.
        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_OVF)
        self.assertEqual(emu.sp, 0x21F9)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_back_to_back_reti_dispatch_preserves_stack_integrity(self) -> None:
        emu = ATmega2560Emulator()
        program = [0x0000] * 128
        program[emu.VECTOR_TIMER0_COMPA] = 0x9518  # RETI
        program[emu.VECTOR_TIMER1_OVF] = 0x9518    # RETI
        emu.load_program_words(program)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x006E] = 0x02  # TIMSK0 OCIE0A
        emu.data[0x006F] = 0x01  # TIMSK1 TOIE1
        emu.data[0x20 + 0x15] |= 1 << 1  # OCF0A
        emu.data[0x20 + 0x16] |= 1 << 0  # TOV1

        emu.step()  # Timer0 COMPA service
        self.assertEqual(emu.sp, 0x21FC)
        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)

        emu.step()  # RETI from Timer0, then Timer1 OVF immediately services
        self.assertEqual(emu.sp, 0x21FC)
        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_OVF)

        emu.step()  # RETI from Timer1
        self.assertEqual(emu.sp, 0x21FF)
        self.assertEqual(emu.pc, 1)

    def test_timer1_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x0084] = 0xFF  # TCNT1L
        emu.data[0x0085] = 0xFF  # TCNT1H
        emu.data[0x006F] = 0x01  # TIMSK1 TOIE1

        emu.step()  # overflow -> service

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_OVF)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.sp, 0x21FC)

    def test_timer1_compa_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x0088] = 0x01  # OCR1AL
        emu.data[0x0089] = 0x00  # OCR1AH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H
        emu.data[0x006F] = 0x02  # TIMSK1 OCIE1A

        emu.step()  # compare match -> service

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_COMPA)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_timer1_compa_has_priority_over_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x0084] = 0xFF  # TCNT1L
        emu.data[0x0085] = 0xFF  # TCNT1H
        emu.data[0x0088] = 0x00  # OCR1AL
        emu.data[0x0089] = 0x00  # OCR1AH
        emu.data[0x006F] = 0x03  # TIMSK1 OCIE1A + TOIE1

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_COMPA)
        tifr1 = emu.data[0x20 + 0x16]
        self.assertEqual((tifr1 >> 1) & 1, 0)  # OCF1A cleared by service
        self.assertEqual(tifr1 & 1, 1)         # TOV1 remains pending

    def test_timer1_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x008A] = 0x01  # OCR1BL
        emu.data[0x008B] = 0x00  # OCR1BH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H
        emu.data[0x006F] = 0x04  # TIMSK1 OCIE1B

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_COMPB)

    def test_timer1_compc_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x008C] = 0x01  # OCR1CL
        emu.data[0x008D] = 0x00  # OCR1CH
        emu.data[0x0084] = 0x00  # TCNT1L
        emu.data[0x0085] = 0x00  # TCNT1H
        emu.data[0x006F] = 0x08  # TIMSK1 OCIE1C

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_COMPC)

    def test_timer1_capt_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x006F] = 0x20  # TIMSK1 ICIE1
        emu.trigger_timer1_capture(0x1234)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_CAPT)
        self.assertEqual(emu.data[0x0086], 0x34)
        self.assertEqual(emu.data[0x0087], 0x12)

    def test_timer1_capt_has_priority_over_compare_and_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0081] = 0x01  # TCCR1B clk/1
        emu.data[0x0084] = 0xFF
        emu.data[0x0085] = 0xFF
        emu.data[0x0088] = 0x00
        emu.data[0x0089] = 0x00
        emu.data[0x008A] = 0x00
        emu.data[0x008B] = 0x00
        emu.data[0x008C] = 0x00
        emu.data[0x008D] = 0x00
        emu.data[0x006F] = 0x2F  # ICIE1 + OCIE1A/B/C + TOIE1
        emu.trigger_timer1_capture(0xBEEF)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_CAPT)
        tifr1 = emu.data[0x20 + 0x16]
        self.assertEqual((tifr1 >> 5) & 1, 0)  # ICF1 cleared by service
        self.assertEqual((tifr1 >> 1) & 1, 1)  # OCF1A pending
        self.assertEqual((tifr1 >> 2) & 1, 1)  # OCF1B pending
        self.assertEqual((tifr1 >> 3) & 1, 1)  # OCF1C pending
        self.assertEqual(tifr1 & 1, 1)         # TOV1 pending

    def test_timer2_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00B1] = 0x01  # TCCR2B clk/1
        emu.data[0x00B2] = 0xFF  # TCNT2
        emu.data[0x0070] = 0x01  # TIMSK2 TOIE2

        emu.step()  # overflow -> service

        self.assertEqual(emu.pc, emu.VECTOR_TIMER2_OVF)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_timer2_compa_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00B1] = 0x01  # TCCR2B clk/1
        emu.data[0x00B3] = 0x01  # OCR2A
        emu.data[0x00B2] = 0x00  # TCNT2
        emu.data[0x0070] = 0x02  # TIMSK2 OCIE2A

        emu.step()  # compare match -> service

        self.assertEqual(emu.pc, emu.VECTOR_TIMER2_COMPA)

    def test_timer2_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00B1] = 0x01  # TCCR2B clk/1
        emu.data[0x00B4] = 0x01  # OCR2B
        emu.data[0x00B2] = 0x00  # TCNT2
        emu.data[0x0070] = 0x04  # TIMSK2 OCIE2B

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER2_COMPB)

    def test_timer2_compa_compb_ovf_priority(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00B1] = 0x01  # TCCR2B clk/1
        emu.data[0x00B2] = 0xFF  # next tick wraps to 0x00
        emu.data[0x00B3] = 0x00  # OCR2A
        emu.data[0x00B4] = 0x00  # OCR2B
        emu.data[0x0070] = 0x07  # TIMSK2 OCIE2A + OCIE2B + TOIE2

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER2_COMPA)
        tifr2 = emu.data[0x20 + 0x17]
        self.assertEqual((tifr2 >> 1) & 1, 0)  # OCF2A cleared by service
        self.assertEqual((tifr2 >> 2) & 1, 1)  # OCF2B still pending
        self.assertEqual(tifr2 & 1, 1)         # TOV2 still pending

    def test_timer3_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0091] = 0x01  # TCCR3B clk/1
        emu.data[0x0094] = 0xFF  # TCNT3L
        emu.data[0x0095] = 0xFF  # TCNT3H
        emu.data[0x0071] = 0x01  # TIMSK3 TOIE3

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_OVF)

    def test_timer3_compa_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0091] = 0x01  # TCCR3B clk/1
        emu.data[0x0098] = 0x01  # OCR3AL
        emu.data[0x0099] = 0x00  # OCR3AH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H
        emu.data[0x0071] = 0x02  # TIMSK3 OCIE3A

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_COMPA)

    def test_timer3_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0091] = 0x01  # TCCR3B clk/1
        emu.data[0x009A] = 0x01  # OCR3BL
        emu.data[0x009B] = 0x00  # OCR3BH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H
        emu.data[0x0071] = 0x04  # TIMSK3 OCIE3B

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_COMPB)

    def test_timer3_compc_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0091] = 0x01  # TCCR3B clk/1
        emu.data[0x009C] = 0x01  # OCR3CL
        emu.data[0x009D] = 0x00  # OCR3CH
        emu.data[0x0094] = 0x00  # TCNT3L
        emu.data[0x0095] = 0x00  # TCNT3H
        emu.data[0x0071] = 0x08  # TIMSK3 OCIE3C

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_COMPC)

    def test_timer3_capt_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0071] = 0x20  # TIMSK3 ICIE3
        emu.trigger_timer3_capture(0xCAFE)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_CAPT)
        self.assertEqual(emu.data[0x0096], 0xFE)
        self.assertEqual(emu.data[0x0097], 0xCA)

    def test_timer3_capt_has_priority_over_compare_and_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 192)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0091] = 0x01
        emu.data[0x0094] = 0xFF
        emu.data[0x0095] = 0xFF
        emu.data[0x0098] = 0x00
        emu.data[0x0099] = 0x00
        emu.data[0x009A] = 0x00
        emu.data[0x009B] = 0x00
        emu.data[0x009C] = 0x00
        emu.data[0x009D] = 0x00
        emu.data[0x0071] = 0x2F  # ICIE3 + OCIE3A/B/C + TOIE3
        emu.trigger_timer3_capture(0xBEEF)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER3_CAPT)
        tifr3 = emu.data[0x20 + 0x18]
        self.assertEqual((tifr3 >> 5) & 1, 0)  # ICF3 cleared by service
        self.assertEqual((tifr3 >> 1) & 1, 1)  # OCF3A pending
        self.assertEqual((tifr3 >> 2) & 1, 1)  # OCF3B pending
        self.assertEqual((tifr3 >> 3) & 1, 1)  # OCF3C pending
        self.assertEqual(tifr3 & 1, 1)         # TOV3 pending

    def test_timer4_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00A1] = 0x01
        emu.data[0x00A4] = 0xFF
        emu.data[0x00A5] = 0xFF
        emu.data[0x0072] = 0x01

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_OVF)

    def test_timer4_compa_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00A1] = 0x01
        emu.data[0x00A8] = 0x01
        emu.data[0x00A9] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00
        emu.data[0x0072] = 0x02

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_COMPA)

    def test_timer4_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00A1] = 0x01
        emu.data[0x00AA] = 0x01
        emu.data[0x00AB] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00
        emu.data[0x0072] = 0x04

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_COMPB)

    def test_timer4_compc_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00A1] = 0x01
        emu.data[0x00AC] = 0x01
        emu.data[0x00AD] = 0x00
        emu.data[0x00A4] = 0x00
        emu.data[0x00A5] = 0x00
        emu.data[0x0072] = 0x08

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_COMPC)

    def test_timer4_capt_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0072] = 0x20
        emu.trigger_timer4_capture(0xCAFE)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_CAPT)
        self.assertEqual(emu.data[0x00A6], 0xFE)
        self.assertEqual(emu.data[0x00A7], 0xCA)

    def test_timer4_capt_has_priority_over_compare_and_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x00A1] = 0x01
        emu.data[0x00A4] = 0xFF
        emu.data[0x00A5] = 0xFF
        emu.data[0x00A8] = 0x00
        emu.data[0x00A9] = 0x00
        emu.data[0x00AA] = 0x00
        emu.data[0x00AB] = 0x00
        emu.data[0x00AC] = 0x00
        emu.data[0x00AD] = 0x00
        emu.data[0x0072] = 0x2F
        emu.trigger_timer4_capture(0xBEEF)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_CAPT)
        tifr4 = emu.data[0x20 + 0x19]
        self.assertEqual((tifr4 >> 5) & 1, 0)
        self.assertEqual((tifr4 >> 1) & 1, 1)
        self.assertEqual((tifr4 >> 2) & 1, 1)
        self.assertEqual((tifr4 >> 3) & 1, 1)
        self.assertEqual(tifr4 & 1, 1)

    def test_timer5_overflow_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0121] = 0x01
        emu.data[0x0124] = 0xFF
        emu.data[0x0125] = 0xFF
        emu.data[0x0073] = 0x01

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_OVF)

    def test_timer5_compa_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0121] = 0x01
        emu.data[0x0128] = 0x01
        emu.data[0x0129] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00
        emu.data[0x0073] = 0x02

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_COMPA)

    def test_timer5_compb_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0121] = 0x01
        emu.data[0x012A] = 0x01
        emu.data[0x012B] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00
        emu.data[0x0073] = 0x04

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_COMPB)

    def test_timer5_compc_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0121] = 0x01
        emu.data[0x012C] = 0x01
        emu.data[0x012D] = 0x00
        emu.data[0x0124] = 0x00
        emu.data[0x0125] = 0x00
        emu.data[0x0073] = 0x08

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_COMPC)

    def test_timer5_capt_interrupt_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0073] = 0x20
        emu.trigger_timer5_capture(0xCAFE)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_CAPT)
        self.assertEqual(emu.data[0x0126], 0xFE)
        self.assertEqual(emu.data[0x0127], 0xCA)

    def test_timer5_capt_has_priority_over_compare_and_ovf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0121] = 0x01
        emu.data[0x0124] = 0xFF
        emu.data[0x0125] = 0xFF
        emu.data[0x0128] = 0x00
        emu.data[0x0129] = 0x00
        emu.data[0x012A] = 0x00
        emu.data[0x012B] = 0x00
        emu.data[0x012C] = 0x00
        emu.data[0x012D] = 0x00
        emu.data[0x0073] = 0x2F
        emu.trigger_timer5_capture(0xBEEF)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER5_CAPT)
        tifr5 = emu.data[0x20 + 0x1A]
        self.assertEqual((tifr5 >> 5) & 1, 0)
        self.assertEqual((tifr5 >> 1) & 1, 1)
        self.assertEqual((tifr5 >> 2) & 1, 1)
        self.assertEqual((tifr5 >> 3) & 1, 1)
        self.assertEqual(tifr5 & 1, 1)

    def test_cross_timer_priority_timer0_compa_beats_all_other_timer_compa(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)

        # Enable COMPA interrupt for Timer0..Timer5.
        emu.data[0x006E] = 0x02
        emu.data[0x006F] = 0x02
        emu.data[0x0070] = 0x02
        emu.data[0x0071] = 0x02
        emu.data[0x0072] = 0x02
        emu.data[0x0073] = 0x02

        # Mark all COMPA flags pending simultaneously.
        emu.data[0x20 + 0x15] |= 1 << 1
        emu.data[0x20 + 0x16] |= 1 << 1
        emu.data[0x20 + 0x17] |= 1 << 1
        emu.data[0x20 + 0x18] |= 1 << 1
        emu.data[0x20 + 0x19] |= 1 << 1
        emu.data[0x20 + 0x1A] |= 1 << 1

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER0_COMPA)
        self.assertEqual((emu.data[0x20 + 0x15] >> 1) & 1, 0)
        self.assertEqual((emu.data[0x20 + 0x16] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x17] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x18] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x19] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x1A] >> 1) & 1, 1)

    def test_cross_timer_priority_timer1_beats_timer2_to_timer5(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)

        emu.data[0x006F] = 0x02
        emu.data[0x0070] = 0x02
        emu.data[0x0071] = 0x02
        emu.data[0x0072] = 0x02
        emu.data[0x0073] = 0x02

        emu.data[0x20 + 0x16] |= 1 << 1
        emu.data[0x20 + 0x17] |= 1 << 1
        emu.data[0x20 + 0x18] |= 1 << 1
        emu.data[0x20 + 0x19] |= 1 << 1
        emu.data[0x20 + 0x1A] |= 1 << 1

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER1_COMPA)
        self.assertEqual((emu.data[0x20 + 0x16] >> 1) & 1, 0)
        self.assertEqual((emu.data[0x20 + 0x17] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x18] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x19] >> 1) & 1, 1)
        self.assertEqual((emu.data[0x20 + 0x1A] >> 1) & 1, 1)

    def test_cross_timer_priority_timer4_beats_timer5(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 320)

        emu._set_flag(emu.FLAG_I, 1)
        emu.data[0x0072] = 0x02
        emu.data[0x0073] = 0x02
        emu.data[0x20 + 0x19] |= 1 << 1
        emu.data[0x20 + 0x1A] |= 1 << 1

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_TIMER4_COMPA)
        self.assertEqual((emu.data[0x20 + 0x19] >> 1) & 1, 0)
        self.assertEqual((emu.data[0x20 + 0x1A] >> 1) & 1, 1)


if __name__ == "__main__":
    unittest.main()
