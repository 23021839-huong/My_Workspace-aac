"""Fixed-width helpers and vector I/O shared by the Python models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

INT32_MIN = -(1 << 31)
INT32_MAX = (1 << 31) - 1
INT16_MIN = -(1 << 15)
INT16_MAX = (1 << 15) - 1
Q31_SCALE = 1 << 31


def int32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def int16(value: int) -> int:
    value &= 0xFFFF
    return value - (1 << 16) if value & 0x8000 else value


def clz32_positive(value: int) -> int:
    if value <= 0 or value > INT32_MAX:
        raise ValueError(f"CLZ input must be a positive signed-32 value, got {value}")
    return 32 - value.bit_length()


def count_leading_bits_positive(value: int) -> int:
    return clz32_positive(value) - 1


def fmult_div2_q31_q15(a: int, b: int) -> int:
    """FDK generic fixmuldiv2_DS: signed high product for Q31 x Q15."""
    return int32((a * b) >> 16)


def fmult_div2_q15_q15(a: int, b: int) -> int:
    """FDK generic fixmuldiv2_SS; result is represented as Q31."""
    return int32(a * b)


def fmult_q31(a: int, b: int) -> int:
    """FDK generic fixmul_DD, including its truncation before left shift."""
    return int32(((a * b) >> 32) << 1)


def fpow2_q31(a: int) -> int:
    return fmult_q31(a, a)


def q31_to_float(raw: int) -> float:
    return raw / float(Q31_SCALE)


def float_to_q31(value: float) -> int:
    scaled = int(value * Q31_SCALE + (0.5 if value >= 0.0 else -0.5))
    return max(INT32_MIN, min(INT32_MAX, scaled))


def read_int_lines(path: str | Path) -> list[int]:
    values: list[int] = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        token = line.split("#", 1)[0].strip()
        if token:
            try:
                values.append(int(token, 0))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: invalid integer {token!r}") from exc
    return values


def write_int_lines(path: str | Path, values: Iterable[int]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


def load_case(case_dir: str | Path) -> dict[str, object]:
    directory = Path(case_dir)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["mdct_spectrum"] = read_int_lines(directory / "input_mdct_q31.txt")
    manifest["sfb_offsets"] = read_int_lines(directory / "sfb_offsets.txt")
    manifest["scalefactors"] = read_int_lines(directory / "scalefactor.txt")
    gain_values = read_int_lines(directory / "global_gain.txt")
    if len(gain_values) != 1:
        raise ValueError("global_gain.txt must contain exactly one integer")
    manifest["global_gain"] = gain_values[0]
    return manifest

