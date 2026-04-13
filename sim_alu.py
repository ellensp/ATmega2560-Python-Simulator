"""ATmega2560 emulator — ALU flag helpers mixin."""


class _AluMixin:
    # -----------------------------
    # SREG flag helpers
    # -----------------------------

    def _get_flag(self, bit: int) -> int:
        return (self.sreg >> bit) & 1

    def _set_flag(self, bit: int, value: int) -> None:
        if value:
            self.sreg |= 1 << bit
        else:
            self.sreg &= ~(1 << bit)

    def _update_sign_flag(self) -> None:
        n = self._get_flag(self.FLAG_N)
        v = self._get_flag(self.FLAG_V)
        self._set_flag(self.FLAG_S, n ^ v)

    # -----------------------------
    # ALU flag writers
    # -----------------------------

    def _write_logic_flags(self, result: int) -> None:
        r7 = (result >> 7) & 1
        self._set_flag(self.FLAG_V, 0)
        self._set_flag(self.FLAG_N, r7)
        self._set_flag(self.FLAG_Z, int((result & 0xFF) == 0))
        self._update_sign_flag()

    def _write_add_flags(self, rd_val: int, rr_val: int, result: int) -> None:
        rd7 = (rd_val >> 7) & 1
        rr7 = (rr_val >> 7) & 1
        r7 = (result >> 7) & 1

        rd3 = (rd_val >> 3) & 1
        rr3 = (rr_val >> 3) & 1
        r3 = (result >> 3) & 1

        h = (rd3 & rr3) | (rr3 & (1 - r3)) | ((1 - r3) & rd3)
        v = (rd7 & rr7 & (1 - r7)) | ((1 - rd7) & (1 - rr7) & r7)
        n = r7
        z = int((result & 0xFF) == 0)
        c = (rd7 & rr7) | (rr7 & (1 - r7)) | ((1 - r7) & rd7)

        self._set_flag(self.FLAG_H, int(bool(h)))
        self._set_flag(self.FLAG_V, int(bool(v)))
        self._set_flag(self.FLAG_N, n)
        self._set_flag(self.FLAG_Z, z)
        self._set_flag(self.FLAG_C, int(bool(c)))
        self._update_sign_flag()

    def _write_sub_flags(self, rd_val: int, rr_val: int, result: int, preserve_z: bool = False) -> None:
        rd7 = (rd_val >> 7) & 1
        rr7 = (rr_val >> 7) & 1
        r7 = (result >> 7) & 1

        rd3 = (rd_val >> 3) & 1
        rr3 = (rr_val >> 3) & 1
        r3 = (result >> 3) & 1

        h = ((1 - rd3) & rr3) | (rr3 & r3) | (r3 & (1 - rd3))
        v = (rd7 & (1 - rr7) & (1 - r7)) | ((1 - rd7) & rr7 & r7)
        n = r7
        z_raw = int((result & 0xFF) == 0)
        c = ((1 - rd7) & rr7) | (rr7 & r7) | (r7 & (1 - rd7))

        if preserve_z:
            z = self._get_flag(self.FLAG_Z) & z_raw
        else:
            z = z_raw

        self._set_flag(self.FLAG_H, int(bool(h)))
        self._set_flag(self.FLAG_V, int(bool(v)))
        self._set_flag(self.FLAG_N, n)
        self._set_flag(self.FLAG_Z, z)
        self._set_flag(self.FLAG_C, int(bool(c)))
        self._update_sign_flag()

    def _write_adc_flags(self, rd_val: int, rr_val: int, c_in: int, result: int) -> None:
        full = rd_val + rr_val + c_in
        h = int(((rd_val & 0x0F) + (rr_val & 0x0F) + c_in) > 0x0F)
        c = int(full > 0xFF)
        v = int((((~(rd_val ^ rr_val)) & (rd_val ^ result)) & 0x80) != 0)
        n = (result >> 7) & 1
        z = int((result & 0xFF) == 0)

        self._set_flag(self.FLAG_H, h)
        self._set_flag(self.FLAG_V, v)
        self._set_flag(self.FLAG_N, n)
        self._set_flag(self.FLAG_Z, z)
        self._set_flag(self.FLAG_C, c)
        self._update_sign_flag()

    def _write_sbc_flags(self, rd_val: int, rr_val: int, c_in: int, result: int, preserve_z: bool = False) -> None:
        borrow = int(rd_val < (rr_val + c_in))
        h = int((rd_val & 0x0F) < ((rr_val & 0x0F) + c_in))
        v = int((((rd_val ^ rr_val) & (rd_val ^ result)) & 0x80) != 0)
        n = (result >> 7) & 1
        z_raw = int((result & 0xFF) == 0)
        z = (self._get_flag(self.FLAG_Z) & z_raw) if preserve_z else z_raw

        self._set_flag(self.FLAG_H, h)
        self._set_flag(self.FLAG_V, v)
        self._set_flag(self.FLAG_N, n)
        self._set_flag(self.FLAG_Z, z)
        self._set_flag(self.FLAG_C, borrow)
        self._update_sign_flag()

    @staticmethod
    def _sign_extend(value: int, bits: int) -> int:
        sign = 1 << (bits - 1)
        mask = (1 << bits) - 1
        value &= mask
        return (value ^ sign) - sign

    @staticmethod
    def _clamp_u16(value: int) -> int:
        return value & 0xFFFF
