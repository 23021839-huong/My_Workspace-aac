"""Read-only model/source audit; generated evidence stays beside this script.

Run with Python >=3.10. Does not build or execute the C++/FDK harness.
"""
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
import wave

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
REF = REPO / "my_workspace/quantization_coding/quantization_reference"
sys.path.insert(0, str(REF))
from python_ref import fdk_tables as tables
from python_ref.quantization_fixed import quantize_line, quantize_spectrum
from tools.extract_fdk_tables import array_body, parse_plain_ints, parse_q31_decimal, parse_qtc_hex
from tools.generate_test_vectors import CASES, write_case
from verification.compare_models import compare


def main():
    result = {"scope": "Python/source audit, not a new C++/FDK/RTL run"}
    suite = unittest.defaultTestLoader.discover(str(REF / "tests"))
    unit = unittest.TextTestRunner(verbosity=2).run(suite)
    result["unit_tests"] = {"count": unit.testsRun, "passed": unit.wasSuccessful()}
    result["synthetic"] = {}
    for name, case in CASES.items():
        write_case(HERE / "regenerated", name, case)
        expected = REF / "vectors/expected" / name
        report = compare(expected, HERE / "regenerated/expected" / name)
        trace = [json.loads(x) for x in (expected / "intermediate_results.jsonl").read_text().splitlines()]
        result["synthetic"][name] = {
            "comparison": report,
            "active_lines": len(trace),
            "max_abs_q": max(abs(x["output_raw"]) for x in trace),
            "nonzero_lut_indices": len({x["lut_index_3_4"] for x in trace if x["sign"]}),
        }
    rom = (REPO / "libAACenc/src/aacEnc_rom.cpp").read_text(encoding="utf-8")
    inc = (REF / "cpp_ref/fdk_quant_tables.inc").read_text()
    table_specs = [
        ("FDKaacEnc_mTab_3_4", "kMTab34Q15", parse_qtc_hex, tables.M_TAB_3_4_Q15),
        ("FDKaacEnc_quantTableQ", "kQuantTableQQ15", parse_qtc_hex, tables.QUANT_TABLE_Q_Q15),
        ("FDKaacEnc_quantTableE", "kQuantTableEQ15", parse_qtc_hex, tables.QUANT_TABLE_E_Q15),
        ("FDKaacEnc_mTab_4_3Elc", "kMTab43Q31", parse_q31_decimal, tables.M_TAB_4_3_Q31),
        ("FDKaacEnc_specExpMantTableCombElc", "kSpecExpMantQ31", parse_q31_decimal, sum(tables.SPEC_EXP_MANT_Q31, [])),
        ("FDKaacEnc_specExpTableComb", "kSpecExpShift", parse_plain_ints, sum(tables.SPEC_EXP_SHIFT, [])),
    ]
    result["tables"] = {}
    for symbol, cpp_symbol, parser, expected in table_specs:
        body = re.search(cpp_symbol + r"\[\d+\] = \{([^}]+)\}", inc).group(1)
        cpp = list(map(int, re.findall(r"-?\d+", body)))
        result["tables"][symbol] = {
            "length": len(expected),
            "python_matches_source_extractor": parser(array_body(rom, symbol)) == expected,
            "cpp_matches_python": cpp == expected,
        }
    positive, tp = quantize_line(1048573, -40)
    negative, tn = quantize_line(-1048573, -40)
    result["sign_counterexample"] = {
        "raw": 1048573, "gain": -40, "q_positive": positive,
        "q_negative": negative, "initial_positive": tp.accu_after_gain,
        "initial_negative": tn.accu_after_gain,
    }
    minimal = HERE / "minimal_actual"
    minimal.mkdir(exist_ok=True)
    (minimal / "quantized_spectrum_ref.txt").write_bytes(
        (REF / "vectors/expected/smoke_long/quantized_spectrum_ref.txt").read_bytes())
    result["missing_auxiliary_comparison"] = compare(REF / "vectors/expected/smoke_long", minimal)
    q, trace = quantize_line(2147483647, -76)
    result["retry_range"] = {"raw": 2147483647, "gain": -76, "q": q, "total_shift_after": trace.total_shift_after}
    try:
        quantize_spectrum([2147483647], [0, 1], 1, 1, 1, -76, [0])
    except OverflowError as exc:
        result["retry_range"]["default_model_error"] = str(exc)
    profile = REPO / "output/z2_profile"
    with (profile / "encoder_profile.csv").open() as stream:
        stats = {x["block"]: x for x in csv.DictReader(stream)}
    frame = float(stats["frame_total"]["average_us"])
    qmax = float(stats["quantize_and_max_sfb"]["average_us"])
    result["profile"] = {
        "rows": stats,
        "qmax_ideal_system_speedup": 1 / (1 - qmax / frame),
        "hypothetical_system_speedups": {str(t): frame / (frame - qmax + t) for t in (20, 30, 50, 60)},
    }
    result["hashes"] = {}
    files = [profile / "encoder_profile.csv", profile / "profile_output.aac", REPO / "input/abc_votay.wav"]
    files += [REPO / "libAACenc/src" / f for f in ("quantize.cpp", "aacEnc_rom.cpp", "qc_main.cpp", "sf_estim.cpp", "aacenc_profile.cpp")]
    for path in files:
        result["hashes"][str(path.relative_to(REPO))] = hashlib.sha256(path.read_bytes()).hexdigest()
    with wave.open(str(REPO / "input/abc_votay.wav"), "rb") as wav:
        result["wav"] = {"channels": wav.getnchannels(), "sample_rate": wav.getframerate(), "sample_width": wav.getsampwidth(), "samples": wav.getnframes(), "duration_s": wav.getnframes() / wav.getframerate()}
    data = (profile / "profile_output.aac").read_bytes()
    offset = count = 0
    modes = set()
    while offset + 7 <= len(data):
        assert data[offset] == 255 and data[offset + 1] & 246 == 240
        size = ((data[offset + 3] & 3) << 11) | (data[offset + 4] << 3) | (data[offset + 5] >> 5)
        assert size >= 7 and offset + size <= len(data)
        modes.add(((data[offset + 2] >> 6) + 1, (data[offset + 2] >> 2) & 15, ((data[offset + 2] & 1) << 2) | (data[offset + 3] >> 6)))
        offset += size
        count += 1
    result["adts_structure"] = {"frames": count, "bytes_consumed": offset, "file_bytes": len(data), "aot_rate_index_channels": sorted(modes), "decode_test": False}
    (HERE / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("Evidence written to", HERE / "results.json")
    return 0 if unit.wasSuccessful() and all(x["comparison"]["exact_match"] for x in result["synthetic"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
