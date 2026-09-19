"""Small PYNQ MMIO driver for the mdct_axi_lite bring-up adapter."""

from __future__ import annotations

import time
import math
import operator
from pathlib import Path
from typing import Iterable

import numpy as np

REG_CONTROL = 0x00
REG_STATUS = 0x04
REG_PCM_INDEX = 0x08
REG_PCM_DATA = 0x0C
REG_SPEC_INDEX = 0x10
REG_SPEC_DATA = 0x14
REG_MDCT_EXP = 0x18
REG_ID = 0x1C
REG_PCM_COUNT = 0x20

CONTROL_START = 1 << 0
CONTROL_CLEAR_HISTORY = 1 << 1
CONTROL_SPEC_READ = 1 << 2
CONTROL_CLEAR_FLAGS = 1 << 3

STATUS_PCM_READY = 1 << 0
STATUS_ACTIVE = 1 << 1
STATUS_DONE = 1 << 2
STATUS_SPEC_VALID = 1 << 3
STATUS_ERROR = 1 << 4

MDCT_ID = 0x4D444354
DEFAULT_BASE_ADDRESS = 0x43C00000
APERTURE_BYTES = 0x10000

BLOCK_TYPES = {"long": 0, "start": 1, "short": 2, "stop": 3}
WINDOW_SHAPES = {"sine": 0, "kbd": 1}


class MdctPynq:
    """Software interface to one window_mdct accelerator instance."""

    def __init__(
        self,
        bitfile: str | Path | None = None,
        *,
        base_address: int = DEFAULT_BASE_ADDRESS,
    ) -> None:
        from pynq import MMIO, Overlay

        if bitfile is not None:
            bitfile = Path(bitfile).resolve()
            for path in (bitfile, bitfile.with_suffix(".hwh")):
                if not path.is_file() or path.stat().st_size == 0:
                    raise FileNotFoundError(f"missing or empty overlay file: {path}")
        self.overlay = Overlay(str(bitfile)) if bitfile is not None else None
        self.mmio = MMIO(base_address, APERTURE_BYTES)
        self._needs_reload = False
        self.last_timings: dict[str, float] = {}
        if self.mmio.read(REG_ID) != MDCT_ID:
            raise RuntimeError(
                f"MDCT peripheral not found at 0x{base_address:08x}; "
                "check the loaded .bit/.hwh files"
            )

    def _wait_for(self, mask: int, deadline: float) -> int:
        while time.monotonic() < deadline:
            status = self.mmio.read(REG_STATUS)
            if status & STATUS_ERROR:
                raise RuntimeError(f"MDCT protocol error, status=0x{status:08x}")
            if status & mask:
                return status
        status = self.mmio.read(REG_STATUS)
        raise TimeoutError(f"MDCT timeout, status=0x{status:08x}")

    @staticmethod
    def _mode_value(value: str | int, table: dict[str, int], name: str) -> int:
        if isinstance(value, str):
            try:
                return table[value.lower()]
            except KeyError as exc:
                raise ValueError(f"unknown {name}: {value!r}") from exc
        result = operator.index(value)
        if result not in table.values():
            raise ValueError(f"invalid {name}: {result}")
        return result

    def transform(
        self,
        pcm: Iterable[int],
        *,
        block_type: str | int = "long",
        right_shape: str | int = "sine",
        clear_history: bool = False,
        timeout_s: float = 5.0,
    ) -> tuple[np.ndarray, int]:
        """Run one frame; timeout_s bounds the complete MMIO transaction.

        Use one instance exclusively for one stream. After a timeout, protocol
        error or interrupted transfer, reload the overlay before starting again.
        clear_history resets window history only, not a partially loaded frame.
        last_timings contains host wall times, including polling/MMIO overhead.
        """

        samples = np.asarray([operator.index(value) for value in pcm], dtype=np.int64)
        if samples.shape != (2048,):
            raise ValueError(f"expected exactly 2048 PCM samples, got {samples.size}")
        if np.any(samples < -32768) or np.any(samples > 32767):
            raise ValueError("PCM values must fit signed 16-bit Q15")

        block = self._mode_value(block_type, BLOCK_TYPES, "block type")
        shape = self._mode_value(right_shape, WINDOW_SHAPES, "window shape")
        config = (block << 8) | (shape << 10)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and positive")
        if self._needs_reload:
            raise RuntimeError("previous transfer failed; reload the overlay")
        status = self.mmio.read(REG_STATUS)
        if status & (STATUS_ACTIVE | STATUS_ERROR | (1 << 5) | (1 << 6)) or \
                self.mmio.read(REG_PCM_COUNT) != 0:
            raise RuntimeError(
                f"MDCT is not idle/empty, status=0x{status:08x}; reload the overlay"
            )
        self.last_timings = {}
        started = time.monotonic()
        deadline = started + timeout_s
        try:
            return self._transfer(samples, config, block, clear_history, started, deadline)
        except BaseException:
            # Neither clearing flags nor clear_history resets the PCM loader.
            self._needs_reload = True
            raise

    def _transfer(self, samples, config, block, clear_history, started, deadline):

        self.mmio.write(REG_CONTROL, config | CONTROL_CLEAR_FLAGS)
        for sample in samples:
            self._wait_for(STATUS_PCM_READY, deadline)
            self.mmio.write(REG_PCM_DATA, int(sample) & 0xFFFF)

        while self.mmio.read(REG_PCM_COUNT) != 2048:
            status = self.mmio.read(REG_STATUS)
            if status & STATUS_ERROR:
                raise RuntimeError(f"PCM load failed, status=0x{status:08x}")
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out while loading PCM snapshot")

        loaded = time.monotonic()
        command = config | CONTROL_START
        if clear_history:
            command |= CONTROL_CLEAR_HISTORY
        self.mmio.write(REG_CONTROL, command)
        self._wait_for(STATUS_DONE, deadline)
        computed = time.monotonic()

        self.mmio.write(REG_SPEC_INDEX, 0)
        output = np.empty(1024, dtype=np.int32)
        for index in range(1024):
            self.mmio.write(REG_CONTROL, config | CONTROL_SPEC_READ)
            self._wait_for(STATUS_SPEC_VALID, deadline)
            raw = self.mmio.read(REG_SPEC_DATA)
            output[index] = raw if raw < (1 << 31) else raw - (1 << 32)

        exponent = self.mmio.read(REG_MDCT_EXP) & 0x1F
        if exponent != (9 if block == 2 else 12):
            raise RuntimeError(f"invalid MDCT exponent {exponent} for block {block}")
        finished = time.monotonic()
        if finished > deadline:
            raise TimeoutError("MDCT frame exceeded timeout_s")
        self.last_timings = {
            "load_ms": (loaded - started) * 1000,
            "compute_poll_ms": (computed - loaded) * 1000,
            "read_ms": (finished - computed) * 1000,
            "total_ms": (finished - started) * 1000,
        }
        return output, exponent
