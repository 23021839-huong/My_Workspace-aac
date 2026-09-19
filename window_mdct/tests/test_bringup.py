"""Host-only tests: these never program an FPGA or claim hardware correctness."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "tools"))
import mdct_pynq as drv
from mdct_golden import compare_spectrum, load_frames
from compare_board_float import compare_results
from gen_mdct_vectors import PCM_SNAPSHOT_LENGTH, VECTOR_SUITES
from pack_pynq_z2 import package
from run_mdct_board import run_frames, summarize_timings


class FakeMMIO:
    """Immediate protocol responses with recognizable signed output values."""
    def __init__(self):
        self.count = 0
        self.status = drv.STATUS_PCM_READY
        self.exponent = 12
        self.spec_index = 0
        self.result = 0
        self.writes = []
        self.stall_after = None

    def read(self, address):
        if address == drv.REG_STATUS:
            if self.stall_after is not None and self.count >= self.stall_after:
                return 0
            return self.status
        if address == drv.REG_PCM_COUNT:
            return self.count
        if address == drv.REG_SPEC_DATA:
            return self.result
        if address == drv.REG_MDCT_EXP:
            return self.exponent
        if address == drv.REG_ID:
            return drv.MDCT_ID
        raise AssertionError(f"unexpected read: {address}")

    def write(self, address, data):
        self.writes.append((address, data))
        if address == drv.REG_PCM_DATA:
            self.count += 1
        elif address == drv.REG_SPEC_INDEX:
            self.spec_index = data
        elif address == drv.REG_CONTROL:
            if data & drv.CONTROL_CLEAR_FLAGS:
                self.status = drv.STATUS_PCM_READY
            if data & drv.CONTROL_START:
                assert self.count == 2048
                self.count = 0
                self.status = drv.STATUS_PCM_READY | drv.STATUS_DONE
                self.exponent = 9 if ((data >> 8) & 3) == 2 else 12
            if data & drv.CONTROL_SPEC_READ:
                self.result = (self.spec_index - 512) & 0xffffffff
                self.spec_index += 1
                self.status |= drv.STATUS_SPEC_VALID


def fake_driver():
    device = drv.MdctPynq.__new__(drv.MdctPynq)
    device.mmio = FakeMMIO()
    device._needs_reload = False
    device.last_timings = {}
    return device


class DriverTests(unittest.TestCase):
    def test_signed_pcm_spectrum_and_successive_modes(self):
        device = fake_driver()
        for block in (0, 1, 2, 3):
            result, exponent = device.transform([-32768, 32767] * 1024, block_type=block)
            self.assertEqual(result.dtype, np.dtype("int32"))
            self.assertEqual(result.tolist(), list(range(-512, 512)))
            self.assertEqual(exponent, 9 if block == 2 else 12)
            self.assertEqual(set(device.last_timings),
                             {"load_ms", "compute_poll_ms", "read_ms", "total_ms"})
        samples = [data for address, data in device.mmio.writes if address == drv.REG_PCM_DATA]
        self.assertEqual(samples[:2], [0x8000, 0x7fff])
        self.assertEqual(len(samples), 4 * 2048)

    def test_invalid_inputs_do_not_write_hardware(self):
        device = fake_driver()
        for pcm in ([0] * 1023, [32768] * 2048, [0.5] * 2048):
            with self.assertRaises((ValueError, TypeError)):
                device.transform(pcm)
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                device.transform([0] * 2048, timeout_s=timeout)
        with self.assertRaises(TypeError):
            device.transform([0] * 2048, block_type=1.5)
        self.assertEqual(device.mmio.writes, [])

    def test_partial_previous_frame_is_not_silently_cleared(self):
        device = fake_driver()
        device.mmio.count = 12
        with self.assertRaisesRegex(RuntimeError, "not idle/empty"):
            device.transform([0] * 2048, clear_history=True)
        self.assertEqual(device.mmio.writes, [])

    def test_timeout_bounds_entire_frame_and_blocks_retry(self):
        device = fake_driver()
        # Every call is ready, but each poll costs 10 ms of simulated wall time.
        # A per-sample timeout would incorrectly allow this whole transfer.
        ticks = iter(i / 100 for i in range(100000))
        with patch.object(drv.time, "monotonic", side_effect=lambda: next(ticks)):
            with self.assertRaises(TimeoutError):
                device.transform([0] * 2048, timeout_s=0.1)
        self.assertLess(device.mmio.count, 20)
        writes = len(device.mmio.writes)
        with self.assertRaisesRegex(RuntimeError, "reload"):
            device.transform([0] * 2048)
        self.assertEqual(len(device.mmio.writes), writes)

    def test_hardware_error_is_not_erased(self):
        device = fake_driver()
        device.mmio.status |= drv.STATUS_ERROR
        with self.assertRaises(RuntimeError):
            device.transform([0] * 2048)
        self.assertEqual(device.mmio.writes, [])

    def test_wrong_exponent_fails(self):
        device = fake_driver()
        original = device.mmio.read
        device.mmio.read = lambda address: 7 if address == drv.REG_MDCT_EXP else original(address)
        with self.assertRaisesRegex(RuntimeError, "exponent"):
            device.transform([0] * 2048)
        self.assertTrue(device._needs_reload)


class GoldenAndRunnerTests(unittest.TestCase):
    def test_timing_summary_reports_tail_latency(self):
        reports = [
            {"total_ms": value, "compute_poll_ms": value / 10.0}
            for value in (1.0, 2.0, 3.0, 4.0, 100.0)
        ]
        summary = summarize_timings(reports)
        self.assertEqual(summary["total_ms"]["count"], 5)
        self.assertEqual(summary["total_ms"]["minimum"], 1.0)
        self.assertEqual(summary["total_ms"]["p50"], 3.0)
        self.assertGreater(summary["total_ms"]["p95"], 80.0)
        self.assertEqual(summary["total_ms"]["maximum"], 100.0)
        self.assertNotIn("load_ms", summary)

    def test_extended_suite_is_q15_continuous_and_covers_modes(self):
        suite = VECTOR_SUITES["extended"]
        self.assertEqual(len(suite.cases), 10)
        self.assertEqual(len(suite.block_sequence), 10)
        self.assertEqual(set(map(int, suite.block_sequence)), {0, 1, 2, 3})
        self.assertEqual(set(map(int, suite.shape_sequence)), {0, 1})
        for case in suite.cases:
            seed = (0x4D444354 ^ (case.case_id * 0x9E3779B9)) & 0xFFFFFFFF
            previous = None
            for frame_id in range(len(suite.block_sequence)):
                pcm = case.generator(frame_id, seed)
                self.assertEqual(len(pcm), PCM_SNAPSHOT_LENGTH)
                self.assertTrue(all(-32768 <= value <= 32767 for value in pcm))
                if previous is not None:
                    self.assertEqual(previous[1024:], pcm[:1024])
                previous = pcm

    def test_versioned_corpus_and_mode_history(self):
        frames, hashes = load_frames(ROOT / "golden" / "radix2_q31_v1")
        self.assertEqual(len(frames), 18)
        self.assertEqual(sum(f.reset_before for f in frames), 3)
        self.assertEqual([f.block_type for f in frames[:6]], [0, 0, 1, 2, 3, 0])
        self.assertEqual([f.right_shape for f in frames[:6]], [0, 1, 0, 1, 0, 1])
        self.assertEqual(len(hashes), 13)

    def test_corrupted_expected_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "golden"
            shutil.copytree(ROOT / "golden" / "radix2_q31_v1", directory)
            with (directory / "mdct_out_q31.txt").open("a") as stream:
                stream.write("0 0 0 00000001 12\n")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_frames(directory)

    def test_checker_detects_one_lsb_exponent_and_short_output(self):
        self.assertFalse(compare_spectrum([0, 1], [0, 2], 12, 12)["passed"])
        self.assertFalse(compare_spectrum([0, 1], [0, 1], 12, 9)["passed"])
        with self.assertRaises(ValueError):
            compare_spectrum([0, 1], [0], 12, 12)
        report = compare_spectrum([2147483647], np.array([-2147483648], dtype=np.int32), 12, 12)
        self.assertEqual(report["max_abs_error_lsb"], 4294967295)

    def test_runner_preserves_reset_sequence_and_reports_injected_error(self):
        frames, _ = load_frames(ROOT / "golden" / "radix2_q31_v1")
        calls = []
        class Device:
            last_timings = {"total_ms": 1.0}
            def transform(self, pcm, **kwargs):
                frame = frames[len(calls) % len(frames)]
                calls.append(kwargs)
                actual = list(frame.spectrum)
                if len(calls) == 2:
                    actual[5] += 1
                return actual, frame.exponent
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            reports = run_frames(Device(), frames, 2, 5, Path(temporary), print_io=True)
            self.assertEqual(len(reports), 36)
            self.assertEqual(sum(not row["passed"] for row in reports), 1)
            self.assertEqual(reports[1]["first_mismatches"][0]["bin"], 5)
            self.assertEqual(sum(call["clear_history"] for call in calls), 6)
            input_rows = (Path(temporary) / "input_pcm.txt").read_text().splitlines()
            output_rows = (Path(temporary) / "output_compare.csv").read_text().splitlines()
            self.assertEqual(len(input_rows), 36 * 2048)
            self.assertEqual(len(output_rows), 1 + 36 * 1024)
            self.assertIn(",1,", output_rows[1 + 1024 + 5])

    def test_board_capture_float64_comparison(self):
        frames, _ = load_frames(ROOT / "golden" / "radix2_q31_v1")
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            results = Path(temporary)
            with (results / "input_pcm.txt").open("w", encoding="ascii") as inputs, \
                    (results / "actual_q31.txt").open("w", encoding="ascii") as actual:
                for frame in frames:
                    for index, value in enumerate(frame.pcm):
                        inputs.write(
                            f"0 {frame.case_id} {frame.frame_id} {index} "
                            f"{value} {value & 0xffff:04X}\n"
                        )
                    for index, value in enumerate(frame.spectrum):
                        actual.write(
                            f"0 {frame.case_id} {frame.frame_id} {index} "
                            f"{value & 0xffffffff:08X} {frame.exponent}\n"
                        )
            summary = compare_results(results, ROOT / "golden" / "radix2_q31_v1")
            self.assertEqual(summary["comparison_count"], 18432)
            self.assertEqual(summary["input_mismatch_count_vs_golden"], 0)
            self.assertAlmostEqual(summary["rmse"], 3.9305574335739e-4, places=14)
            self.assertAlmostEqual(summary["relative_rms"], 1.87898108810111e-5, places=14)
            self.assertAlmostEqual(summary["max_abs_error"], 1.52640359237921e-2, places=14)
            self.assertEqual(len((results / "float_frames.csv").read_text().splitlines()), 19)
            self.assertEqual(
                len((results / "float_output_compare.csv").read_text().splitlines()),
                18433,
            )


class PackageTests(unittest.TestCase):
    def test_export_pair_checksums_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            info = "\n".join(("export_status=PASS", "internal_timing_coverage=PASS",
                              "part=xc7z020clg400-1", "base_address=0x43C00000",
                              "setup_slack_ns=1.0", "hold_slack_ns=0.1"))
            (directory / "build_info.txt").write_text(info)
            # Deliberately artificial artifacts, confined to this temporary test.
            (directory / "mdct_pynq_z2.bit").write_bytes(b"unit-test-only")
            destination = directory / "test.zip"
            with self.assertRaises(FileNotFoundError):
                package(directory, destination)
            self.assertFalse(destination.exists())
            (directory / "mdct_pynq_z2.hwh").write_bytes(b"unit-test-only")
            package(directory, destination)
            with zipfile.ZipFile(destination) as archive:
                self.assertIn("mdct_pynq_z2/compare_board_float.py", archive.namelist())
                for row in archive.read("mdct_pynq_z2/SHA256SUMS").decode().splitlines():
                    digest, name = row.split()
                    self.assertEqual(hashlib.sha256(archive.read("mdct_pynq_z2/" + name)).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                package(directory, destination)
            (directory / "build_info.txt").write_text(info.replace("setup_slack_ns=1.0", "setup_slack_ns=-1.0"))
            with self.assertRaises(ValueError):
                package(directory, directory / "bad.zip")


if __name__ == "__main__":
    unittest.main()
