#!/usr/bin/env python3
"""Compare captured PYNQ Window/MDCT outputs with a NumPy float64 oracle."""
from __future__ import annotations

import argparse
import csv
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Sequence

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - depends on the board image.
    raise SystemExit("ERROR: NumPy is required: python3 -c \"import numpy\"") from exc

from mdct_golden import load_frames, sha256


HERE = Path(__file__).resolve().parent
DEFAULT_GOLDEN = (HERE / "golden" if (HERE / "golden").is_dir() else
                  HERE.parent / "golden" / "radix2_q31_v1")
Q31_SCALE = 1 << 31
FOLD_EXPONENT = 2
BLOCK_NAMES = ("LONG", "START", "SHORT", "STOP")
WINDOW_TABLE = {
    (1024, 0): 0,  # SINE1024
    (1024, 1): 1,  # KBD1024
    (128, 0): 2,   # SINE128
    (128, 1): 3,   # KBD128
}


def _signed_hex(token: str, bits: int) -> int:
    raw = int(token, 16)
    if not 0 <= raw < (1 << bits):
        raise ValueError(f"out-of-range {bits}-bit value: {token}")
    return raw - (1 << bits) if raw & (1 << (bits - 1)) else raw


def _wrap32(value: int) -> int:
    raw = int(value) & 0xFFFFFFFF
    return raw - (1 << 32) if raw & 0x80000000 else raw


def _load_windows(golden: Path) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    tables: dict[int, list[tuple[int, int]]] = {index: [] for index in range(4)}
    path = golden / "rom_window_q15.txt"
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            fields = line.split()
            if len(fields) != 4:
                raise ValueError(f"{path}:{line_number}: expected 4 fields")
            table_id, index = map(int, fields[:2])
            if table_id not in tables or index != len(tables[table_id]):
                raise ValueError(f"{path}:{line_number}: invalid table/index")
            tables[table_id].append((_signed_hex(fields[2], 16), _signed_hex(fields[3], 16)))
    expected_lengths = {0: 512, 1: 512, 2: 64, 3: 64}
    if {key: len(value) for key, value in tables.items()} != expected_lengths:
        raise ValueError(f"invalid window ROM lengths in {path}")
    return {key: tuple(tables[table_id]) for key, table_id in WINDOW_TABLE.items()}


@lru_cache(maxsize=2)
def _dct4_kernel(length: int) -> np.ndarray:
    if length not in (128, 1024):
        raise ValueError(f"unsupported DCT-IV length: {length}")
    n = np.arange(length, dtype=np.float64)[:, None]
    k = np.arange(length, dtype=np.float64)[None, :]
    return np.cos((np.pi / length) * (n + 0.5) * (k + 0.5))


def _dct4_float64(values: Sequence[float]) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64)
    return vector @ _dct4_kernel(int(vector.size))


