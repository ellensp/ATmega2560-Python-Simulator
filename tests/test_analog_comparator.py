import unittest

from sim_peripherals import Timer1
from sim import ATmega2560Emulator


class TestAnalogComparator(unittest.TestCase):
    def _new_emu(self) -> ATmega2560Emulator:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 128)
        return emu

    def test_aco_reflects_comparator_output(self) -> None:
        emu = self._new_emu()

        emu.set_analog_comparator_inputs(positive=5, negative=2)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACO_BIT) & 1, 1)

        emu.set_analog_comparator_inputs(positive=1, negative=3)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACO_BIT) & 1, 0)

    def test_analog_comparator_interrupt_dispatch_on_rising_output(self) -> None:
        emu = self._new_emu()
        emu._set_flag(emu.FLAG_I, 1)
        emu._data_write(
            emu.DATA_ACSR,
            (1 << emu.ACSR_ACIE_BIT) | (1 << emu.ACSR_ACIS0_BIT) | (1 << emu.ACSR_ACIS1_BIT),
        )

        emu.set_analog_comparator_inputs(positive=0, negative=1)
        emu.set_analog_comparator_inputs(positive=2, negative=1)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACI_BIT) & 1, 1)

        emu.step()

        self.assertEqual(emu.pc, emu.VECTOR_ANALOG_COMP)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACI_BIT) & 1, 0)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)

    def test_aci_write_one_to_clear(self) -> None:
        emu = self._new_emu()
        emu._data_write(emu.DATA_ACSR, 0)
        emu.set_analog_comparator_inputs(positive=4, negative=1)
        emu.set_analog_comparator_inputs(positive=0, negative=1)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACI_BIT) & 1, 1)

        emu._data_write(emu.DATA_ACSR, 1 << emu.ACSR_ACI_BIT)

        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACI_BIT) & 1, 0)

    def test_acbg_selects_internal_bandgap_as_positive_input(self) -> None:
        emu = self._new_emu()
        emu.set_analog_comparator_inputs(positive=0, negative=100)
        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACO_BIT) & 1, 0)

        emu._data_write(emu.DATA_ACSR, 1 << emu.ACSR_ACBG_BIT)

        self.assertEqual((emu.data[emu.DATA_ACSR] >> emu.ACSR_ACO_BIT) & 1, 1)

    def test_acic_triggers_timer1_capture_on_selected_edge(self) -> None:
        emu = self._new_emu()
        emu.data[Timer1.DATA_TCNT1L] = 0x34
        emu.data[Timer1.DATA_TCNT1H] = 0x12
        emu.data[Timer1.DATA_TCCR1B] = 1 << 6  # ICES1: capture on rising edge
        emu._data_write(emu.DATA_ACSR, 1 << emu.ACSR_ACIC_BIT)

        emu.set_analog_comparator_inputs(positive=0, negative=1)
        emu.set_analog_comparator_inputs(positive=3, negative=1)

        captured = emu.data[Timer1.DATA_ICR1L] | (emu.data[Timer1.DATA_ICR1H] << 8)
        self.assertEqual(captured, 0x1234)
        self.assertEqual((emu.data[0x20 + Timer1.IO_TIFR1] >> Timer1.ICF1_BIT) & 1, 1)


if __name__ == "__main__":
    unittest.main()
