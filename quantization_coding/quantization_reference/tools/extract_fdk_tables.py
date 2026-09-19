"""Extract the exact FDK quantizer ROM constants used by the host build.

The generated files are checked in so the reference models remain runnable even
when the FDK tree is not on the target machine.  Re-run this script whenever the
FDK baseline commit changes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def array_body(source: str, symbol: str) -> str:
    marker = re.search(rf"\b{re.escape(symbol)}\s*(?:\[[^;=]*\])+\s*=\s*\{{", source)
    if not marker:
        raise ValueError(f"array not found: {symbol}")
    start = marker.end() - 1
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index]
    raise ValueError(f"unterminated array: {symbol}")


def q31_from_decimal(token: str) -> int:
    value = float(token)
    scaled = int(value * (1 << 31) + (0.5 if value >= 0 else -0.5))
    return max(-(1 << 31), min((1 << 31) - 1, scaled))


def q15_from_q31(raw: int) -> int:
    if raw > 0 and ((raw >> 15) + 1) > 0xFFFF:
        return 0x7FFF
    value = ((raw >> 15) + 1) >> 1
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


def parse_qtc_hex(body: str) -> list[int]:
    values = [int(token, 16) for token in re.findall(r"QTC\(0x([0-9a-fA-F]+)\)", body)]
    return [q15_from_q31(value if value < (1 << 31) else value - (1 << 32)) for value in values]


def parse_q31_decimal(body: str) -> list[int]:
    tokens = re.findall(r"FL2FXCONST_DBL\(([-+0-9.eEfF]+)\)", body)
    return [q31_from_decimal(token.rstrip("fF")) for token in tokens]


def parse_plain_ints(body: str) -> list[int]:
    return [int(token, 0) for token in re.findall(r"(?<![A-Za-z_])(?:0x[0-9a-fA-F]+|\d+)", body)]


def rows(values: list[int], width: int) -> list[list[int]]:
    if len(values) % width:
        raise ValueError(f"cannot split {len(values)} values into rows of {width}")
    return [values[index : index + width] for index in range(0, len(values), width)]


def py_list(values: list[int], indent: str = "") -> str:
    chunks = [values[index : index + 8] for index in range(0, len(values), 8)]
    return "[\n" + "".join(indent + "    " + ", ".join(map(str, chunk)) + ",\n" for chunk in chunks) + indent + "]"


def cpp_array(name: str, ctype: str, values: list[int]) -> str:
    body = "\n".join("    " + ", ".join(map(str, chunk)) + "," for chunk in rows(values + [0] * ((8 - len(values) % 8) % 8), 8))
    if len(values) % 8:
        padding = (8 - len(values) % 8) % 8
        final = ", ".join(map(str, values[-(8 - padding) :])) + ","
        body_lines = body.splitlines()
        body_lines[-1] = "    " + final
        body = "\n".join(body_lines)
    return f"static constexpr {ctype} {name}[{len(values)}] = {{\n{body}\n}};\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    repo_root = args.repo_root.resolve() if args.repo_root else Path(__file__).resolve().parents[4]
    rom_path = repo_root / "libAACenc" / "src" / "aacEnc_rom.cpp"
    source = rom_path.read_text(encoding="utf-8")

    m34 = parse_qtc_hex(array_body(source, "FDKaacEnc_mTab_3_4"))
    quant_q = parse_qtc_hex(array_body(source, "FDKaacEnc_quantTableQ"))
    quant_e = parse_qtc_hex(array_body(source, "FDKaacEnc_quantTableE"))
    m43 = parse_q31_decimal(array_body(source, "FDKaacEnc_mTab_4_3Elc"))
    exp_mant = parse_q31_decimal(array_body(source, "FDKaacEnc_specExpMantTableCombElc"))
    exp_shift = parse_plain_ints(array_body(source, "FDKaacEnc_specExpTableComb"))

    expected = {"m34": 512, "quant_q": 4, "quant_e": 4, "m43": 512, "exp_mant": 56, "exp_shift": 56}
    actual = {"m34": len(m34), "quant_q": len(quant_q), "quant_e": len(quant_e), "m43": len(m43), "exp_mant": len(exp_mant), "exp_shift": len(exp_shift)}
    if actual != expected:
        raise ValueError(f"unexpected table sizes: {actual}, expected {expected}")

    python_output = '''"""Generated from libAACenc/src/aacEnc_rom.cpp; do not edit."""\n\n'''
    python_output += f"M_TAB_3_4_Q15 = {py_list(m34)}\n\n"
    python_output += f"QUANT_TABLE_Q_Q15 = {quant_q!r}\n"
    python_output += f"QUANT_TABLE_E_Q15 = {quant_e!r}\n\n"
    python_output += f"M_TAB_4_3_Q31 = {py_list(m43)}\n\n"
    python_output += f"SPEC_EXP_MANT_Q31 = {rows(exp_mant, 14)!r}\n"
    python_output += f"SPEC_EXP_SHIFT = {rows(exp_shift, 14)!r}\n"
    (project_root / "python_ref" / "fdk_tables.py").write_text(python_output, encoding="utf-8")

    cpp_output = "// Generated from libAACenc/src/aacEnc_rom.cpp; do not edit.\n#pragma once\n#include <cstdint>\n\n"
    cpp_output += cpp_array("kMTab34Q15", "std::int16_t", m34) + "\n"
    cpp_output += cpp_array("kQuantTableQQ15", "std::int16_t", quant_q) + "\n"
    cpp_output += cpp_array("kQuantTableEQ15", "std::int16_t", quant_e) + "\n"
    cpp_output += cpp_array("kMTab43Q31", "std::int32_t", m43) + "\n"
    cpp_output += cpp_array("kSpecExpMantQ31", "std::int32_t", exp_mant) + "\n"
    cpp_output += cpp_array("kSpecExpShift", "std::uint8_t", exp_shift)
    (project_root / "cpp_ref" / "fdk_quant_tables.inc").write_text(cpp_output, encoding="utf-8")

    print(f"Extracted FDK ROM tables from {rom_path}")
    print(actual)


if __name__ == "__main__":
    main()
