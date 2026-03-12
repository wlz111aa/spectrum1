from time import sleep
import uasyncio as asyncio
from machine import I2C, Pin


class AS7341:
    """Minimal, robust AS7341 driver for MicroPython.

    - Supports providing an existing I2C object or creating one from SDA/SCL pins.
    - read_channels() returns dict with keys: F1..F8, CLEAR, NIR, DARK
    - Allows soft-scaling by `gain` and sets `atime_ms` (best-effort write to ATIME).
    """

    _I2C_ADDRESS = 0x39

    # Registers (subset used)
    _WHOAMI = 0x92
    _CHIP_ID = 0x09
    _ENABLE = 0x80
    _CONFIG = 0x70
    _LED = 0x74
    _ATIME = 0x81
    _ASTEP_L = 0xCA
    _ASTEP_H = 0xCB
    _ASTATUS = 0x94

    # SMUX input mapping indexes (used by smux routines)
    class SMUX_IN:
        NC_F3L = 0
        F1L_NC = 1
        NC_NC0 = 2
        NC_F8L = 3
        F6L_NC = 4
        F2L_F4L = 5
        NC_F5L = 6
        F7L_NC = 7
        NC_CL = 8
        NC_F5R = 9
        F7R_NC = 10
        NC_NC1 = 11
        NC_F2R = 12
        F4R_NC = 13
        F8R_F6R = 14
        NC_F3R = 15
        F1R_EXT_GPIO = 16
        EXT_INT_CR = 17
        NC_DARK = 18
        NIR_F = 19

    class SMUX_OUT:
        DISABLED = 0
        ADC0 = 1
        ADC1 = 2
        ADC2 = 3
        ADC3 = 4
        ADC4 = 5
        ADC5 = 6

    def __init__(self, i2c=None, scl=None, sda=None, addr: int = _I2C_ADDRESS, gain: int = 128, atime_ms: int = 100):
        """Create driver.

        Args:
            i2c: existing machine.I2C instance (optional). If None, `scl` and `sda` must be provided.
            scl, sda: pin numbers to create I2C(0) when `i2c` is None.
            addr: I2C device address (default 0x39).
            gain: logical gain (used as software scale factor). Default 128.
            atime_ms: target integration time in ms (best-effort write to ATIME register).
        """
        self.addr = addr
        self.gain = gain or 128
        self._scale = float(self.gain) / 128.0
        self.atime_ms = atime_ms or 100

        # init or use provided I2C
        if i2c is not None:
            self.i2c = i2c
        else:
            if scl is None or sda is None:
                raise ValueError('Either provide i2c or scl and sda pins')
            try:
                self.i2c = I2C(0, scl=Pin(scl), sda=Pin(sda), freq=400000)
            except Exception:
                # try fallback to default constructor
                try:
                    self.i2c = I2C(0)
                except Exception:
                    self.i2c = None

        # apply basic defaults to device where possible (non-fatal)
        try:
            # best-effort write ATIME; guard with try/except so driver never crashes here
            atime_reg = int(max(1, min(255, int(self.atime_ms))))
            self._write_reg(self._ATIME, atime_reg)
            # set some default ASTEP to a reasonable value (existing code used 0x03E7)
            self._write_reg(self._ASTEP_L, 0xE7)
            self._write_reg(self._ASTEP_H, 0x03)
            # minimal configuration: disable fancy features
            self._write_reg(self._CONFIG, 0x00)
            self._write_reg(self._LED, 0x00)
            # ensure chip power bit set (bit0 in ENABLE)
            self._set_enable_bit(0, True)
        except Exception:
            # Any failure here should not break driver construction
            pass

    # --- low level i2c helpers (robust) ---
    def _write_reg(self, reg: int, val: int):
        try:
            if self.i2c is None:
                return False
            # some MicroPython builds accept writeto_mem; fallback to writeto
            try:
                self.i2c.writeto_mem(self.addr, reg & 0xFF, bytes([val & 0xFF]))
            except Exception:
                self.i2c.writeto(self.addr, bytes([reg & 0xFF, val & 0xFF]))
            return True
        except Exception:
            return False

    def _read_reg(self, reg: int) -> int:
        try:
            if self.i2c is None:
                return 0
            try:
                b = self.i2c.readfrom_mem(self.addr, reg & 0xFF, 1)
                return b[0]
            except Exception:
                # some ports may not implement readfrom_mem
                data = self.i2c.readfrom(self.addr, 2)
                if data:
                    return data[0]
                return 0
        except Exception:
            return 0

    def _read_block(self, reg: int, n: int) -> bytes:
        try:
            if self.i2c is None:
                return bytes([0]) * n
            try:
                return self.i2c.readfrom_mem(self.addr, reg & 0xFF, n)
            except Exception:
                # fallback: do a generic read (may not work on all firmwares)
                return self.i2c.readfrom(self.addr, n)
        except Exception:
            return bytes([0]) * n

    def _set_enable_bit(self, bit: int, value: bool):
        try:
            cur = self._read_reg(self._ENABLE)
            if value:
                cur |= (1 << bit)
            else:
                cur &= ~(1 << bit)
            self._write_reg(self._ENABLE, cur)
        except Exception:
            pass

    def _set_smux_command(self, cmd: int):
        # Best-effort: write CFG6 bits if available (register 0xAF may not exist on some firmwares)
        CFG6 = 0xAF
        try:
            cur = self._read_reg(CFG6)
            cur &= ~(0x03 << 3)
            cur |= ((cmd & 0x03) << 3)
            self._write_reg(CFG6, cur)
        except Exception:
            pass

    def _set_smux(self, smux_addr: int, out1: int, out2: int):
        try:
            smux_byte = ((out2 & 0x0F) << 4) | (out1 & 0x0F)
            # SMUX registers are at 0x00..0x13
            self._write_reg(smux_addr & 0xFF, smux_byte)
        except Exception:
            pass

    def _read_all_channels(self):
        # Reading ASTATUS latches 12 spectral bytes; read 13 bytes starting there
        try:
            raw = self._read_block(self._ASTATUS, 13)
            if not raw or len(raw) < 13:
                return [0] * 6
            vals = []
            for i in range(6):
                lo = raw[1 + i * 2]
                hi = raw[1 + i * 2 + 1]
                vals.append((hi << 8) | lo)
            return vals
        except Exception:
            return [0] * 6

    # SMUX configurations for two reads
    def _f1f4_clear_nir(self):
        S = self.SMUX_IN
        O = self.SMUX_OUT
        try:
            self._set_smux(S.NC_F3L, O.DISABLED, O.ADC2)
            self._set_smux(S.F1L_NC, O.ADC0, O.DISABLED)
            self._set_smux(S.NC_NC0, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F8L, O.DISABLED, O.DISABLED)
            self._set_smux(S.F6L_NC, O.DISABLED, O.DISABLED)
            self._set_smux(S.F2L_F4L, O.ADC1, O.ADC3)
            self._set_smux(S.NC_F5L, O.DISABLED, O.DISABLED)
            self._set_smux(S.F7L_NC, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_CL, O.DISABLED, O.ADC4)
            self._set_smux(S.NC_F5R, O.DISABLED, O.DISABLED)
            self._set_smux(S.F7R_NC, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_NC1, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F2R, O.DISABLED, O.ADC1)
            self._set_smux(S.F4R_NC, O.ADC3, O.DISABLED)
            self._set_smux(S.F8R_F6R, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F3R, O.DISABLED, O.ADC2)
            self._set_smux(S.F1R_EXT_GPIO, O.ADC0, O.DISABLED)
            self._set_smux(S.EXT_INT_CR, O.DISABLED, O.ADC4)
            self._set_smux(S.NC_DARK, O.DISABLED, O.DISABLED)
            self._set_smux(S.NIR_F, O.ADC5, O.DISABLED)
        except Exception:
            pass

    def _f5f8_clear_nir(self):
        S = self.SMUX_IN
        O = self.SMUX_OUT
        try:
            self._set_smux(S.NC_F3L, O.DISABLED, O.DISABLED)
            self._set_smux(S.F1L_NC, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_NC0, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F8L, O.DISABLED, O.ADC3)
            self._set_smux(S.F6L_NC, O.ADC1, O.DISABLED)
            self._set_smux(S.F2L_F4L, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F5L, O.DISABLED, O.ADC0)
            self._set_smux(S.F7L_NC, O.ADC2, O.DISABLED)
            self._set_smux(S.NC_CL, O.DISABLED, O.ADC4)
            self._set_smux(S.NC_F5R, O.DISABLED, O.ADC0)
            self._set_smux(S.F7R_NC, O.ADC2, O.DISABLED)
            self._set_smux(S.NC_NC1, O.DISABLED, O.DISABLED)
            self._set_smux(S.NC_F2R, O.DISABLED, O.DISABLED)
            self._set_smux(S.F4R_NC, O.DISABLED, O.DISABLED)
            self._set_smux(S.F8R_F6R, O.ADC3, O.ADC1)
            self._set_smux(S.NC_F3R, O.DISABLED, O.DISABLED)
            self._set_smux(S.F1R_EXT_GPIO, O.DISABLED, O.DISABLED)
            self._set_smux(S.EXT_INT_CR, O.DISABLED, O.ADC4)
            self._set_smux(S.NC_DARK, O.DISABLED, O.DISABLED)
            self._set_smux(S.NIR_F, O.ADC5, O.DISABLED)
        except Exception:
            pass

    # --- public API ---
    def read_channels(self) -> dict:
        """Read all 11 logical channels and return a dict with keys:
        F1,F2,F3,F4,F5,F6,F7,F8,CLEAR,NIR,DARK

        This function is robust: it traps exceptions and returns zeros on failure.
        The returned numeric values are scaled by the configured `gain` (software scaling).
        """
        try:
            # --- Read F1..F4 group ---
            # 1. Disable SP_EN (Bit 1)
            self._set_enable_bit(1, False)
            # 2. Write SMUX configuration to registers
            self._f1f4_clear_nir()
            # 3. Set SMUX_CMD = Write (2) to CFG6
            self._set_smux_command(2)
            # 4. Enable SMUXEN (Bit 4) to start loading
            self._set_enable_bit(4, True)
            # 5. Wait for SMUXEN to clear (self-clearing)
            # Simple timeout loop
            for _ in range(100):
                if not (self._read_reg(self._ENABLE) & 0x10):
                    break
                sleep(0.001)
            # 6. Enable SP_EN (Bit 1) to start measurement
            self._set_enable_bit(1, True)
            # 7. Wait for integration
            # Calculate actual integration time: (ATIME + 1) * (ASTEP + 1) * 2.78碌s
            # ASTEP=999, ATIME=self.atime_ms (clamped)
            atime_reg = int(max(1, min(255, int(self.atime_ms))))
            wait_s = (atime_reg + 1) * 1000 * 2.78e-6
            sleep(wait_s + 0.05)
            # 8. Read Data
            vals1 = self._read_all_channels()  # 6 values: F1,F2,F3,F4,CLEAR,NIR

            # --- Read F5..F8 group ---
            # 1. Disable SP_EN
            self._set_enable_bit(1, False)
            # 2. Write SMUX configuration
            self._f5f8_clear_nir()
            # 3. Set SMUX_CMD = Write (2)
            self._set_smux_command(2)
            # 4. Enable SMUXEN
            self._set_enable_bit(4, True)
            # 5. Wait for SMUXEN
            for _ in range(100):
                if not (self._read_reg(self._ENABLE) & 0x10):
                    break
                sleep(0.001)
            # 6. Enable SP_EN
            self._set_enable_bit(1, True)
            # 7. Wait
            atime_reg = int(max(1, min(255, int(self.atime_ms))))
            wait_s = (atime_reg + 1) * 1000 * 2.78e-6
            sleep(wait_s + 0.05)
            # 8. Read Data
            vals2 = self._read_all_channels()  # 6 values: F5,F6,F7,F8,CLEAR,NIR

            # assemble, apply software gain scaling and ensure ints
            out = {
                'channel1': int(vals1[0]*self._scale),
                'channel2': int(vals1[1]*self._scale),
                'channel3': int(vals1[2]*self._scale),
                'channel4': int(vals1[3]*self._scale),
                'channel5': int(vals2[0]*self._scale),
                'channel6': int(vals2[1]*self._scale),
                'channel7': int(vals2[2]*self._scale),
                'channel8': int(vals2[3]*self._scale),
                'channel9': int(vals2[4]*self._scale),
                'channel10': int(vals2[5]*self._scale),
                'channel11': 0
            }
            return out
        except Exception:
            # on any error return zeros; never raise
            return {
                'F1': 0, 'F2': 0, 'F3': 0, 'F4': 0,
                'F5': 0, 'F6': 0, 'F7': 0, 'F8': 0,
                'CLEAR': 0, 'NIR': 0, 'DARK': 0,
            }

    def set_gain(self, gain: int):
        """Set logical gain (software scaling). Returns currently set gain."""
        try:
            self.gain = int(gain)
            self._scale = float(self.gain) / 128.0
        except Exception:
            pass
        return self.gain

    def set_atime(self, atime_ms: int):
        """Set integration time (best-effort write to ATIME register)."""
        try:
            self.atime_ms = int(atime_ms)
            atime_reg = int(max(1, min(255, self.atime_ms)))
            self._write_reg(self._ATIME, atime_reg)
            return True
        except Exception:
            return False

