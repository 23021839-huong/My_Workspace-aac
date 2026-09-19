"""Compare quantizer output directories and report line/SFB error metrics."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python_ref.utils import read_int_lines  # noqa: E402


def load_line_to_sfb(trace_path: Path) -> dict[int, int]:
    result: dict[int, int] = {}
    if trace_path.exists():
        for row in trace_path.read_text(encoding="utf-8").splitlines():
            item = json.loads(row)
            result[int(item["line"])] = int(item["sfb"])
    return result


def compare_optional_vector(expected_dir: Path, actual_dir: Path,
                            name: str) -> dict[str, object]:
    expected_path = expected_dir / name
    actual_path = actual_dir / name
    if not actual_path.exists():
        return {"available": False}
    expected = read_int_lines(expected_path)
    actual = read_int_lines(actual_path)
    if len(expected) != len(actual):
        return {"available": True, "length_mismatch": [len(expected), len(actual)]}
    positions = [index for index, pair in enumerate(zip(expected, actual))
                 if pair[0] != pair[1]]
    return {"available": True, "mismatch_count": len(positions),
            "mismatch_positions": positions[:64]}


def compare_optional_traces(expected_dir: Path, actual_dir: Path) -> dict[str, object]:
    expected_path = expected_dir / "intermediate_results.jsonl"
    actual_path = actual_dir / "intermediate_results.jsonl"
    if not actual_path.exists():
        return {"available": False}
    expected = [json.loads(row) for row in expected_path.read_text(encoding="utf-8").splitlines()]
    actual = [json.loads(row) for row in actual_path.read_text(encoding="utf-8").splitlines()]
    if len(expected) != len(actual):
        return {"available": True, "length_mismatch": [len(expected), len(actual)]}
    mismatches: list[dict[str, object]] = []
    for index, (want, got) in enumerate(zip(expected, actual)):
        fields = sorted(key for key in want.keys() | got.keys() if want.get(key) != got.get(key))
        if fields and len(mismatches) < 64:
            mismatches.append({"trace_index": index, "line": want.get("line"),
                               "sfb": want.get("sfb"), "fields": fields})
    total = sum(want != got for want, got in zip(expected, actual))
    return {"available": True, "mismatch_count": total, "first_mismatches": mismatches}


def compare(expected_dir: Path, actual_dir: Path,
            actual_name: str = "quantized_spectrum_ref.txt") -> dict[str, object]:
    expected = read_int_lines(expected_dir / "quantized_spectrum_ref.txt")
    actual = read_int_lines(actual_dir / actual_name)
    if len(expected) != len(actual):
        raise ValueError(f"length mismatch: expected {len(expected)}, actual {len(actual)}")
    errors = [got - want for want, got in zip(expected, actual)]
    positions = [index for index, error in enumerate(errors) if error]
    line_to_sfb = load_line_to_sfb(expected_dir / "intermediate_results.jsonl")
    per_sfb = Counter(line_to_sfb.get(index, -1) for index in positions)
    report = {
        "samples": len(errors),
        "mismatch_count": len(positions),
        "max_abs_error": max(map(abs, errors), default=0),
        "mean_abs_error": sum(map(abs, errors)) / len(errors) if errors else 0.0,
        "mismatch_positions": positions[:64],
        "mismatch_count_by_sfb": dict(sorted(per_sfb.items())),
        "max_value_in_sfb": compare_optional_vector(
            expected_dir, actual_dir, "max_value_in_sfb_ref.txt"),
        "active_line_mask": compare_optional_vector(
            expected_dir, actual_dir, "active_line_mask.txt"),
        "intermediate_results": compare_optional_traces(expected_dir, actual_dir),
    }
    auxiliary_mismatches = 0
    for key in ("max_value_in_sfb", "active_line_mask", "intermediate_results"):
        item = report[key]
        if item.get("available"):
            auxiliary_mismatches += int(item.get("mismatch_count", 0))
            auxiliary_mismatches += int("length_mismatch" in item)
    report["exact_match"] = not positions and auxiliary_mismatches == 0
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_dir", type=Path)
    parser.add_argument("actual_dir", type=Path)
    parser.add_argument("--actual-name", default="quantized_spectrum_ref.txt")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = compare(args.expected_dir, args.actual_dir, args.actual_name)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
    raise SystemExit(0 if report["exact_match"] else 1)


if __name__ == "__main__":
    main()
