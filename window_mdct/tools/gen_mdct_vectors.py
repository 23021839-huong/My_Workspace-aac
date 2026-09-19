#!/usr/bin/env python3
"""Generate versioned AAC-LC MDCT boundary vectors for C++/NumPy/VHDL.

The emitted fixed-point values come only from ``mdct_radix2_model.py`` and
literal FDK ROM tables.  ``numpy_metrics.csv`` is a separate float64 quality
report and is never used as the source of bit-exact hexadecimal values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import math
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
WINDOW_MDCT_DIR = SCRIPT_DIR.parent
REPO_ROOT = WINDOW_MDCT_DIR.parent.parent
REF_DIR = WINDOW_MDCT_DIR / "ref"
if str(REF_DIR) not in sys.path:
    sys.path.insert(0, str(REF_DIR))

from mdct_radix2_model import (  # noqa: E402
    BlockType,
    FFT_SCALE_MASK,
    FdkRom,
    FrameTrace,
    MdctRadix2Model,
    ModelError,
    PCM_SNAPSHOT_LENGTH,
    WindowShape,
    float_metrics,
    hex_s16,
    hex_s32,
    run_self_test,
)


SCHEMA = "mdct-r2-fdkq15-v1"
FDK_COMMIT = "35f9c13cb6df0c5d4e7ba958ef2d251c48b8d1d9"
DEFAULT_OUTPUT = WINDOW_MDCT_DIR / "golden" / "radix2_q31_v1"
EXTENDED_OUTPUT = WINDOW_MDCT_DIR / "build" / "golden" / "radix2_q31_extended_v1"
FRAME_HOP = 1024

BLOCK_SEQUENCE = (
    BlockType.LONG,
    BlockType.LONG,
    BlockType.START,
    BlockType.SHORT,
    BlockType.STOP,
    BlockType.LONG,
)
SHAPE_SEQUENCE = (
    WindowShape.SINE,
    WindowShape.KBD,
    WindowShape.SINE,
    WindowShape.KBD,
    WindowShape.SINE,
    WindowShape.KBD,
)

# A longer legal AAC-LC transition sequence for board stress tests. Adjacent
# 2048-sample snapshots in this suite overlap by 1024 samples, like real encoder
# input, instead of being unrelated synthetic frames.
EXTENDED_BLOCK_SEQUENCE = (
    BlockType.LONG,
    BlockType.LONG,
    BlockType.LONG,
    BlockType.START,
    BlockType.SHORT,
    BlockType.SHORT,
    BlockType.SHORT,
    BlockType.STOP,
    BlockType.LONG,
    BlockType.LONG,
)
EXTENDED_SHAPE_SEQUENCE = (
    WindowShape.SINE,
    WindowShape.SINE,
    WindowShape.KBD,
    WindowShape.KBD,
    WindowShape.SINE,
    WindowShape.KBD,
    WindowShape.SINE,
    WindowShape.KBD,
    WindowShape.SINE,
    WindowShape.KBD,
)
EXTENDED_SAMPLE_COUNT = (
    (len(EXTENDED_BLOCK_SEQUENCE) - 1) * FRAME_HOP + PCM_SNAPSHOT_LENGTH
)


@dataclass(frozen=True)
class VectorCase:
    case_id: int
    name: str
    description: str
    generator: Callable[[int, int], list[int]]
    continuous_seed: bool = False


@dataclass(frozen=True)
class VectorSuite:
    name: str
    cases: tuple[VectorCase, ...]
    block_sequence: tuple[BlockType, ...]
    shape_sequence: tuple[WindowShape, ...]


def _zero_pcm(_frame: int, _seed: int) -> list[int]:
    return [0] * PCM_SNAPSHOT_LENGTH


def _impulse_pcm(frame: int, _seed: int) -> list[int]:
    positions = (0, 447, 448, 1599, 1600, 2047)
    result = [0] * PCM_SNAPSHOT_LENGTH
    result[positions[frame % len(positions)]] = 32767 if (frame & 1) == 0 else -32768
    return result


def _lcg_pcm(seed: int) -> list[int]:
    result: list[int] = []
    state = seed & 0xFFFFFFFF
    for _ in range(PCM_SNAPSHOT_LENGTH):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        raw = (state >> 16) & 0xFFFF
        result.append(raw - 0x10000 if raw & 0x8000 else raw)
    return result


def _stress_pcm(frame: int, seed: int) -> list[int]:
    mode = frame % 6
    if mode == 0:
        return [32767] * PCM_SNAPSHOT_LENGTH
    if mode == 1:
        return [-32768] * PCM_SNAPSHOT_LENGTH
    if mode == 2:
        return [32767 if (index & 1) == 0 else -32768 for index in range(PCM_SNAPSHOT_LENGTH)]
    if mode == 3:
        return _lcg_pcm(seed ^ 0xA5A5A5A5)
    if mode == 4:
        return [((index * 97 + 0x1234) & 0xFFFF) - 0x8000 for index in range(PCM_SNAPSHOT_LENGTH)]
    random_values = _lcg_pcm(seed ^ 0x5A5A5A5A)
    # Make the extrema explicit while retaining a dense deterministic signal.
    random_values[0] = -32768
    random_values[1] = 32767
    random_values[447] = -32768
    random_values[448] = 32767
    random_values[1599] = -32768
    random_values[1600] = 32767
    return random_values


CASES = (
    VectorCase(0, "zero_transition", "zero input across LONG/LONG/START/SHORT/STOP/LONG", _zero_pcm),
    VectorCase(1, "impulse_boundaries", "signed impulses at MDCT and short-block boundaries", _impulse_pcm),
    VectorCase(2, "extrema_prng", "DC extrema, alternating extrema, ramp and fixed-seed LCG", _stress_pcm),
)


def _clip_q15(value: int | float) -> int:
    return min(32767, max(-32768, int(round(value))))


def _continuous_pcm(frame: int, sample: Callable[[int], int]) -> list[int]:
    base = frame * FRAME_HOP
    return [_clip_q15(sample(base + index)) for index in range(PCM_SNAPSHOT_LENGTH)]


def _near_zero_pcm(frame: int, _seed: int) -> list[int]:
    pattern = (-3, -2, -1, 0, 1, 2, 3, 0)
    return _continuous_pcm(frame, lambda index: pattern[index % len(pattern)])


def _dc_offset_pcm(frame: int, _seed: int) -> list[int]:
    return _continuous_pcm(frame, lambda _index: 12345)


def _tone_997_pcm(frame: int, _seed: int) -> list[int]:
    scale = 2.0 * math.pi * 997.0 / 48000.0
    return _continuous_pcm(frame, lambda index: 29490.0 * math.sin(scale * index))


def _multitone_pcm(frame: int, _seed: int) -> list[int]:
    def sample(index: int) -> int:
        phase = 2.0 * math.pi * index / 48000.0
        return _clip_q15(
            14000.0 * math.sin(440.0 * phase)
            + 9000.0 * math.sin(3000.0 * phase)
            + 7000.0 * math.sin(11000.0 * phase)
        )

    return _continuous_pcm(frame, sample)


def _chirp_pcm(frame: int, _seed: int) -> list[int]:
    duration = EXTENDED_SAMPLE_COUNT / 48000.0
    slope = (20000.0 - 20.0) / duration

    def sample(index: int) -> int:
        time_s = index / 48000.0
        phase = 2.0 * math.pi * (20.0 * time_s + 0.5 * slope * time_s * time_s)
        return _clip_q15(28000.0 * math.sin(phase))

    return _continuous_pcm(frame, sample)


def _transient_bursts_pcm(frame: int, _seed: int) -> list[int]:
    def sample(index: int) -> int:
        phase = index % 4096
        impulses = {
            0: 32767,
            1: -32768,
            447: 30000,
            448: -30000,
            1023: 32767,
            1024: -32768,
            1599: 24576,
            1600: -24576,
            2047: 32767,
        }
        if phase in impulses:
            return impulses[phase]
        if 2304 <= phase < 2432:
            return 26000 if ((phase // 8) & 1) == 0 else -26000
        return 0

    return _continuous_pcm(frame, sample)


def _clipped_tone_pcm(frame: int, _seed: int) -> list[int]:
    scale = 2.0 * math.pi * 1000.0 / 48000.0
    return _continuous_pcm(frame, lambda index: 52000.0 * math.sin(scale * index))


def _sample_hash(index: int, seed: int) -> int:
    value = (index + seed + 0x9E3779B9) & 0xFFFFFFFF
    value ^= value >> 16
    value = (value * 0x7FEB352D) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 0x846CA68B) & 0xFFFFFFFF
    value ^= value >> 16
    return value


def _low_level_noise_pcm(frame: int, seed: int) -> list[int]:
    return _continuous_pcm(
        frame, lambda index: int(_sample_hash(index, seed) & 0x1F) - 16
    )


def _fullband_noise_pcm(frame: int, seed: int) -> list[int]:
    def sample(index: int) -> int:
        raw = (_sample_hash(index, seed) >> 16) & 0xFFFF
        return raw - 0x10000 if raw & 0x8000 else raw

    return _continuous_pcm(frame, sample)


def _speech_like_pcm(frame: int, _seed: int) -> list[int]:
    def sample(index: int) -> int:
        time_s = index / 48000.0
        envelope = 0.35 + 0.65 * (
            0.5 + 0.5 * math.sin(2.0 * math.pi * 3.0 * time_s)
        )
        voiced = (
            15000.0 * math.sin(2.0 * math.pi * 120.0 * time_s)
            + 7000.0 * math.sin(2.0 * math.pi * 240.0 * time_s)
            + 4000.0 * math.sin(2.0 * math.pi * 360.0 * time_s)
            + 2500.0 * math.sin(2.0 * math.pi * 480.0 * time_s)
        )
        return _clip_q15(envelope * voiced)

    return _continuous_pcm(frame, sample)


EXTENDED_CASES = (
    VectorCase(
        0, "near_zero_lsb", "near-zero periodic values exercising sign and low bits",
        _near_zero_pcm, True,
    ),
    VectorCase(
        1, "dc_offset", "constant positive DC input with realistic frame overlap",
        _dc_offset_pcm, True,
    ),
    VectorCase(
        2, "tone_997hz", "near-full-scale 997 Hz coherent continuous tone",
        _tone_997_pcm, True,
    ),
    VectorCase(
        3, "multitone", "continuous 440 Hz, 3 kHz and 11 kHz multitone",
        _multitone_pcm, True,
    ),
    VectorCase(
        4, "chirp_20_20k", "continuous 20 Hz to 20 kHz linear chirp",
        _chirp_pcm, True,
    ),
    VectorCase(
        5, "transient_bursts", "impulses, steps and bursts around transform boundaries",
        _transient_bursts_pcm, True,
    ),
    VectorCase(
        6, "clipped_tone", "hard-clipped 1 kHz tone stressing Q15 extrema",
        _clipped_tone_pcm, True,
    ),
    VectorCase(
        7, "low_level_noise", "deterministic noise limited to roughly five significant bits",
        _low_level_noise_pcm, True,
    ),
    VectorCase(
        8, "fullband_noise", "deterministic full-range stateless noise",
        _fullband_noise_pcm, True,
    ),
    VectorCase(
        9, "speech_like", "voiced harmonic signal with a slow amplitude envelope",
        _speech_like_pcm, True,
    ),
)


VECTOR_SUITES = {
    "baseline": VectorSuite("baseline", CASES, BLOCK_SEQUENCE, SHAPE_SEQUENCE),
    "extended": VectorSuite(
        "extended", EXTENDED_CASES, EXTENDED_BLOCK_SEQUENCE, EXTENDED_SHAPE_SEQUENCE
    ),
}


OUTPUT_NAMES = (
    "contract.meta",
    "cases.csv",
    "manifest.csv",
    "rom_window_q15.txt",
    "rom_fft_q15.txt",
    "rom_dct_q15.txt",
    "pcm_in_s16.txt",
    "fold_q31.txt",
    "pre_q31.txt",
    "fft_stage_q31.txt",
    "post_q31.txt",
    "mdct_out_q31.txt",
    "numpy_metrics.csv",
    "checksums.sha256",
)


def _float_text(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return format(value, ".17g")


def _prepare_output(directory: Path, force: bool) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {name: directory / name for name in OUTPUT_NAMES}
    existing = [path for name, path in paths.items() if name != "checksums.sha256" and path.exists()]
    if existing and not force:
        joined = ", ".join(str(path) for path in existing[:4])
        suffix = " ..." if len(existing) > 4 else ""
        raise ModelError(f"output files already exist: {joined}{suffix}; pass --force to replace")
    return paths


def _dump_roms(rom: FdkRom, window_file, fft_file, dct_file) -> dict[str, int]:
    table_order = (
        (0, 1024, WindowShape.SINE),
        (1, 1024, WindowShape.KBD),
        (2, 128, WindowShape.SINE),
        (3, 128, WindowShape.KBD),
    )
    window_rows = 0
    for table_id, length, shape in table_order:
        for address, value in enumerate(rom.window(length, shape)):
            window_file.write(
                f"{table_id} {address} {hex_s16(value.re)} {hex_s16(value.im)}\n"
            )
            window_rows += 1

    for address, value in enumerate(rom.sine_table_512):
        fft_file.write(f"{address} {hex_s16(value.re)} {hex_s16(value.im)}\n")
    for address, value in enumerate(rom.sine_table_1024):
        dct_file.write(f"{address} {hex_s16(value.re)} {hex_s16(value.im)}\n")
    return {
        "rom_window_rows": window_rows,
        "rom_fft_rows": len(rom.sine_table_512),
        "rom_dct_rows": len(rom.sine_table_1024),
    }


def _write_frame_vectors(
    case_id: int,
    frame: FrameTrace,
    reset_before: bool,
    manifest_writer,
    pcm_file,
    fold_file,
    pre_file,
    fft_stage_file,
    post_file,
    mdct_file,
    metrics_writer,
    include_float_metrics: bool,
    counts: dict[str, int],
) -> None:
    for index, value in enumerate(frame.pcm):
        pcm_file.write(f"{case_id} {frame.frame_id} {index} {hex_s16(value)}\n")
        counts["pcm_rows"] += 1

    n_spec = len(frame.subblocks)
    for sub in frame.subblocks:
        params = sub.params
        nfft = sub.fft.nfft
        manifest_writer.writerow(
            (
                SCHEMA,
                case_id,
                case_id,
                frame.frame_id,
                int(reset_before),
                sub.sub_id,
                int(frame.block_type),
                int(params.right_shape),
                int(params.left_shape),
                n_spec,
                params.tl,
                params.fl,
                params.fr,
                params.nl,
                params.nr,
                params.pcm_base,
                2 * params.tl,
                params.output_base,
                nfft,
                -1,
                FFT_SCALE_MASK[nfft],
                sub.exp_fold,
                sub.exp_pre,
                sub.fft.scale_exp,
                sub.exp_fft_out,
                sub.exp_post,
            )
        )
        counts["manifest_rows"] += 1

        for index, value in enumerate(sub.fold):
            fold_file.write(
                f"{case_id} {frame.frame_id} {sub.sub_id} {index} "
                f"{hex_s32(value)} {sub.exp_fold}\n"
            )
            counts["fold_rows"] += 1

        for index, value in enumerate(sub.pre):
            pre_file.write(
                f"{case_id} {frame.frame_id} {sub.sub_id} {index} "
                f"{hex_s32(value.re)} {hex_s32(value.im)} {sub.exp_pre}\n"
            )
            counts["pre_rows"] += 1

        for stage in sub.fft.stages:
            cumulative_exp = sub.exp_pre + stage.scale_exp
            for index, value in enumerate(stage.ram):
                fft_stage_file.write(
                    f"{case_id} {frame.frame_id} {sub.sub_id} {stage.stage} {index} "
                    f"{hex_s32(value.re)} {hex_s32(value.im)} {stage.scale_exp} "
                    f"{cumulative_exp}\n"
                )
                counts["fft_stage_rows"] += 1

        for index, value in enumerate(sub.post):
            post_file.write(
                f"{case_id} {frame.frame_id} {sub.sub_id} {index} "
                f"{hex_s32(value)} {sub.exp_post}\n"
            )
            counts["post_rows"] += 1

        if include_float_metrics:
            metric = float_metrics(sub)
            metrics_writer.writerow(
                (
                    case_id,
                    frame.frame_id,
                    sub.sub_id,
                    params.tl,
                    nfft,
                    _float_text(metric.fft.rel_rms),
                    _float_text(metric.fft.rms_error),
                    _float_text(metric.fft.max_abs_error),
                    _float_text(metric.fft.snr_db),
                    _float_text(metric.mdct.rel_rms),
                    _float_text(metric.mdct.rms_error),
                    _float_text(metric.mdct.max_abs_error),
                    _float_text(metric.mdct.snr_db),
                )
            )
            counts["metrics_rows"] += 1

    for index, value in enumerate(frame.output):
        mdct_file.write(
            f"{case_id} {frame.frame_id} {index} {hex_s32(value)} {frame.exponent}\n"
        )
        counts["mdct_rows"] += 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_contract(
    path: Path,
    rom: FdkRom,
    seed: int,
    include_float_metrics: bool,
    counts: dict[str, int],
) -> None:
    source_digest = _sha256(rom.source_path)
    try:
        source_name = rom.source_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # A deliberately external --rom-source remains explicit, while the
        # normal checked-in contract is portable between Windows and Linux.
        source_name = rom.source_path.as_posix()
    lines = (
        f"schema={SCHEMA}",
        f"fdkCommit={FDK_COMMIT}",
        f"fdkRomSource={source_name}",
        f"fdkRomSha256={source_digest}",
        "codec=AAC-LC",
        "frameLength=1024",
        "pcmSnapshotLength=2048",
        "pcmFormat=signed16",
        "dataFormat=Q31_signed32",
        "coefficientFormat=Q15_signed16",
        "fftDirection=negative_exponent",
        "fftAlgorithm=pure_radix2_DIT",
        "fftInputOrder=natural",
        "fftStageRamOrder=bit_reversed_DIT_storage",
        "fftOutputOrder=natural",
        "fftScaleMask64=101111",
        "fftScaleMask512=101111111",
        "fftScaleExp64=5",
        "fftScaleExp512=8",
        "foldExp=2",
        "preExp=4",
        "mdctExpLong=12",
        "mdctExpShort=9",
        "dctPostSinStepLong=2",
        "dctPostSinStepShort=16",
        "rounding=none_arithmetic_shift",
        "overflow=wrap_modulo_2^32",
        "windowTableId0=SINE1024",
        "windowTableId1=KBD1024",
        "windowTableId2=SINE128",
        "windowTableId3=KBD128",
        "blockType0=LONG",
        "blockType1=START",
        "blockType2=SHORT",
        "blockType3=STOP",
        "windowShape0=SINE",
        "windowShape1=KBD",
        "fftStage0=RAM_after_bit_reversal",
        f"seed=0x{seed & 0xFFFFFFFF:08X}",
        f"floatMetrics={int(include_float_metrics)}",
    )
    with path.open("w", encoding="ascii", newline="\n") as stream:
        for line in lines:
            stream.write(line + "\n")
        for key in sorted(counts):
            stream.write(f"{key}={counts[key]}\n")


def _write_checksums(path: Path, files: Sequence[Path]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as stream:
        for file_path in sorted(files, key=lambda item: item.name):
            stream.write(f"{_sha256(file_path)}  {file_path.name}\n")


def _validate_text_file(path: Path, field_count: int, hex_fields: dict[int, int]) -> int:
    rows = 0
    with path.open("r", encoding="ascii") as stream:
        for line_number, raw in enumerate(stream, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                raise ModelError(f"{path}:{line_number}: blank/comment lines are forbidden")
            fields = line.split()
            if len(fields) != field_count:
                raise ModelError(
                    f"{path}:{line_number}: expected {field_count} fields, got {len(fields)}"
                )
            for index, width in hex_fields.items():
                token = fields[index]
                if len(token) != width or any(char not in "0123456789ABCDEF" for char in token):
                    raise ModelError(
                        f"{path}:{line_number}: field {index} must be {width}-digit uppercase hex"
                    )
            rows += 1
    return rows


def validate_output(directory: Path) -> dict[str, int]:
    """Re-open all text vectors and validate their VHDL-friendly schema."""

    schemas = {
        "rom_window_q15.txt": (4, {2: 4, 3: 4}),
        "rom_fft_q15.txt": (3, {1: 4, 2: 4}),
        "rom_dct_q15.txt": (3, {1: 4, 2: 4}),
        "pcm_in_s16.txt": (4, {3: 4}),
        "fold_q31.txt": (6, {4: 8}),
        "pre_q31.txt": (7, {4: 8, 5: 8}),
        "fft_stage_q31.txt": (9, {5: 8, 6: 8}),
        "post_q31.txt": (6, {4: 8}),
        "mdct_out_q31.txt": (5, {3: 8}),
    }
    return {
        name: _validate_text_file(directory / name, field_count, hex_fields)
        for name, (field_count, hex_fields) in schemas.items()
    }


def generate_vectors(
    output_dir: Path,
    rom_source: Path | None = None,
    seed: int = 0x4D444354,
    force: bool = False,
    include_float_metrics: bool = True,
    suite_name: str = "baseline",
) -> dict[str, int]:
    try:
        suite = VECTOR_SUITES[suite_name]
    except KeyError as exc:
        raise ModelError(f"unknown vector suite: {suite_name}") from exc
    if len(suite.block_sequence) != len(suite.shape_sequence):
        raise ModelError(f"suite {suite_name} has inconsistent block/shape sequences")
    paths = _prepare_output(output_dir, force)
    rom = FdkRom(rom_source)
    counts = {
        "case_rows": 0,
        "manifest_rows": 0,
        "pcm_rows": 0,
        "fold_rows": 0,
        "pre_rows": 0,
        "fft_stage_rows": 0,
        "post_rows": 0,
        "mdct_rows": 0,
        "metrics_rows": 0,
    }

    with ExitStack() as stack:
        cases_stream = stack.enter_context(paths["cases.csv"].open("w", encoding="utf-8", newline=""))
        manifest_stream = stack.enter_context(
            paths["manifest.csv"].open("w", encoding="utf-8", newline="")
        )
        metrics_stream = stack.enter_context(
            paths["numpy_metrics.csv"].open("w", encoding="utf-8", newline="")
        )
        cases_writer = csv.writer(cases_stream, lineterminator="\n")
        manifest_writer = csv.writer(manifest_stream, lineterminator="\n")
        metrics_writer = csv.writer(metrics_stream, lineterminator="\n")

        cases_writer.writerow(("case_id", "name", "description", "frames", "seed"))
        manifest_writer.writerow(
            (
                "schema",
                "case_id",
                "sequence_id",
                "frame_id",
                "reset_before",
                "sub_id",
                "block_type",
                "right_shape",
                "left_shape",
                "n_spec",
                "tl",
                "fl",
                "fr",
                "nl",
                "nr",
                "pcm_base",
                "pcm_count",
                "out_base",
                "fft_n",
                "fft_sign",
                "fft_scale_mask",
                "exp_fold",
                "exp_pre",
                "fft_scale_exp",
                "exp_fft_out",
                "exp_post",
            )
        )
        metrics_writer.writerow(
            (
                "case_id",
                "frame_id",
                "sub_id",
                "tl",
                "fft_n",
                "fft_rel_rms",
                "fft_rms_error",
                "fft_max_abs_error",
                "fft_snr_db",
                "mdct_rel_rms",
                "mdct_rms_error",
                "mdct_max_abs_error",
                "mdct_snr_db",
            )
        )

        text_streams = {
            name: stack.enter_context(paths[name].open("w", encoding="ascii", newline="\n"))
            for name in (
                "rom_window_q15.txt",
                "rom_fft_q15.txt",
                "rom_dct_q15.txt",
                "pcm_in_s16.txt",
                "fold_q31.txt",
                "pre_q31.txt",
                "fft_stage_q31.txt",
                "post_q31.txt",
                "mdct_out_q31.txt",
            )
        }
        counts.update(
            _dump_roms(
                rom,
                text_streams["rom_window_q15.txt"],
                text_streams["rom_fft_q15.txt"],
                text_streams["rom_dct_q15.txt"],
            )
        )

        for case in suite.cases:
            cases_writer.writerow((
                case.case_id,
                case.name,
                case.description,
                len(suite.block_sequence),
                f"0x{seed:08X}",
            ))
            counts["case_rows"] += 1
            model = MdctRadix2Model(rom)
            case_seed = (seed ^ (case.case_id * 0x9E3779B9)) & 0xFFFFFFFF
            for frame_id, (block, shape) in enumerate(
                zip(suite.block_sequence, suite.shape_sequence)
            ):
                frame_seed = case_seed if case.continuous_seed else case_seed ^ frame_id
                pcm = case.generator(frame_id, frame_seed)
                if len(pcm) != PCM_SNAPSHOT_LENGTH:
                    raise ModelError(
                        f"case {case.name} frame {frame_id} generated {len(pcm)} samples"
                    )
                if any(value < -32768 or value > 32767 for value in pcm):
                    raise ModelError(f"case {case.name} frame {frame_id} exceeds signed Q15")
                trace = model.process_frame(pcm, block, shape, frame_id)
                _write_frame_vectors(
                    case.case_id,
                    trace,
                    reset_before=(frame_id == 0),
                    manifest_writer=manifest_writer,
                    pcm_file=text_streams["pcm_in_s16.txt"],
                    fold_file=text_streams["fold_q31.txt"],
                    pre_file=text_streams["pre_q31.txt"],
                    fft_stage_file=text_streams["fft_stage_q31.txt"],
                    post_file=text_streams["post_q31.txt"],
                    mdct_file=text_streams["mdct_out_q31.txt"],
                    metrics_writer=metrics_writer,
                    include_float_metrics=include_float_metrics,
                    counts=counts,
                )

    _write_contract(paths["contract.meta"], rom, seed, include_float_metrics, counts)
    checksum_inputs = [
        path
        for name, path in paths.items()
        if name != "checksums.sha256" and path.exists()
    ]
    _write_checksums(paths["checksums.sha256"], checksum_inputs)
    validated = validate_output(output_dir)
    for name, rows in validated.items():
        if rows <= 0:
            raise ModelError(f"generated vector file is empty: {name}")
    return counts


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--suite",
        choices=tuple(VECTOR_SUITES),
        default="baseline",
        help="baseline reproduces immutable v1; extended adds 100 board-stress frames",
    )
    parser.add_argument("--rom-source", type=Path)
    parser.add_argument("--seed", type=lambda token: int(token, 0), default=0x4D444354)
    parser.add_argument("--force", action="store_true", help="replace only the known output files")
    parser.add_argument("--skip-float", action="store_true", help="write no per-subblock NumPy metrics")
    parser.add_argument(
        "--self-test-only",
        action="store_true",
        help="run model self-tests without generating files",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_self_test(args.rom_source)
        print(
            "SELF-TEST PASS: "
            f"FFT cases={summary['fft_cases']}, frames={summary['frames']}, "
            f"max FFT rel RMS={summary['max_fft_rel_rms']:.6e}, "
            f"max MDCT rel RMS={summary['max_mdct_rel_rms']:.6e}"
        )
        if args.self_test_only:
            return 0
        default_output = DEFAULT_OUTPUT if args.suite == "baseline" else EXTENDED_OUTPUT
        output_dir = (args.out or default_output).resolve()
        counts = generate_vectors(
            output_dir=output_dir,
            rom_source=args.rom_source,
            seed=args.seed,
            force=args.force,
            include_float_metrics=not args.skip_float,
            suite_name=args.suite,
        )
    except (ModelError, OSError, csv.Error, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"PASS: generated {SCHEMA} suite={args.suite} vectors in {output_dir}")
    for key in sorted(counts):
        print(f"  {key}={counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
