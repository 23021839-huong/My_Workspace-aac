"""FDK-oriented fixed-point reference for the AAC spectral quantizer.

The forward path mirrors libAACenc/src/quantize.cpp for the x86/ARM-style
ARCH_PREFER_MULT_32x16 configuration.  It deliberately preserves arithmetic
right shifts and the final int16 narrowing operation.  Range checking is a
separate step, just as it is in qc_main.cpp.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

try:
    from .fdk_tables import (
        M_TAB_3_4_Q15,
        M_TAB_4_3_Q31,
        QUANT_TABLE_E_Q15,
        QUANT_TABLE_Q_Q15,
        SPEC_EXP_MANT_Q31,
        SPEC_EXP_SHIFT,
    )
    from .utils import (
        clz32_positive,
        count_leading_bits_positive,
        fmult_div2_q15_q15,
        fmult_div2_q31_q15,
        fmult_q31,
        int16,
        int32,
        load_case,
        write_int_lines,
    )
except ImportError:  # Direct script execution.
    from fdk_tables import (  # type: ignore
        M_TAB_3_4_Q15,
        M_TAB_4_3_Q31,
        QUANT_TABLE_E_Q15,
        QUANT_TABLE_Q_Q15,
        SPEC_EXP_MANT_Q31,
        SPEC_EXP_SHIFT,
    )
    from utils import (  # type: ignore
        clz32_positive,
        count_leading_bits_positive,
        fmult_div2_q15_q15,
        fmult_div2_q31_q15,
        fmult_q31,
        int16,
        int32,
        load_case,
        write_int_lines,
    )

DFRACT_BITS = 32
MANT_DIGITS = 9
MANT_SIZE = 1 << MANT_DIGITS
MAX_QUANT = 8191
K_AAC_LC_RAW = 13284  # FL2FXCONST_DBL(-0.0946 + 0.5) >> 16
K_DEAD_ZONE_RAW = 7536  # FL2FXCONST_DBL(0.23) >> 16


@dataclass(frozen=True)
class LineTrace:
    line: int
    sfb: int
    input_raw: int
    gain: int
    sign: int
    quantizer_index: int
    quantizer_raw: int
    accu_after_gain: int
    clz_shift: int
    normalized_accu: int
    lut_index_3_4: int
    total_shift_before: int
    gain_table_index: int
    accu_after_pow: int
    total_shift_after: int
    rounding_offset_raw: int
    output_raw: int


@dataclass(frozen=True)
class SpectrumResult:
    quantized_spectrum: list[int]
    max_value_in_sfb: list[int]
    maximum_quantized_value: int
    active_line_mask: list[int]
    traces: list[LineTrace]


def quantize_line(raw: int, gain: int, dead_zone: bool = False, *, line: int = -1, sfb: int = -1) -> tuple[int, LineTrace]:
    if raw < -(1 << 31) or raw > (1 << 31) - 1:
        raise ValueError(f"input is not signed 32-bit: {raw}")

    quantizer_index = (-gain) & 3
    quantizer = QUANT_TABLE_Q_Q15[quantizer_index]
    quantizer_shift = ((-gain) >> 2) + 1
    k = K_DEAD_ZONE_RAW if dead_zone else K_AAC_LC_RAW
    initial_accu = fmult_div2_q31_q15(raw, quantizer)

    if initial_accu == 0:
        trace = LineTrace(line, sfb, raw, gain, 0, quantizer_index, quantizer,
                          initial_accu, 0, 0, 0, 0, 0, 0, 0, k, 0)
        return 0, trace

    sign = -1 if initial_accu < 0 else 1
    magnitude = -initial_accu if initial_accu < 0 else initial_accu
    accu_shift = clz32_positive(magnitude) - 1
    normalized = int32(magnitude << accu_shift)
    table_index = (normalized >> (DFRACT_BITS - 2 - MANT_DIGITS)) & ~MANT_SIZE
    total_before = quantizer_shift - accu_shift + 1
    gain_table_index = total_before & 3
    after_pow = fmult_div2_q15_q15(M_TAB_3_4_Q15[table_index], QUANT_TABLE_E_Q15[gain_table_index])
    total_after = (16 - 4) - 3 * (total_before >> 2)
    if total_after < 0:
        raise OverflowError(f"FDK MAX_QUANT precondition violated: totalShift={total_after}, gain={gain}, raw={raw}")
    shifted = after_pow >> min(total_after, DFRACT_BITS - 1)
    magnitude_q = (k + shifted) >> (DFRACT_BITS - 1 - 16)
    output = int16(-magnitude_q if sign < 0 else magnitude_q)
    trace = LineTrace(line, sfb, raw, gain, sign, quantizer_index, quantizer,
                      initial_accu, accu_shift, normalized, table_index,
                      total_before, gain_table_index, after_pow, total_after, k,
                      output)
    return output, trace


def inverse_quantize_line(quantized: int, gain: int) -> int:
    """Mirror FDKaacEnc_invQuantizeLines; result uses FDK's half-scale domain."""
    quantized = int16(quantized)
    if quantized == 0:
        return 0
    if abs(quantized) > MAX_QUANT:
        raise ValueError(f"inverse quantizer input exceeds MAX_QUANT: {quantized}")

    sign = -1 if quantized < 0 else 1
    accu = abs(quantized)
    exponent_shift = count_leading_bits_positive(accu)
    normalized = int32(accu << exponent_shift)
    spec_exp = (DFRACT_BITS - 1) - exponent_shift
    if spec_exp >= 14:
        raise ValueError(f"inverse exponent out of table: {spec_exp}")
    table_index = (normalized >> (DFRACT_BITS - 2 - MANT_DIGITS)) & ~MANT_SIZE
    mantissa = M_TAB_4_3_Q31[table_index]
    gain_mod = gain & 3
    exponent_mantissa = SPEC_EXP_MANT_Q31[gain_mod][spec_exp]
    result = fmult_q31(mantissa, exponent_mantissa)
    table_shift = SPEC_EXP_SHIFT[gain_mod][spec_exp] - 1
    integer_gain_shift = gain >> 2
    delta = -integer_gain_shift - table_shift
    result = int32(result << -delta) if delta < 0 else result >> delta
    return -result if sign < 0 else result


