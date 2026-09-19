"""Readable mathematical oracle for AAC-LC spectral quantization.

This model uses real-number pow operations.  It is intended for theory checks,
plots and gain-search experiments; the fixed model is the bit-level oracle.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

try:
    from .utils import load_case, q31_to_float, write_int_lines
except ImportError:
    from utils import load_case, q31_to_float, write_int_lines  # type: ignore


@dataclass(frozen=True)
class FloatBandSearch:
    gain: int
    distortion: float
    quantized: list[int]


def quantize_line(value: float, gain: int, dead_zone: bool = False) -> int:
    if value == 0.0:
        return 0
    rounding_offset = 0.23 if dead_zone else 0.4054
    # FDK's mdctSpectrum is Q1.31, so converting it to a real number removes
    # the fixed-point scale.  The remaining QSS term is exactly the expression
    # stated in quantize.cpp: |spec|^(3/4) * 2^(-3*gain/16).
    magnitude = abs(value) ** 0.75 * 2.0 ** (-3.0 * gain / 16.0)
    return (-1 if value < 0.0 else 1) * math.floor(magnitude + rounding_offset)


def inverse_quantize_line(quantized: int, gain: int) -> float:
    if quantized == 0:
        return 0.0
    magnitude = abs(quantized) ** (4.0 / 3.0) * 2.0 ** (gain / 4.0)
    return (-1.0 if quantized < 0 else 1.0) * magnitude


def quantize_band(values: Sequence[float], gain: int, dead_zone: bool = False) -> list[int]:
    return [quantize_line(value, gain, dead_zone) for value in values]


def band_distortion(values: Sequence[float], quantized: Sequence[int], gain: int) -> float:
    return sum((abs(value) - abs(inverse_quantize_line(q, gain))) ** 2
               for value, q in zip(values, quantized))


def search_band_gain(values: Sequence[float], allowed_distortion: float,
                     gain_min: int = -80, gain_max: int = 255,
                     dead_zone: bool = False) -> FloatBandSearch:
    """Choose the coarsest gain whose reconstruction stays below the threshold."""
    best: FloatBandSearch | None = None
    for gain in range(gain_min, gain_max + 1):
        quantized = quantize_band(values, gain, dead_zone)
        if max((abs(value) for value in quantized), default=0) > 8191:
            continue
        distortion = band_distortion(values, quantized, gain)
        if distortion <= allowed_distortion:
            best = FloatBandSearch(gain, distortion, quantized)
    if best is None:
        raise ValueError("no gain satisfies distortion and MAX_QUANT constraints")
    return best


def quantize_spectrum(spectrum_q31: Sequence[int], offsets: Sequence[int], sfb_cnt: int,
                      max_sfb_per_group: int, sfb_per_group: int,
                      global_gain: int, scalefactors: Sequence[int],
                      dead_zone: bool = False) -> list[int]:
    output = [0] * len(spectrum_q31)
    values = [q31_to_float(value) for value in spectrum_q31]
    for group_start in range(0, sfb_cnt, sfb_per_group):
        for local_sfb in range(max_sfb_per_group):
            sfb = group_start + local_sfb
            gain = global_gain - scalefactors[sfb]
            for line in range(offsets[sfb], offsets[sfb + 1]):
                output[line] = quantize_line(values[line], gain, dead_zone)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    case = load_case(args.case_dir)
    output = quantize_spectrum(
        case["mdct_spectrum"], case["sfb_offsets"], int(case["sfb_cnt"]),
        int(case["max_sfb_per_group"]), int(case["sfb_per_group"]),
        int(case["global_gain"]), case["scalefactors"],
        bool(case.get("dzone_quant_enable", 0)),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_int_lines(args.output_dir / "quantized_spectrum_float.txt", output)
    (args.output_dir / "summary_float.json").write_text(
        json.dumps({"model": "mathematical-float", "bit_exact": False}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
