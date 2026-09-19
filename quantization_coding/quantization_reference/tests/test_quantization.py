from __future__ import annotations

import unittest

from python_ref.fdk_tables import M_TAB_3_4_Q15, M_TAB_4_3_Q31
from python_ref.quantization_fixed import (
    inverse_quantize_line,
    quantize_line,
    quantize_spectrum,
)
from python_ref.quantization_float import quantize_line as quantize_float


class QuantizationTest(unittest.TestCase):
    def test_rom_dimensions(self) -> None:
        self.assertEqual(len(M_TAB_3_4_Q15), 512)
        self.assertEqual(len(M_TAB_4_3_Q31), 512)

    def test_zero_and_sign(self) -> None:
        for gain in (-40, -3, 0, 17):
            self.assertEqual(quantize_line(0, gain)[0], 0)
            positive = quantize_line(1 << 30, gain)[0]
            negative = quantize_line(-(1 << 30), gain)[0]
            self.assertEqual(negative, -positive)

    def test_fixed_tracks_float_with_lut_rounding(self) -> None:
        for gain in range(-40, 25):
            for raw in (1 << 20, 123456789, 1 << 30, (1 << 31) - 1):
                fixed = quantize_line(raw, gain)[0]
                floating = quantize_float(raw / 2**31, gain)
                self.assertLessEqual(abs(fixed - floating), 1)

    def test_inverse_half_scale_contract(self) -> None:
        q = quantize_line(1 << 30, -40)[0]
        reconstructed_half_q31 = inverse_quantize_line(q, -40)
        self.assertLess(abs(reconstructed_half_q31 - (1 << 29)), 1 << 23)

    def test_grouped_inactive_bands_remain_prefilled(self) -> None:
        result = quantize_spectrum(
            [1 << 30] * 16, [0, 4, 8, 12, 16], 4, 3, 4,
            -20, [0, 0, 0, 0], prefill=77)
        self.assertEqual(result.quantized_spectrum[12:], [77] * 4)
        self.assertEqual(result.active_line_mask[12:], [0] * 4)


if __name__ == "__main__":
    unittest.main()
