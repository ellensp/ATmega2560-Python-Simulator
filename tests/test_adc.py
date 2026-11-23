import unittest

from sim import ATmega2560Emulator


class TestADCController(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 256)
        return emu

    def test_conversion_completes_and_sets_result_right_adjusted(self) -> None:
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 0x02AB)

        emu._data_write(emu.DATA_ADMUX, 0x00)
        emu._data_write(emu.DATA_ADCSRA, (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT))

        for _ in range(13):
            emu.step()

        self.assertEqual(emu.data[emu.DATA_ADCL], 0xAB)
        self.assertEqual(emu.data[emu.DATA_ADCH], 0x02)
        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADSC_BIT) & 1, 0)
        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADIF_BIT) & 1, 1)

    def test_adif_write_one_to_clear(self) -> None:
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 0x0015)
        emu._data_write(emu.DATA_ADCSRA, (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT))

        for _ in range(13):
            emu.step()

        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADIF_BIT) & 1, 1)

        emu._data_write(emu.DATA_ADCSRA, 1 << emu.ADC_ADIF_BIT)
        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADIF_BIT) & 1, 0)

    def test_left_adjust_result_format(self) -> None:
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 0x02AB)
        emu._data_write(emu.DATA_ADMUX, 1 << emu.ADC_ADLAR_BIT)
        emu._data_write(emu.DATA_ADCSRA, (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT))

        for _ in range(13):
            emu.step()

        self.assertEqual(emu.data[emu.DATA_ADCH], 0xAA)
        self.assertEqual(emu.data[emu.DATA_ADCL], 0xC0)

    def test_conversion_does_not_start_when_adc_disabled(self) -> None:
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 0x03FF)
        emu._data_write(emu.DATA_ADCSRA, 1 << emu.ADC_ADSC_BIT)

        for _ in range(20):
            emu.step()

        self.assertEqual(emu.data[emu.DATA_ADCL], 0x00)
        self.assertEqual(emu.data[emu.DATA_ADCH], 0x00)
        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADIF_BIT) & 1, 0)

    def test_adc_interrupt_dispatch(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.set_adc_channel_value(0, 0x0101)

        emu._data_write(
            emu.DATA_ADCSRA,
            (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADIE_BIT) | (1 << emu.ADC_ADSC_BIT),
        )

        for _ in range(13):
            emu.step()

        self.assertEqual((emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADIF_BIT) & 1, 1)
        emu.step()  # one instruction later (hardware timing)
        self.assertEqual(emu.pc, emu.VECTOR_ADC)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)


if __name__ == "__main__":
    unittest.main()


class TestADCChannelSelect(unittest.TestCase):
    """All 16 channels, MUX5 routing correctness, and channel re-selection."""

    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 512)
        return emu

    def _read_adc_result(self, emu: ATmega2560Emulator) -> int:
        return emu.data[emu.DATA_ADCL] | (emu.data[emu.DATA_ADCH] << 8)

    def _convert(self, emu: ATmega2560Emulator, admux: int, adcsrb: int = 0, steps: int = 13) -> int:
        """Write ADCSRB/ADMUX, trigger a conversion, run *steps* NOP cycles, return result."""
        emu._data_write(emu.DATA_ADCSRB, adcsrb)
        emu._data_write(emu.DATA_ADMUX, admux)
        emu._data_write(emu.DATA_ADCSRA, (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT))
        for _ in range(steps):
            emu.step()
        return self._read_adc_result(emu)

    def test_all_channels_0_to_7(self) -> None:
        """Each channel 0-7 returns its own configured value (no MUX5)."""
        for ch in range(8):
            with self.subTest(ch=ch):
                emu = self._new_emu()
                emu.set_adc_channel_value(ch, ch * 111 + 10)   # unique: 10, 121, 232, …
                result = self._convert(emu, admux=ch, adcsrb=0)
                self.assertEqual(result, ch * 111 + 10)

    def test_all_channels_8_to_15_via_mux5(self) -> None:
        """Channels 8-15 routed via MUX5=1 in ADCSRB; each returns the correct value."""
        for ch in range(8, 16):
            with self.subTest(ch=ch):
                emu = self._new_emu()
                emu.set_adc_channel_value(ch, ch * 60 + 7)     # unique: 487, 547, …
                result = self._convert(emu, admux=ch & 0x07, adcsrb=1 << 3)
                self.assertEqual(result, ch * 60 + 7)

    def test_mux5_isolates_ch5_from_ch13(self) -> None:
        """
        Ch5 and ch13 both have MUX[2:0]=5; only MUX5 distinguishes them.
        Reading ch5 (MUX5=0) must return ch5's value; ch13 (MUX5=1) must
        return ch13's value.  This regression test covers the MUX5 mask bug.
        """
        # ch5 with MUX5=0
        emu = self._new_emu()
        emu.set_adc_channel_value(5, 111)
        emu.set_adc_channel_value(13, 999)
        self.assertEqual(self._convert(emu, admux=5, adcsrb=0), 111)

        # ch13 with MUX5=1
        emu2 = self._new_emu()
        emu2.set_adc_channel_value(5, 111)
        emu2.set_adc_channel_value(13, 999)
        self.assertEqual(self._convert(emu2, admux=5, adcsrb=1 << 3), 999)

    def test_mux5_isolates_ch0_from_ch8(self) -> None:
        """Ch0 (MUX5=0, MUX=0) and ch8 (MUX5=1, MUX=0) are distinct."""
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 200)
        emu.set_adc_channel_value(8, 800)
        self.assertEqual(self._convert(emu, admux=0, adcsrb=0), 200)

        emu2 = self._new_emu()
        emu2.set_adc_channel_value(0, 200)
        emu2.set_adc_channel_value(8, 800)
        self.assertEqual(self._convert(emu2, admux=0, adcsrb=1 << 3), 800)

    def test_channel_reselect_between_conversions(self) -> None:
        """Changing ADMUX+ADCSRB before re-asserting ADSC picks up the new channel."""
        emu = self._new_emu()
        emu.set_adc_channel_value(2, 300)
        emu.set_adc_channel_value(10, 700)

        # First conversion: ch2
        self.assertEqual(self._convert(emu, admux=2, adcsrb=0), 300)
        # Second conversion: ch10 (MUX5=1, MUX=2)
        self.assertEqual(self._convert(emu, admux=2, adcsrb=1 << 3), 700)

    def test_channel_values_do_not_bleed(self) -> None:
        """Reading ch0 does not return a value set on ch1 or ch8."""
        emu = self._new_emu()
        emu.set_adc_channel_value(0, 50)
        emu.set_adc_channel_value(1, 950)
        emu.set_adc_channel_value(8, 512)
        self.assertEqual(self._convert(emu, admux=0, adcsrb=0), 50)


