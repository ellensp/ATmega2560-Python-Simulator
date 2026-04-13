import unittest

from avr_encoding import rjmp
from sim_peripherals import WatchdogTimer
from sim import ATmega2560Emulator


class TestWatchdog(unittest.TestCase):
    @staticmethod
    def _run_until(emu: ATmega2560Emulator, predicate, max_steps: int) -> None:
        for _ in range(max_steps):
            emu.step()
            if predicate():
                return

    def test_wdtcsr_timed_sequence_required_for_config(self) -> None:
        emu = ATmega2560Emulator()

        # Outside timed window, config writes are ignored.
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x08)  # WDE
        self.assertEqual((emu.data[WatchdogTimer.DATA_WDTCSR] >> WatchdogTimer.WDE_BIT) & 1, 0)

        # Timed sequence allows config update.
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x08)  # WDE
        self.assertEqual((emu.data[WatchdogTimer.DATA_WDTCSR] >> WatchdogTimer.WDE_BIT) & 1, 1)

    def test_wdtcsr_timed_window_expires(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([0x0000] * 16)

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE opens 4-cycle window

        # 5 cycles later, window is expired.
        for _ in range(5):
            emu.step()

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x40)  # WDIE write should be ignored
        self.assertEqual((emu.data[WatchdogTimer.DATA_WDTCSR] >> WatchdogTimer.WDIE_BIT) & 1, 0)

    def test_watchdog_interrupt_mode_dispatch(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)] + [0x0000] * 127)
        emu._set_flag(emu.FLAG_I, 1)

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x40)  # WDIE (interrupt-only)

        timeout = emu.watchdog._timeout_cycles(emu.data)
        self._run_until(emu, lambda: emu.pc == emu.VECTOR_WDT, timeout + 2000)

        self.assertEqual(emu.pc, emu.VECTOR_WDT)
        self.assertEqual((emu.sreg >> emu.FLAG_I) & 1, 0)
        self.assertEqual(emu.sp, 0x21FC)

    def test_watchdog_reset_mode_sets_mcusr_wdrf(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)] + [0x0000] * 127)
        emu.reg[5] = 0xA5

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x08)  # WDE (reset-only)

        timeout = emu.watchdog._timeout_cycles(emu.data)
        self._run_until(
            emu,
            lambda: ((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1) == 1,
            timeout + 2000,
        )

        self.assertEqual((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1, 1)
        self.assertEqual(emu.pc, 0)
        self.assertEqual(emu.reg[5], 0)

    def test_watchdog_combined_mode_interrupt_then_reset(self) -> None:
        emu = ATmega2560Emulator()
        emu.load_program_words([rjmp(-1)] + [0x0000] * 127)

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x48)  # WDIE|WDE

        timeout = emu.watchdog._timeout_cycles(emu.data)
        self._run_until(
            emu,
            lambda: ((emu.data[WatchdogTimer.DATA_WDTCSR] >> WatchdogTimer.WDIF_BIT) & 1) == 1,
            timeout + 2000,
        )

        self.assertEqual((emu.data[WatchdogTimer.DATA_WDTCSR] >> WatchdogTimer.WDIF_BIT) & 1, 1)
        self.assertEqual((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1, 0)

        self._run_until(
            emu,
            lambda: ((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1) == 1,
            timeout + 4000,
        )

        self.assertEqual((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1, 1)

    def test_wdr_instruction_kicks_watchdog_counter(self) -> None:
        emu = ATmega2560Emulator()
        program = [0x0000] * 300000
        program[100] = 0x95A8  # WDR
        emu.load_program_words(program)

        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x18)  # WDCE|WDE
        emu._data_write(WatchdogTimer.DATA_WDTCSR, 0x08)  # WDE

        for _ in range(150000):
            emu.step()

        # WDR at step ~100 should have prevented an early watchdog reset.
        self.assertEqual((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1, 0)

        timeout = emu.watchdog._timeout_cycles(emu.data)
        self._run_until(
            emu,
            lambda: ((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1) == 1,
            timeout + 200000,
        )

        self.assertEqual((emu.data[WatchdogTimer.DATA_MCUSR] >> WatchdogTimer.WDRF_BIT) & 1, 1)


if __name__ == "__main__":
    unittest.main()
