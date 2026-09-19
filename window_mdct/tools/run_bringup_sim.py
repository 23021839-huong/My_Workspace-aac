#!/usr/bin/env python3
"""Run native-core and AXI-wrapper regressions with GHDL; preserve all logs."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sw"))
from mdct_golden import load_frames

FFT_UNITS = ("fft_radix2_twiddle_rom", "fft_radix2_addr_gen", "fft_radix2_memory",
             "fft_radix2_butterfly", "fft_radix2_control", "fft_radix2_core")
MDCT_UNITS = ("mdct_window_rom", "mdct_rotation_rom", "mdct_pcm_memory",
              "mdct_work_memory", "mdct_fft_cache_memory", "mdct_spectrum_memory",
              "mdct_window_fold", "mdct_dct4_pre", "mdct_dct4_post", "mdct_control", "mdct_core")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ghdl", default="ghdl", help="executable name or full path")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build" / "bringup_sim")
    args = parser.parse_args()
    executable = shutil.which(args.ghdl)
    if executable is None:
        parser.error("GHDL not found; install it or pass --ghdl /path/to/ghdl")
    golden = ROOT / "golden" / "radix2_q31_v1"
    load_frames(golden)
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    fft = ROOT / "fft_radix2_core" / "rtl"
    sources = [fft / "fft_radix2_pkg.vhd", ROOT / "rtl" / "mdct_pkg.vhd"]
    sources += [fft / (unit + ".vhd") for unit in FFT_UNITS]
    sources += [ROOT / "rtl" / (unit + ".vhd") for unit in MDCT_UNITS]
    sources += [ROOT / "board" / "pynq_z2" / "mdct_axi_lite.vhd"]
    benches = ("tb_mdct_core", "tb_mdct_axi_lite")
    sources += [ROOT / "tb" / (unit + ".vhd") for unit in benches]

    def run(arguments, name, marker=None):
        completed = subprocess.run([executable, *arguments], cwd=build,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, timeout=300)
        (build / name).write_text(completed.stdout, encoding="utf-8")
        print(completed.stdout[-4000:])
        if completed.returncode or (marker and marker not in completed.stdout):
            raise RuntimeError(f"simulation failed; see {build / name}")

    # Vivado true-dual-port BRAM templates use shared non-protected variables.
    # GHDL requires relaxed rules for this synthesis idiom.
    flags = ["--std=08", "-frelaxed-rules"]
    run(["-a", *flags, *map(str, sources)], "compile.log")
    for bench in benches:
        # -r elaborates with the absolute generic before opening golden files.
        run(["-r", *flags, bench, "-gGOLDEN_DIR=" + golden.as_posix(),
             "--assert-level=error"], bench + ".log", "PASS: " + bench[3:])
    print(f"PASS: native core and AXI wrapper; logs: {build}")


if __name__ == "__main__":
    main()
