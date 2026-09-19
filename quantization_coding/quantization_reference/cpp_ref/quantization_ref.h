#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace aac_quant_ref {

constexpr int kMaxQuant = 8191;

struct LineTrace {
  int line;
  int sfb;
  std::int32_t input_raw;
  int gain;
  int sign;
  int quantizer_index;
  std::int16_t quantizer_raw;
  std::int32_t accu_after_gain;
  int clz_shift;
  std::int32_t normalized_accu;
  int lut_index_3_4;
  int total_shift_before;
  int gain_table_index;
  std::int32_t accu_after_pow;
  int total_shift_after;
  std::int32_t rounding_offset_raw;
  std::int16_t output_raw;
};

struct SpectrumResult {
  std::vector<std::int16_t> quantized_spectrum;
  std::vector<int> max_value_in_sfb;
  int maximum_quantized_value{};
  std::vector<int> active_line_mask;
  std::vector<LineTrace> traces;
};

std::int16_t QuantizeLine(std::int32_t raw, int gain, bool dead_zone,
                          LineTrace* trace = nullptr, int line = -1,
                          int sfb = -1);
std::int32_t InverseQuantizeLine(std::int16_t quantized, int gain);
SpectrumResult QuantizeSpectrum(const std::vector<std::int32_t>& spectrum,
                                const std::vector<int>& offsets, int sfb_cnt,
                                int max_sfb_per_group, int sfb_per_group,
                                int global_gain,
                                const std::vector<int>& scalefactors,
                                bool dead_zone = false,
                                bool strict_range = true,
                                std::int16_t prefill = 0,
                                bool collect_trace = true);
void WriteResult(const std::string& output_dir, const SpectrumResult& result);

}  // namespace aac_quant_ref