class TestADCPrescaler(unittest.TestCase):
    """Conversion timing scales with ADPS; channel value is unaffected."""

    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 512)
        return emu

    def _start_conversion(self, emu: ATmega2560Emulator, adps: int) -> None:
        emu.set_adc_channel_value(0, 0x200)
        emu._data_write(
            emu.DATA_ADCSRA,
            (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT) | (adps & 0x07),
        )

    def _adsc(self, emu: ATmega2560Emulator) -> int:
        return (emu.data[emu.DATA_ADCSRA] >> emu.ADC_ADSC_BIT) & 1

    def test_adps0_completes_at_13_cycles(self) -> None:
        """ADPS=0b000 → scale ×1 → 13 CPU cycles."""
        emu = self._new_emu()
        self._start_conversion(emu, adps=0b000)
        for _ in range(12):
            emu.step()
        self.assertEqual(self._adsc(emu), 1, "should still be busy at cycle 12")
        emu.step()
        self.assertEqual(self._adsc(emu), 0, "should complete at cycle 13")

    def test_adps1_completes_at_26_cycles(self) -> None:
        """ADPS=0b001 → scale ×2 → 26 CPU cycles."""
        emu = self._new_emu()
        self._start_conversion(emu, adps=0b001)
        for _ in range(25):
            emu.step()
        self.assertEqual(self._adsc(emu), 1, "should still be busy at cycle 25")
        emu.step()
        self.assertEqual(self._adsc(emu), 0, "should complete at cycle 26")

    def test_adps2_completes_at_52_cycles(self) -> None:
        """ADPS=0b010 → scale ×4 → 52 CPU cycles."""
        emu = self._new_emu()
        self._start_conversion(emu, adps=0b010)
        for _ in range(51):
            emu.step()
        self.assertEqual(self._adsc(emu), 1, "should still be busy at cycle 51")
        emu.step()
        self.assertEqual(self._adsc(emu), 0, "should complete at cycle 52")

    def test_adps3_completes_at_104_cycles(self) -> None:
        """ADPS=0b011 → scale ×8 → 104 CPU cycles."""
        emu = self._new_emu()
        self._start_conversion(emu, adps=0b011)
        for _ in range(103):
            emu.step()
        self.assertEqual(self._adsc(emu), 1)
        emu.step()
        self.assertEqual(self._adsc(emu), 0)

    def test_prescaler_does_not_alter_result(self) -> None:
        """The sampled value is independent of which prescaler is chosen."""
        for adps in range(8):
            with self.subTest(adps=adps):
                cycles = 13 * (1 << adps)
                emu = ATmega2560Emulator()
                emu.load_program_words([0x0000] * (cycles + 8))
                emu.set_adc_channel_value(0, 0x3AB)
                emu._data_write(
                    emu.DATA_ADCSRA,
                    (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT) | adps,
                )
                for _ in range(cycles):
                    emu.step()
                result = emu.data[emu.DATA_ADCL] | (emu.data[emu.DATA_ADCH] << 8)
                self.assertEqual(result, 0x3AB)


