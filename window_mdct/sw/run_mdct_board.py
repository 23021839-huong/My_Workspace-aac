#!/usr/bin/env python3
"""Run the full golden frame sequences through the PYNQ MDCT AXI peripheral."""
from __future__ import annotations

import argparse
import csv
import json
import math
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from mdct_golden import compare_spectrum, load_frames, sha256


HERE = Path(__file__).resolve().parent
DEFAULT_GOLDEN = (HERE / "golden" if (HERE / "golden").is_dir() else
                  HERE.parent / "golden" / "radix2_q31_v1")
TIMING_FIELDS = ("load_ms", "compute_poll_ms", "read_ms", "total_ms")


def _percentile(values, fraction):
    """Linearly interpolated percentile for a non-empty sorted value list."""
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def summarize_timings(reports):
    """Aggregate host-side timing without relabeling it as pure core latency."""
    summary = {}
    for field in TIMING_FIELDS:
        if not reports or any(field not in report for report in reports):
            continue
        values = sorted(float(report[field]) for report in reports)
        summary[field] = {
            "count": len(values),
            "average": sum(values) / len(values),
            "minimum": values[0],
            "p50": _percentile(values, 0.50),
            "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99),
            "maximum": values[-1],
        }
    return summary


def run_frames(device, frames, repeat, timeout_s, output, print_io=False):
    reports = []
    with (output / "actual_q31.txt").open("w", encoding="utf-8") as actual_file, \
            (output / "input_pcm.txt").open("w", encoding="utf-8") as input_file, \
            (output / "output_compare.csv").open("w", encoding="utf-8", newline="") as compare_file, \
            (output / "frames.jsonl").open("w", encoding="utf-8") as details:
        compare_writer = csv.writer(compare_file)
        compare_writer.writerow(("iteration", "case_id", "frame_id", "bin",
                                 "actual_signed", "actual_hex", "expected_signed",
                                 "expected_hex", "error_lsb", "exponent"))
        for iteration in range(repeat):
            for frame in frames:
                for index, value in enumerate(frame.pcm):
                    input_file.write(
                        f"{iteration} {frame.case_id} {frame.frame_id} {index} "
                        f"{value} {value & 0xffff:04X}\n"
                    )
                    if print_io:
                        print(f"IN  repeat={iteration} case={frame.case_id} "
                              f"frame={frame.frame_id} sample={index:04d} "
                              f"signed={value:6d} hex=0x{value & 0xffff:04X}")
                input_file.flush()
                actual, exponent = device.transform(
                    frame.pcm, block_type=frame.block_type, right_shape=frame.right_shape,
                    clear_history=frame.reset_before, timeout_s=timeout_s,
                )
                report = {
                    "iteration": iteration, "case_id": frame.case_id,
                    "frame_id": frame.frame_id, "block_type": frame.block_type,
                    "right_shape": frame.right_shape,
                    **compare_spectrum(frame.spectrum, actual, frame.exponent, exponent),
                    **device.last_timings,
                }
                reports.append(report)
                details.write(json.dumps(report) + "\n")
                details.flush()
                for index, (value, expected) in enumerate(zip(actual, frame.spectrum)):
                    value = int(value)
                    error = value - expected
                    actual_file.write(
                        f"{iteration} {frame.case_id} {frame.frame_id} {index} "
                        f"{value & 0xffffffff:08X} {exponent}\n"
                    )
                    compare_writer.writerow((
                        iteration, frame.case_id, frame.frame_id, index,
                        value, f"{value & 0xffffffff:08X}", expected,
                        f"{expected & 0xffffffff:08X}", error, exponent,
                    ))
                    if print_io:
                        print(f"OUT repeat={iteration} case={frame.case_id} "
                              f"frame={frame.frame_id} bin={index:04d} "
                              f"actual={value:12d} hex=0x{value & 0xffffffff:08X} "
                              f"expected={expected:12d} error={error:+d}")
                actual_file.flush()
                compare_file.flush()
                verdict = "PASS" if report["passed"] else "FAIL"
                print(f"{verdict} repeat={iteration} case={frame.case_id} "
                      f"frame={frame.frame_id} mismatches={report['mismatch_count']} "
                      f"exp={exponent} total={report['total_ms']:.3f} ms", flush=True)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitfile", type=Path, default=HERE / "mdct_pynq_z2.bit")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds for a whole frame")
    parser.add_argument("--output", type=Path, help="new directory; existing results are never overwritten")
    parser.add_argument("--print-io", action="store_true",
                        help="print every PCM input and MDCT output/golden/error")
    parser.add_argument("--compare-float", action="store_true",
                        help="compare captured PL outputs with NumPy float64 after the board run")
    parser.add_argument("--validate-only", action="store_true", help="check golden only; no hardware access")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    if args.validate_only and args.compare_float:
        parser.error("--compare-float requires a real board run")
    if args.validate_only:
        frames, _ = load_frames(args.golden)
        print(f"PASS: golden validated: {len(frames)} frames, "
              f"{sum(len(f.spectrum) for f in frames)} bins; hardware NOT tested")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output or HERE / "results" / stamp
    output.mkdir(parents=True, exist_ok=False)
    summary = {"status": "FAIL", "hardware_tested": False,
               "utc": stamp, "machine": platform.machine(), "python": sys.version,
               "repeat": args.repeat, "print_io": args.print_io,
               "compare_float": args.compare_float,
               "timing_kind": "host wall time including MMIO/polling"}
    try:
        frames, hashes = load_frames(args.golden)
        summary["golden_sha256"] = hashes
        summary["expected_frames"] = len(frames) * args.repeat
        summary["overlay_sha256"] = {
            path.name: sha256(path)
            for path in (args.bitfile, args.bitfile.with_suffix(".hwh"))
        }
        # Imported only for a real board run. Validation works on a plain PC.
        from mdct_pynq import MdctPynq
        device = MdctPynq(args.bitfile)
        summary["hardware_tested"] = True
        reports = run_frames(device, frames, args.repeat, args.timeout, output, args.print_io)
        summary["completed_frames"] = len(reports)
        summary["failed_frames"] = sum(not row["passed"] for row in reports)
        summary["max_abs_error_lsb"] = max(row["max_abs_error_lsb"] for row in reports)
        summary["timing_ms"] = summarize_timings(reports)
        summary["status"] = "PASS" if summary["failed_frames"] == 0 else "FAIL"
        fields = [key for key in reports[0] if key != "first_mismatches"]
        with (output / "frames.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(reports)
        if args.compare_float:
            from compare_board_float import compare_results
            summary["float_comparison"] = compare_results(output, args.golden)
    except (Exception, KeyboardInterrupt) as exc:
        summary["status"] = "FAIL"
        summary["error"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL: {summary['error']}", file=sys.stderr)
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"{summary['status']}: results saved to {output}")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
