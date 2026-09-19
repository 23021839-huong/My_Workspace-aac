#!/usr/bin/env python3
"""Package one successful Vivado export with the immutable board regression."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sw"))
from mdct_golden import load_frames


def package(overlay_dir: Path, destination: Path) -> Path:
    info = dict(row.split("=", 1) for row in
                (overlay_dir / "build_info.txt").read_text(encoding="utf-8").splitlines() if row)
    if info.get("export_status") != "PASS" or info.get("internal_timing_coverage") != "PASS":
        raise ValueError("overlay export has not passed the Vivado checks")
    if info.get("part") != "xc7z020clg400-1" or info.get("base_address") != "0x43C00000":
        raise ValueError("wrong FPGA part or AXI base address")
    for key in ("setup_slack_ns", "hold_slack_ns"):
        value = float(info[key])
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid {key}: {value}")
    golden = ROOT / "golden" / "radix2_q31_v1"
    frames, _ = load_frames(golden)
    files = {name: overlay_dir / name for name in
             ("mdct_pynq_z2.bit", "mdct_pynq_z2.hwh", "build_info.txt")}
    files.update({name: ROOT / "sw" / name for name in
                  ("mdct_pynq.py", "mdct_golden.py", "run_mdct_board.py",
                   "compare_board_float.py")})
    files.update({"golden/" + path.name: path for path in golden.iterdir() if path.is_file()})
    files.update({"reports/" + path.name: path for path in (overlay_dir / "reports").glob("*.rpt")})
    files["HUONG_DAN.md"] = ROOT / "docs" / "pynq_z2_bringup.md"
    missing = [path for path in files.values() if not path.is_file() or path.stat().st_size == 0]
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "missing or empty deployment files; sync the complete window_mdct tree:\n"
            + formatted
        )
    payload = {}
    for name, path in files.items():
        data = path.read_bytes()
        payload[name] = data
    manifest = {"build": info, "golden_frames": len(frames),
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
    payload["bundle_manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    payload["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payload.items()
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr("mdct_pynq_z2/" + name, data)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overlay-dir", required=True, type=Path,
                        help="timestamp directory printed by the Vivado script")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or args.overlay_dir / "mdct_pynq_z2_bundle.zip"
    print(f"Created {package(args.overlay_dir, destination)}")


if __name__ == "__main__":
    main()
