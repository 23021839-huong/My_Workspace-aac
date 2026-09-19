#include "quantization_ref.h"

#include <algorithm>
#include <bit>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>

#include "fdk_quant_tables.inc"

namespace aac_quant_ref {
namespace {

constexpr int kMantDigits = 9;
constexpr int kMantSize = 1 << kMantDigits;
constexpr std::int32_t kAacLcOffset = 13284;
constexpr std::int32_t kDeadZoneOffset = 7536;

std::int64_t ArithmeticShiftRight(std::int64_t value, unsigned shift) {
  if (shift == 0) return value;
  if (value >= 0) return value >> shift;
  const std::uint64_t magnitude = static_cast<std::uint64_t>(-(value + 1)) + 1;
  return -static_cast<std::int64_t>((magnitude + ((std::uint64_t{1} << shift) - 1)) >> shift);
}

std::int32_t Wrap32(std::int64_t value) {
  return static_cast<std::int32_t>(static_cast<std::uint32_t>(value));
}

std::int32_t FMultDiv2Q31Q15(std::int32_t a, std::int16_t b) {
  return Wrap32(ArithmeticShiftRight(static_cast<std::int64_t>(a) * b, 16));
}

std::int32_t FMultDiv2Q15Q15(std::int16_t a, std::int16_t b) {
  return static_cast<std::int32_t>(a) * b;
}

std::int32_t FMultQ31(std::int32_t a, std::int32_t b) {
  return Wrap32(ArithmeticShiftRight(static_cast<std::int64_t>(a) * b, 32) * 2);
}

int ClzPositive(std::int32_t value) {
  if (value <= 0) throw std::invalid_argument("CLZ requires a positive value");
  return std::countl_zero(static_cast<std::uint32_t>(value));
}

std::int32_t ShiftLeftWrap(std::int32_t value, int shift) {
  return static_cast<std::int32_t>(static_cast<std::uint32_t>(value) << shift);
}

void ValidateGeometry(std::size_t spectrum_size, const std::vector<int>& offsets,
                      int sfb_cnt, int max_sfb_per_group, int sfb_per_group,
                      const std::vector<int>& scalefactors) {
  if (sfb_cnt < 0 || sfb_cnt > 60) throw std::invalid_argument("sfb_cnt must be in [0,60]");
  if (sfb_per_group <= 0 || sfb_cnt % sfb_per_group != 0)
    throw std::invalid_argument("sfb_per_group must divide sfb_cnt");
  if (max_sfb_per_group < 0 || max_sfb_per_group > sfb_per_group)
    throw std::invalid_argument("invalid max_sfb_per_group");
  if (offsets.size() < static_cast<std::size_t>(sfb_cnt + 1) ||
      scalefactors.size() < static_cast<std::size_t>(sfb_cnt))
    throw std::invalid_argument("offset/scalefactor arrays are too short");
  if (spectrum_size > 1024 || offsets.front() < 0 ||
      offsets[sfb_cnt] > static_cast<int>(spectrum_size))
    throw std::invalid_argument("spectrum or offsets outside AAC-LC bounds");
  for (int i = 0; i < sfb_cnt; ++i)
    if (offsets[i] > offsets[i + 1]) throw std::invalid_argument("SFB offsets must be monotonic");
}

}  // namespace

std::int16_t QuantizeLine(std::int32_t raw, int gain, bool dead_zone,
                          LineTrace* trace, int line, int sfb) {
  const int quantizer_index = (-gain) & 3;
  const std::int16_t quantizer = kQuantTableQQ15[quantizer_index];
  const int quantizer_shift = ((-gain) >> 2) + 1;
  const std::int32_t rounding = dead_zone ? kDeadZoneOffset : kAacLcOffset;
  const std::int32_t initial = FMultDiv2Q31Q15(raw, quantizer);
  if (initial == 0) {
    if (trace) *trace = {line, sfb, raw, gain, 0, quantizer_index, quantizer,
                         initial, 0, 0, 0, 0, 0, 0, 0, rounding, 0};
    return 0;
  }
  const int sign = initial < 0 ? -1 : 1;
  const std::int32_t magnitude = initial < 0 ? -initial : initial;
  const int accu_shift = ClzPositive(magnitude) - 1;
  const std::int32_t normalized = ShiftLeftWrap(magnitude, accu_shift);
  const int table_index =
      (normalized >> (32 - 2 - kMantDigits)) & (~kMantSize);
  const int total_before = quantizer_shift - accu_shift + 1;
  const int gain_index = total_before & 3;
  const std::int32_t after_pow =
      FMultDiv2Q15Q15(kMTab34Q15[table_index], kQuantTableEQ15[gain_index]);
  const int total_after = 12 - 3 * (total_before >> 2);
  if (total_after < 0)
    throw std::overflow_error("FDK MAX_QUANT precondition violated");
  const std::int32_t shifted = after_pow >> std::min(total_after, 31);
  const std::int32_t magnitude_q = (rounding + shifted) >> 15;
  const std::int16_t output = static_cast<std::int16_t>(sign < 0 ? -magnitude_q : magnitude_q);
  if (trace) *trace = {line, sfb, raw, gain, sign, quantizer_index, quantizer,
                       initial, accu_shift, normalized, table_index,
                       total_before, gain_index, after_pow, total_after,
                       rounding, output};
  return output;
}

std::int32_t InverseQuantizeLine(std::int16_t quantized, int gain) {
  if (quantized == 0) return 0;
  if (std::abs(static_cast<int>(quantized)) > kMaxQuant)
    throw std::invalid_argument("inverse input exceeds MAX_QUANT");
  const int sign = quantized < 0 ? -1 : 1;
  const std::int32_t magnitude = std::abs(static_cast<int>(quantized));
  const int exponent_shift = ClzPositive(magnitude) - 1;
  const std::int32_t normalized = ShiftLeftWrap(magnitude, exponent_shift);
  const int spec_exp = 31 - exponent_shift;
  const int table_index =
      (normalized >> (32 - 2 - kMantDigits)) & (~kMantSize);
  std::int32_t result = FMultQ31(kMTab43Q31[table_index],
                                 kSpecExpMantQ31[(gain & 3) * 14 + spec_exp]);
  const int table_shift = kSpecExpShift[(gain & 3) * 14 + spec_exp] - 1;
  const int delta = -(gain >> 2) - table_shift;
  result = delta < 0 ? ShiftLeftWrap(result, -delta) : (result >> delta);
  return sign < 0 ? -result : result;
}

SpectrumResult QuantizeSpectrum(const std::vector<std::int32_t>& spectrum,
                                const std::vector<int>& offsets, int sfb_cnt,
                                int max_sfb_per_group, int sfb_per_group,
                                int global_gain,
                                const std::vector<int>& scalefactors,
                                bool dead_zone, bool strict_range,
                                std::int16_t prefill, bool collect_trace) {
  ValidateGeometry(spectrum.size(), offsets, sfb_cnt, max_sfb_per_group,
                   sfb_per_group, scalefactors);
  SpectrumResult result;
  result.quantized_spectrum.assign(spectrum.size(), prefill);
  result.max_value_in_sfb.assign(sfb_cnt, 0);
  result.active_line_mask.assign(spectrum.size(), 0);
  for (int group = 0; group < sfb_cnt; group += sfb_per_group) {
    for (int local = 0; local < max_sfb_per_group; ++local) {
      const int sfb = group + local;
      const int gain = global_gain - scalefactors[sfb];
      int maximum = 0;
      for (int line = offsets[sfb]; line < offsets[sfb + 1]; ++line) {
        LineTrace trace{};
        const auto value = QuantizeLine(spectrum[line], gain, dead_zone,
                                        collect_trace ? &trace : nullptr, line, sfb);
        result.quantized_spectrum[line] = value;
        result.active_line_mask[line] = 1;
        maximum = std::max(maximum, std::abs(static_cast<int>(value)));
        if (collect_trace) result.traces.push_back(trace);
      }
      result.max_value_in_sfb[sfb] = maximum;
      result.maximum_quantized_value = std::max(result.maximum_quantized_value, maximum);
    }
  }
  if (strict_range && result.maximum_quantized_value > kMaxQuant)
    throw std::overflow_error("maximum quantized magnitude exceeds MAX_QUANT");
  return result;
}

void WriteResult(const std::string& output_dir, const SpectrumResult& result) {
  namespace fs = std::filesystem;
  fs::create_directories(output_dir);
  auto write_values = [&](const char* name, const auto& values) {
    std::ofstream out(fs::path(output_dir) / name);
    if (!out) throw std::runtime_error("cannot open output file");
    for (const auto value : values) out << static_cast<int>(value) << '\n';
  };
  write_values("quantized_spectrum_ref.txt", result.quantized_spectrum);
  write_values("max_value_in_sfb_ref.txt", result.max_value_in_sfb);
  write_values("active_line_mask.txt", result.active_line_mask);
  std::ofstream traces(fs::path(output_dir) / "intermediate_results.jsonl");
  for (const auto& t : result.traces) {
    traces << "{\"accu_after_gain\":" << t.accu_after_gain
           << ",\"accu_after_pow\":" << t.accu_after_pow
           << ",\"clz_shift\":" << t.clz_shift
           << ",\"gain\":" << t.gain
           << ",\"gain_table_index\":" << t.gain_table_index
           << ",\"input_raw\":" << t.input_raw
           << ",\"line\":" << t.line
           << ",\"lut_index_3_4\":" << t.lut_index_3_4
           << ",\"normalized_accu\":" << t.normalized_accu
           << ",\"output_raw\":" << t.output_raw
           << ",\"quantizer_index\":" << t.quantizer_index
           << ",\"quantizer_raw\":" << t.quantizer_raw
           << ",\"rounding_offset_raw\":" << t.rounding_offset_raw
           << ",\"sfb\":" << t.sfb << ",\"sign\":" << t.sign
           << ",\"total_shift_after\":" << t.total_shift_after
           << ",\"total_shift_before\":" << t.total_shift_before << "}\n";
  }
  std::ofstream summary(fs::path(output_dir) / "summary.json");
  summary << "{\n  \"maximum_quantized_value\": "
          << result.maximum_quantized_value << ",\n  \"mismatch_precondition\": "
          << (result.maximum_quantized_value > kMaxQuant ? "true" : "false")
          << "\n}\n";
}

}  // namespace aac_quant_ref
