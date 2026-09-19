"""Read the immutable MDCT v1 corpus without regenerating expected results."""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GoldenFrame:
    case_id: int
    frame_id: int
    reset_before: bool
    block_type: int
    right_shape: int
    exponent: int
    pcm: list[int]
    spectrum: list[int]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_checksums(directory: Path) -> dict[str, str]:
    checksums = {}
    for row in (directory / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        digest, name = row.split()
        if Path(name).name != name or name in checksums:
            raise ValueError(f"invalid checksum entry: {name}")
        if sha256(directory / name) != digest:
            raise ValueError(f"golden checksum mismatch: {name}; restore the original corpus")
        checksums[name] = digest
    required = {"manifest.csv", "pcm_in_s16.txt", "mdct_out_q31.txt", "contract.meta"}
    if not required <= checksums.keys():
        raise ValueError("missing checksums for required golden files")
    return checksums


def _signed_hex(token: str, width: int) -> int:
    raw = int(token, 16)
    if not 0 <= raw < (1 << width):
        raise ValueError(f"out-of-range {width}-bit value: {token}")
    return raw - (1 << width) if raw & (1 << (width - 1)) else raw


def load_frames(directory: Path) -> tuple[list[GoldenFrame], dict[str, str]]:
    hashes = verify_checksums(directory)
    frames = {}
    sub_ids = {}
    with (directory / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["schema"] != "mdct-r2-fdkq15-v1":
                raise ValueError("unsupported golden schema")
            key = (int(row["case_id"]), int(row["frame_id"]))
            block, shape = int(row["block_type"]), int(row["right_shape"])
            reset, sub = int(row["reset_before"]), int(row["sub_id"])
            exponent = int(row["exp_post"])
            if block not in range(4) or shape not in range(2) or reset not in range(2):
                raise ValueError(f"invalid mode for frame {key}")
            if exponent != (9 if block == 2 else 12):
                raise ValueError(f"invalid exponent for frame {key}")
            if key not in frames:
                if sub != 0:
                    raise ValueError(f"missing first sub-transform: {key}")
                frames[key] = GoldenFrame(*key, bool(reset), block, shape, exponent, [], [])
                sub_ids[key] = []
            frame = frames[key]
            if (frame.block_type, frame.right_shape, frame.exponent, frame.reset_before) != \
                    (block, shape, exponent, bool(reset)):
                raise ValueError(f"inconsistent frame metadata: {key}")
            sub_ids[key].append(sub)
    if not frames:
        raise ValueError("empty golden corpus")
    previous_case, previous_frame = None, -1
    for key, frame in frames.items():
        if frame.case_id != previous_case:
            if not frame.reset_before or frame.frame_id != 0:
                raise ValueError(f"case must start at reset/frame zero: {key}")
            previous_frame = -1
        if frame.frame_id != previous_frame + 1:
            raise ValueError(f"non-contiguous frame sequence: {key}")
        previous_case, previous_frame = key
        if sub_ids[key] != list(range(8 if frame.block_type == 2 else 1)):
            raise ValueError(f"invalid sub-transform sequence: {key}")

    for name, attr, width, size in (
        ("pcm_in_s16.txt", "pcm", 16, 2048),
        ("mdct_out_q31.txt", "spectrum", 32, 1024),
    ):
        with (directory / name).open(encoding="utf-8") as stream:
            for row in stream:
                fields = row.split()
                if len(fields) != (5 if attr == "spectrum" else 4):
                    raise ValueError(f"malformed row in {name}")
                case_id, frame_id, index = map(int, fields[:3])
                frame = frames[(case_id, frame_id)]
                values = getattr(frame, attr)
                if index != len(values) or index >= size:
                    raise ValueError(f"duplicate/missing/out-of-order index in {name}")
                values.append(_signed_hex(fields[3], width))
                if attr == "spectrum" and int(fields[4]) != frame.exponent:
                    raise ValueError("spectrum exponent disagrees with manifest")
        if any(len(getattr(frame, attr)) != size for frame in frames.values()):
            raise ValueError(f"incomplete frame in {name}")
    return list(frames.values()), hashes


def compare_spectrum(expected, actual, expected_exp: int, actual_exp: int) -> dict:
    actual = [int(value) for value in actual]
    if len(actual) != len(expected):
        raise ValueError(f"expected {len(expected)} bins, received {len(actual)}")
    errors = [got - want for got, want in zip(actual, expected)]
    indices = [i for i, value in enumerate(errors) if value]
    return {
        "passed": not indices and actual_exp == expected_exp,
        "mismatch_count": len(indices),
        "max_abs_error_lsb": max(map(abs, errors), default=0),
        "expected_exp": expected_exp,
        "actual_exp": int(actual_exp),
        "first_mismatches": [
            {"bin": i, "expected": expected[i], "actual": actual[i]} for i in indices[:16]
        ],
    }
