"""Generate deterministic AAC quantizer cases and Python golden outputs."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python_ref.quantization_fixed import quantize_spectrum, write_result  # noqa: E402
from python_ref.quantization_float import quantize_spectrum as quantize_float  # noqa: E402
from python_ref.utils import write_int_lines  # noqa: E402


def saw_spectrum(length: int, seed: int) -> list[int]:
    randomizer = random.Random(seed)
    anchors = [0, 1, -1, 32767, -32768, 1 << 20, -(1 << 20),
               (1 << 30), -(1 << 30), (1 << 31) - 1, -(1 << 31)]
    values = anchors[:]
    while len(values) < length:
        values.append(randomizer.randint(-(1 << 30), (1 << 30)))
    return values[:length]


CASES = {
    "zero_long": {
        "spectrum": [0] * 64,
        "offsets": [0, 4, 12, 28, 64],
        "scalefactors": [0, 0, 0, 0],
        "sfb_cnt": 4, "max_sfb_per_group": 4, "sfb_per_group": 4,
        "global_gain": -20, "dzone_quant_enable": 0,
    },
    "smoke_long": {
        "spectrum": saw_spectrum(128, 0xAAC1C),
        "offsets": [0, 4, 12, 28, 52, 84, 128],
        "scalefactors": [0, 1, -2, 3, -1, 2],
        "sfb_cnt": 6, "max_sfb_per_group": 6, "sfb_per_group": 6,
        "global_gain": -16, "dzone_quant_enable": 0,
    },
    "grouped_short_deadzone": {
        "spectrum": saw_spectrum(96, 0x5A17),
        "offsets": [0, 8, 16, 24, 32, 48, 64, 80, 96],
        "scalefactors": [0, 2, -1, 7, 1, -2, 3, 9],
        "sfb_cnt": 8, "max_sfb_per_group": 3, "sfb_per_group": 4,
        "global_gain": -12, "dzone_quant_enable": 1,
    },
}


def write_case(root: Path, name: str, case: dict[str, object]) -> None:
    case_dir = root / "input" / name
    expected_dir = root / "expected" / name
    case_dir.mkdir(parents=True, exist_ok=True)
    write_int_lines(case_dir / "input_mdct_q31.txt", case["spectrum"])
    write_int_lines(case_dir / "sfb_offsets.txt", case["offsets"])
    write_int_lines(case_dir / "scalefactor.txt", case["scalefactors"])
    write_int_lines(case_dir / "global_gain.txt", [case["global_gain"]])
    manifest = {key: case[key] for key in (
        "sfb_cnt", "max_sfb_per_group", "sfb_per_group",
        "dzone_quant_enable")}
    manifest.update({
        "schema_version": 1,
        "source_commit": "35f9c13cb6df0c5d4e7ba958ef2d251c48b8d1d9",
        "provenance": "deterministic synthetic; verified through FDKaacEnc_QuantizeSpectrum",
        "case": name,
        "aot": "AAC-LC",
        "sample_rate_hz": 48000,
        "channel": 0,
        "frame_index": -1,
        "window_sequence": "EIGHT_SHORT_SEQUENCE" if "grouped_short" in name else "ONLY_LONG_SEQUENCE",
        "mdct_scale": 0,
        "quant_output_prefill": "zero",
        "input_format": "signed Q1.31 decimal",
        "expected_format": "signed integer, one value per line",
        "integer_encoding": "signed-decimal",
        "endianness": "not-applicable-text",
    })
    (case_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    fixed = quantize_spectrum(
        case["spectrum"], case["offsets"], case["sfb_cnt"],
        case["max_sfb_per_group"], case["sfb_per_group"],
        case["global_gain"], case["scalefactors"],
        bool(case["dzone_quant_enable"]))
    write_result(expected_dir, fixed)
    floating = quantize_float(
        case["spectrum"], case["offsets"], case["sfb_cnt"],
        case["max_sfb_per_group"], case["sfb_per_group"],
        case["global_gain"], case["scalefactors"],
        bool(case["dzone_quant_enable"]))
    write_int_lines(expected_dir / "quantized_spectrum_float.txt", floating)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT / "vectors")
    args = parser.parse_args()
    for name, case in CASES.items():
        write_case(args.root, name, case)
    print(f"generated {len(CASES)} cases below {args.root}")


if __name__ == "__main__":
    main()