class TestADCLeftAdjustHighChannels(unittest.TestCase):
    """ADLAR left-adjust format for channels 8-15."""

    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 512)
        return emu

    def _convert_left(self, emu: ATmega2560Emulator, ch: int, value: int) -> tuple[int, int]:
        """Set channel value, do ADLAR conversion, return (ADCH, ADCL)."""
        emu.set_adc_channel_value(ch, value)
        adcsrb = (1 << 3) if ch > 7 else 0          # MUX5
        admux  = (1 << emu.ADC_ADLAR_BIT) | (ch & 0x07)
        emu._data_write(emu.DATA_ADCSRB, adcsrb)
        emu._data_write(emu.DATA_ADMUX,  admux)
        emu._data_write(emu.DATA_ADCSRA, (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADSC_BIT))
        for _ in range(13):
            emu.step()
        return emu.data[emu.DATA_ADCH], emu.data[emu.DATA_ADCL]

    def test_adlar_channel_8_value_0x300(self) -> None:
        """0x300 left-adjusted: ADCH=0xC0, ADCL=0x00."""
        # 0x300 = 0b11_0000_0000 → >>2 = 0xC0; bottom 2 bits = 0 → ADCL=0
        adch, adcl = self._convert_left(self._new_emu(), ch=8, value=0x300)
        self.assertEqual(adch, 0xC0)
        self.assertEqual(adcl, 0x00)

    def test_adlar_channel_15_value_0x155(self) -> None:
        """0x155 left-adjusted: ADCH=0x55, ADCL=0x40 (bottom 2 bits = 0b01)."""
        # 0x155 = 0b01_0101_0101 → >>2 = 0x55; bottom 2 = 0b01 → ADCL = 0x40
        adch, adcl = self._convert_left(self._new_emu(), ch=15, value=0x155)
        self.assertEqual(adch, 0x55)
        self.assertEqual(adcl, 0x40)

    def test_adlar_channel_10_all_ones(self) -> None:
        """0x3FF (max) left-adjusted: ADCH=0xFF, ADCL=0xC0."""
        # 0x3FF = 0b11_1111_1111 → >>2 = 0xFF; bottom 2 = 0b11 → ADCL = 0xC0
        adch, adcl = self._convert_left(self._new_emu(), ch=10, value=0x3FF)
        self.assertEqual(adch, 0xFF)
        self.assertEqual(adcl, 0xC0)

    def test_adlar_channel_12_zero(self) -> None:
        """0 left-adjusted: ADCH=0x00, ADCL=0x00."""
        adch, adcl = self._convert_left(self._new_emu(), ch=12, value=0)
        self.assertEqual(adch, 0x00)
        self.assertEqual(adcl, 0x00)


class TestADCInterruptHighChannels(unittest.TestCase):
    """ADC interrupt dispatches correctly for channels 8-15."""

    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 512)
        return emu

    def _isr_convert(self, ch: int, value: int) -> ATmega2560Emulator:
        """Trigger an ISR-mode conversion on *ch*, run 13 steps, return emu."""
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu.set_adc_channel_value(ch, value)
        adcsrb = (1 << 3) if ch > 7 else 0
        emu._data_write(emu.DATA_ADCSRB, adcsrb)
        emu._data_write(emu.DATA_ADMUX, ch & 0x07)
        emu._data_write(
            emu.DATA_ADCSRA,
            (1 << emu.ADC_ADEN_BIT) | (1 << emu.ADC_ADIE_BIT) | (1 << emu.ADC_ADSC_BIT),
        )
        for _ in range(13):
            emu.step()
        return emu

    def test_isr_dispatch_channel_8(self) -> None:
        """ADC interrupt dispatches to VECTOR_ADC for channel 8."""
        emu = self._isr_convert(ch=8, value=0x1FF)
        result = emu.data[emu.DATA_ADCL] | (emu.data[emu.DATA_ADCH] << 8)
        self.assertEqual(result, 0x1FF)
        emu.step()  # one instruction later (hardware timing)
        self.assertEqual(emu.pc, emu.VECTOR_ADC)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)   # I-flag cleared on entry

    def test_isr_dispatch_channel_15(self) -> None:
        """ADC interrupt dispatches to VECTOR_ADC for channel 15 with full-scale value."""
        emu = self._isr_convert(ch=15, value=0x3FF)
        result = emu.data[emu.DATA_ADCL] | (emu.data[emu.DATA_ADCH] << 8)
        self.assertEqual(result, 0x3FF)
        emu.step()  # one instruction later (hardware timing)
        self.assertEqual(emu.pc, emu.VECTOR_ADC)

    def test_isr_dispatch_all_high_channels(self) -> None:
        """ISR fires and result is correct for every channel in the 8-15 range."""
        for ch in range(8, 16):
            with self.subTest(ch=ch):
                expected = ch * 51 + 3    # unique, stays ≤ 1023
                emu = self._isr_convert(ch=ch, value=expected)
                result = emu.data[emu.DATA_ADCL] | (emu.data[emu.DATA_ADCH] << 8)
                self.assertEqual(result, expected)
                emu.step()  # one instruction later (hardware timing)
                self.assertEqual(emu.pc, emu.VECTOR_ADC)