class FloatMdctOracle:
    """Stateful AAC window/fold followed by an independent float64 DCT-IV."""

    def __init__(self, golden: Path) -> None:
        self.windows = _load_windows(golden)
        self.reset()

    def reset(self) -> None:
        self.prev_fr = 0
        self.prev_shape = 0

    @staticmethod
    def _parameters(block_type: int) -> tuple[int, int, int]:
        if block_type == 2:
            return 8, 128, 128
        if block_type in (0, 3):
            return 1, 1024, 1024
        if block_type == 1:
            return 1, 1024, 128
        raise ValueError(f"invalid block type: {block_type}")

    @staticmethod
    def _fold(pcm: Sequence[int], tl: int, fl: int, fr: int,
              left: Sequence[tuple[int, int]],
              right: Sequence[tuple[int, int]]) -> np.ndarray:
        if len(pcm) != 2 * tl:
            raise ValueError(f"fold needs {2 * tl} samples, got {len(pcm)}")
        nl = (tl - fl) // 2
        nr = (tl - fr) // 2
        if nl < 0 or nr < 0:
            raise ValueError(f"illegal block transition: tl={tl}, fl={fl}, fr={fr}")
        result: list[int | None] = [None] * tl
        for index in range(nl):
            result[tl // 2 + index] = _wrap32(-(int(pcm[tl - index - 1]) << 15))
        for index in range(fl // 2):
            left_re, left_im = left[index]
            value = int(pcm[index + nl]) * left_im
            result[tl // 2 + index + nl] = _wrap32(
                value - int(pcm[tl - nl - index - 1]) * left_re
            )
        for index in range(nr):
            result[tl // 2 - 1 - index] = _wrap32(-(int(pcm[tl + index]) << 15))
        for index in range(fr // 2):
            right_re, right_im = right[index]
            value = _wrap32(
                int(pcm[tl + nr + index]) * right_re
                + int(pcm[2 * tl - nr - index - 1]) * right_im
            )
            result[tl // 2 - nr - index - 1] = _wrap32(-value)
        if any(value is None for value in result):
            raise AssertionError("window fold left output samples unassigned")
        return np.asarray(result, dtype=np.float64)

    def process_frame(self, pcm: Sequence[int], block_type: int,
                      right_shape: int) -> np.ndarray:
        if len(pcm) != 2048 or any(not -32768 <= int(value) <= 32767 for value in pcm):
            raise ValueError("one frame must contain 2048 signed 16-bit samples")
        if right_shape not in (0, 1):
            raise ValueError(f"invalid window shape: {right_shape}")
        n_spec, tl, fr = self._parameters(block_type)
        time_base = (1024 - tl) // 2
        references = []
        for sub_id in range(n_spec):
            if self.prev_fr == 0:
                self.prev_fr = fr
                self.prev_shape = right_shape
            fl = self.prev_fr
            base = time_base + sub_id * tl
            folded = self._fold(
                pcm[base:base + 2 * tl], tl, fl, fr,
                self.windows[(fl, self.prev_shape)],
                self.windows[(fr, right_shape)],
            )
            folded_physical = folded * (2.0**FOLD_EXPONENT / Q31_SCALE)
            references.append(_dct4_float64(folded_physical))
            self.prev_fr = fr
            self.prev_shape = right_shape
        result = np.concatenate(references)
        if result.size != 1024:
            raise AssertionError(f"float oracle produced {result.size} outputs")
        return result


def _read_inputs(path: Path) -> dict[tuple[int, int, int], list[int]]:
    values: dict[tuple[int, int, int], list[int]] = {}
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            fields = line.split()
            if len(fields) != 6:
                raise ValueError(f"{path}:{line_number}: expected 6 fields")
            iteration, case_id, frame_id, index = map(int, fields[:4])
            signed = int(fields[4])
            if signed != _signed_hex(fields[5], 16):
                raise ValueError(f"{path}:{line_number}: signed/hex PCM mismatch")
            frame = values.setdefault((iteration, case_id, frame_id), [])
            if index != len(frame):
                raise ValueError(f"{path}:{line_number}: unexpected input index {index}")
            frame.append(signed)
    return values


def _read_actual(path: Path) -> dict[tuple[int, int, int], tuple[list[int], int]]:
    values: dict[tuple[int, int, int], list[int]] = {}
    exponents: dict[tuple[int, int, int], int] = {}
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            fields = line.split()
            if len(fields) != 6:
                raise ValueError(f"{path}:{line_number}: expected 6 fields")
            iteration, case_id, frame_id, index = map(int, fields[:4])
            key = (iteration, case_id, frame_id)
            frame = values.setdefault(key, [])
            if index != len(frame):
                raise ValueError(f"{path}:{line_number}: unexpected output index {index}")
            frame.append(_signed_hex(fields[4], 32))
            exponent = int(fields[5])
            if key in exponents and exponents[key] != exponent:
                raise ValueError(f"{path}:{line_number}: exponent changed inside frame")
            exponents[key] = exponent
    return {key: (frame, exponents[key]) for key, frame in values.items()}


def _metrics(sum_error_sq: float, sum_reference_sq: float,
             count: int, max_abs_error: float) -> dict[str, float | int]:
    error_power = sum_error_sq / count if count else 0.0
    reference_power = sum_reference_sq / count if count else 0.0
    rmse = math.sqrt(error_power)
    relative_rms = math.sqrt(sum_error_sq / sum_reference_sq) if sum_reference_sq else rmse
    if error_power == 0.0:
        snr_db = math.inf
    elif reference_power == 0.0:
        snr_db = -math.inf
    else:
        snr_db = 10.0 * math.log10(reference_power / error_power)
    return {
        "comparison_count": count,
        "rmse": rmse,
        "relative_rms": relative_rms,
        "snr_db": snr_db,
        "max_abs_error": max_abs_error,
    }


def compare_results(results: Path, golden: Path = DEFAULT_GOLDEN) -> dict[str, object]:
    """Create float64 comparison artifacts from one completed board result directory."""
    results = Path(results).resolve()
    golden = Path(golden).resolve()
    frames, golden_hashes = load_frames(golden)
    input_path = results / "input_pcm.txt"
    actual_path = results / "actual_q31.txt"
    for path in (input_path, actual_path):
        if not path.is_file():
            raise FileNotFoundError(f"missing board capture: {path}")
    inputs = _read_inputs(input_path)
    actual = _read_actual(actual_path)
    if set(inputs) != set(actual):
        raise ValueError("input_pcm.txt and actual_q31.txt contain different frames")
    iterations = sorted({key[0] for key in inputs})
    if iterations != list(range(len(iterations))):
        raise ValueError(f"iterations must be contiguous from zero, got {iterations}")
    expected = {
        (iteration, frame.case_id, frame.frame_id)
        for iteration in iterations for frame in frames
    }
    if set(inputs) != expected:
        missing = sorted(expected - set(inputs))[:4]
        extra = sorted(set(inputs) - expected)[:4]
        raise ValueError(f"captured frame set mismatch; missing={missing}, extra={extra}")

    output_path = results / "float_output_compare.csv"
    frame_path = results / "float_frames.csv"
    summary_path = results / "float_summary.json"
    oracle = FloatMdctOracle(golden)
    sum_error_sq = 0.0
    sum_reference_sq = 0.0
    total_count = 0
    max_abs_error = 0.0
    input_mismatch_count = 0
    worst: dict[str, int | str | float] = {}

    with output_path.open("w", encoding="utf-8", newline="") as output_stream, \
            frame_path.open("w", encoding="utf-8", newline="") as frame_stream:
        output_writer = csv.writer(output_stream, lineterminator="\n")
        frame_fields = (
            "iteration", "case_id", "frame_id", "block_type", "exponent",
            "input_mismatch_count", "rmse", "relative_rms", "snr_db",
            "max_abs_error", "worst_bin",
        )
        frame_writer = csv.DictWriter(frame_stream, fieldnames=frame_fields, lineterminator="\n")
        output_writer.writerow((
            "iteration", "case_id", "frame_id", "block_type", "bin", "sub_id",
            "sub_index", "actual_q31", "exponent", "actual_physical",
            "reference_float64", "signed_error", "abs_error", "error_lsb_to_float",
        ))
        frame_writer.writeheader()
        for iteration in iterations:
            oracle.reset()
            for frame in frames:
                key = (iteration, frame.case_id, frame.frame_id)
                pcm = inputs[key]
                actual_q31, exponent = actual[key]
                if len(pcm) != 2048 or len(actual_q31) != 1024:
                    raise ValueError(
                        f"frame {key}: expected 2048 inputs/1024 outputs, "
                        f"got {len(pcm)}/{len(actual_q31)}"
                    )
                if frame.reset_before:
                    oracle.reset()
                reference = oracle.process_frame(pcm, frame.block_type, frame.right_shape)
                actual_physical = np.asarray(actual_q31, dtype=np.float64) * (
                    2.0**exponent / Q31_SCALE
                )
                error = actual_physical - reference
                abs_error = np.abs(error)
                frame_error_sq = float(np.sum(error * error, dtype=np.float64))
                frame_reference_sq = float(np.sum(reference * reference, dtype=np.float64))
                worst_bin = int(np.argmax(abs_error))
                frame_max = float(abs_error[worst_bin])
                frame_metrics = _metrics(frame_error_sq, frame_reference_sq, 1024, frame_max)
                mismatches = sum(got != want for got, want in zip(pcm, frame.pcm))
                input_mismatch_count += mismatches
                frame_writer.writerow({
                    "iteration": iteration,
                    "case_id": frame.case_id,
                    "frame_id": frame.frame_id,
                    "block_type": BLOCK_NAMES[frame.block_type],
                    "exponent": exponent,
                    "input_mismatch_count": mismatches,
                    "rmse": format(float(frame_metrics["rmse"]), ".17g"),
                    "relative_rms": format(float(frame_metrics["relative_rms"]), ".17g"),
                    "snr_db": format(float(frame_metrics["snr_db"]), ".17g"),
                    "max_abs_error": format(frame_max, ".17g"),
                    "worst_bin": worst_bin,
                })
                sub_length = 128 if frame.block_type == 2 else 1024
                float_scale = Q31_SCALE / 2.0**exponent
                for index in range(1024):
                    output_writer.writerow((
                        iteration, frame.case_id, frame.frame_id,
                        BLOCK_NAMES[frame.block_type], index, index // sub_length,
                        index % sub_length, actual_q31[index], exponent,
                        format(actual_physical[index], ".17g"),
                        format(reference[index], ".17g"), format(error[index], ".17g"),
                        format(abs_error[index], ".17g"),
                        format(actual_q31[index] - reference[index] * float_scale, ".17g"),
                    ))
                if frame_max > max_abs_error:
                    max_abs_error = frame_max
                    worst = {
                        "iteration": iteration,
                        "case_id": frame.case_id,
                        "frame_id": frame.frame_id,
                        "block_type": BLOCK_NAMES[frame.block_type],
                        "bin": worst_bin,
                        "actual_q31": actual_q31[worst_bin],
                        "exponent": exponent,
                        "actual_physical": float(actual_physical[worst_bin]),
                        "reference_float64": float(reference[worst_bin]),
                        "signed_error": float(error[worst_bin]),
                    }
                sum_error_sq += frame_error_sq
                sum_reference_sq += frame_reference_sq
                total_count += 1024

    aggregate = _metrics(sum_error_sq, sum_reference_sq, total_count, max_abs_error)
    summary: dict[str, object] = {
        "schema": "mdct-board-float64-v1",
        "reference": "Q15 window/fold physical values followed by NumPy float64 DCT-IV",
        "result_directory": str(results),
        "iterations": len(iterations),
        "unique_frames": len(frames),
        "compared_frames": len(iterations) * len(frames),
        "unique_output_count": sum(len(frame.spectrum) for frame in frames),
        **aggregate,
        "input_mismatch_count_vs_golden": input_mismatch_count,
        "worst": worst,
        "source_sha256": {
            "input_pcm.txt": sha256(input_path),
            "actual_q31.txt": sha256(actual_path),
            "rom_window_q15.txt": golden_hashes["rom_window_q15.txt"],
        },
        "artifacts": {
            "per_output": output_path.name,
            "per_frame": frame_path.name,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"FLOAT: compared {summary['compared_frames']} frames, {total_count} PL outputs")
    print(f"FLOAT: RMSE={float(aggregate['rmse']):.6e}, "
          f"relative RMS={float(aggregate['relative_rms']):.6e}, "
          f"SNR={float(aggregate['snr_db']):.3f} dB, "
          f"max abs={max_abs_error:.6e}")
    print(f"FLOAT: results saved to {summary_path}")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path,
                        help="directory containing input_pcm.txt and actual_q31.txt")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    args = parser.parse_args(argv)
    try:
        compare_results(args.results, args.golden)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
