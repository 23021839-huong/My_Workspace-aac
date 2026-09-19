"""Generate vectors and cross-check Python fixed, float, and optional C++."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python_ref.quantization_fixed import main as _unused  # noqa: F401,E402
from verification.compare_models import compare  # noqa: E402


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpp", type=Path, help="path to quantization_ref_cli")
    parser.add_argument("--fdk", type=Path, help="path to fdk_quant_harness")
    args = parser.parse_args()
    run([sys.executable, str(ROOT / "tools" / "generate_test_vectors.py")])
    failures = 0
    for case_dir in sorted((ROOT / "vectors" / "input").iterdir()):
        expected = ROOT / "vectors" / "expected" / case_dir.name
        float_report = compare(expected, expected, "quantized_spectrum_float.txt")
        print(f"{case_dir.name}: float max_error={float_report['max_abs_error']}, "
              f"mismatches={float_report['mismatch_count']}")
        if args.cpp:
            actual = ROOT / "vectors" / "cpp_actual" / case_dir.name
            run([str(args.cpp), str(case_dir), str(actual)])
            report = compare(expected, actual)
            print(f"{case_dir.name}: C++ mismatches={report['mismatch_count']}")
            failures += int(not report["exact_match"])
        if args.fdk:
            actual = ROOT / "vectors" / "fdk_actual" / case_dir.name
            run([str(args.fdk), str(case_dir), str(actual)])
            report = compare(expected, actual)
            print(f"{case_dir.name}: FDK mismatches={report['mismatch_count']}")
            failures += int(not report["exact_match"])
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