class AS7341_Async(AS7341):
    """Async version of AS7341 driver."""
    
    async def read_spectrum_async(self):
        try:
            # --- Read F1..F4 group ---
            # 1. Disable SP_EN (Bit 1)
            self._set_enable_bit(1, False)
            # 2. Write SMUX configuration
            self._f1f4_clear_nir()
            # 3. Set SMUX_CMD = Write (2)
            self._set_smux_command(2)
            # 4. Enable SMUXEN (Bit 4)
            self._set_enable_bit(4, True)
            # 5. Wait for SMUXEN to clear
            for _ in range(100):
                if not (self._read_reg(self._ENABLE) & 0x10):
                    break
                await asyncio.sleep(0.001)
            # 6. Enable SP_EN
            self._set_enable_bit(1, True)
            # 7. Wait for integration
            atime_reg = int(max(1, min(255, int(self.atime_ms))))
            wait_s = (atime_reg + 1) * 1000 * 2.78e-6
            await asyncio.sleep(wait_s + 0.05)
            # 8. Read Data
            vals1 = self._read_all_channels()
            
            # --- Read F5..F8 group ---
            # 1. Disable SP_EN
            self._set_enable_bit(1, False)
            # 2. Write SMUX configuration
            self._f5f8_clear_nir()
            # 3. Set SMUX_CMD = Write (2)
            self._set_smux_command(2)
            # 4. Enable SMUXEN
            self._set_enable_bit(4, True)
            # 5. Wait for SMUXEN
            for _ in range(100):
                if not (self._read_reg(self._ENABLE) & 0x10):
                    break
                await asyncio.sleep(0.001)
            # 6. Enable SP_EN
            self._set_enable_bit(1, True)
            # 7. Wait
            atime_reg = int(max(1, min(255, int(self.atime_ms))))
            wait_s = (atime_reg + 1) * 1000 * 2.78e-6
            await asyncio.sleep(wait_s + 0.05)
            # 8. Read Data
            vals2 = self._read_all_channels()

            return {
                'channel1': int(vals1[0]*self._scale),
                'channel2': int(vals1[1]*self._scale),
                'channel3': int(vals1[2]*self._scale),
                'channel4': int(vals1[3]*self._scale),
                'channel5': int(vals2[0]*self._scale),
                'channel6': int(vals2[1]*self._scale),
                'channel7': int(vals2[2]*self._scale),
                'channel8': int(vals2[3]*self._scale),
                'channel9': int(vals2[4]*self._scale),
                'channel10': int(vals2[5]*self._scale),
                'channel11': 0
            }
        except Exception as e:
            print("[AS7341] Async Read Error:", e)
            return {}