def validate_geometry(spectrum: Sequence[int], offsets: Sequence[int], sfb_cnt: int,
                      max_sfb_per_group: int, sfb_per_group: int,
                      scalefactors: Sequence[int]) -> None:
    if not 0 <= sfb_cnt <= 60:
        raise ValueError("sfb_cnt must be in [0, 60]")
    if sfb_per_group <= 0 or sfb_cnt % sfb_per_group:
        raise ValueError("sfb_per_group must be positive and divide sfb_cnt")
    if not 0 <= max_sfb_per_group <= sfb_per_group:
        raise ValueError("max_sfb_per_group must be in [0, sfb_per_group]")
    if len(offsets) < sfb_cnt + 1 or len(scalefactors) < sfb_cnt:
        raise ValueError("offset/scalefactor arrays are too short")
    if len(spectrum) > 1024:
        raise ValueError("spectrum exceeds AAC-LC frame length")
    if offsets[0] < 0 or offsets[sfb_cnt] > len(spectrum):
        raise ValueError("SFB offsets are outside the spectrum")
    if any(offsets[index] > offsets[index + 1] for index in range(sfb_cnt)):
        raise ValueError("SFB offsets must be monotonic")


def quantize_spectrum(spectrum: Sequence[int], offsets: Sequence[int], sfb_cnt: int,
                      max_sfb_per_group: int, sfb_per_group: int,
                      global_gain: int, scalefactors: Sequence[int],
                      dead_zone: bool = False, *, strict_range: bool = True,
                      prefill: int = 0, collect_trace: bool = True) -> SpectrumResult:
    validate_geometry(spectrum, offsets, sfb_cnt, max_sfb_per_group, sfb_per_group, scalefactors)
    output = [int16(prefill)] * len(spectrum)
    active_mask = [0] * len(spectrum)
    maxima = [0] * sfb_cnt
    traces: list[LineTrace] = []
    maximum_all = 0

    for group_start in range(0, sfb_cnt, sfb_per_group):
        for local_sfb in range(max_sfb_per_group):
            sfb = group_start + local_sfb
            gain = global_gain - scalefactors[sfb]
            maximum = 0
            for line in range(offsets[sfb], offsets[sfb + 1]):
                value, trace = quantize_line(spectrum[line], gain, dead_zone, line=line, sfb=sfb)
                output[line] = value
                active_mask[line] = 1
                maximum = max(maximum, abs(value))
                if collect_trace:
                    traces.append(trace)
            maxima[sfb] = maximum
            maximum_all = max(maximum_all, maximum)

    if strict_range and maximum_all > MAX_QUANT:
        raise OverflowError(f"maximum quantized magnitude {maximum_all} exceeds {MAX_QUANT}")
    return SpectrumResult(output, maxima, maximum_all, active_mask, traces)


def write_result(output_dir: str | Path, result: SpectrumResult) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    write_int_lines(directory / "quantized_spectrum_ref.txt", result.quantized_spectrum)
    write_int_lines(directory / "max_value_in_sfb_ref.txt", result.max_value_in_sfb)
    write_int_lines(directory / "active_line_mask.txt", result.active_line_mask)
    (directory / "intermediate_results.jsonl").write_text(
        "".join(json.dumps(asdict(trace), sort_keys=True) + "\n" for trace in result.traces),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(
        json.dumps({"maximum_quantized_value": result.maximum_quantized_value,
                    "mismatch_precondition": result.maximum_quantized_value > MAX_QUANT}, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--allow-out-of-range", action="store_true")
    args = parser.parse_args()
    case = load_case(args.case_dir)
    result = quantize_spectrum(
        case["mdct_spectrum"], case["sfb_offsets"], int(case["sfb_cnt"]),
        int(case["max_sfb_per_group"]), int(case["sfb_per_group"]),
        int(case["global_gain"]), case["scalefactors"],
        bool(case.get("dzone_quant_enable", 0)), strict_range=not args.allow_out_of_range,
    )
    write_result(args.output_dir, result)


if __name__ == "__main__":
    main()
