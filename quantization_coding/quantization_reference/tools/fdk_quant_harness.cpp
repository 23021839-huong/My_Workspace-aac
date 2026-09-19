// Thin verification adapter around the unmodified FDK public spectral kernel.
#include "quantize.h"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;

template <typename T>
std::vector<T> ReadIntegers(const fs::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open " + path.string());
  std::vector<T> values;
  long long value;
  while (input >> value) values.push_back(static_cast<T>(value));
  if (!input.eof()) throw std::runtime_error("invalid integer in " + path.string());
  return values;
}

std::string ReadText(const fs::path& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open " + path.string());
  return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

int JsonInt(const std::string& json, const std::string& key) {
  std::smatch match;
  const std::regex pattern("\\\"" + key + "\\\"\\s*:\\s*(-?[0-9]+)");
  if (!std::regex_search(json, match, pattern)) throw std::runtime_error("missing JSON key " + key);
  return std::stoi(match[1].str());
}

template <typename T>
void WriteIntegers(const fs::path& path, const std::vector<T>& values) {
  std::ofstream output(path);
  for (const auto value : values) output << static_cast<int>(value) << '\n';
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: fdk_quant_harness <case_dir> <output_dir>\n";
    return 2;
  }
  try {
    const fs::path input_dir = argv[1];
    const fs::path output_dir = argv[2];
    const auto manifest = ReadText(input_dir / "manifest.json");
    auto spectrum = ReadIntegers<FIXP_DBL>(input_dir / "input_mdct_q31.txt");
    auto offsets = ReadIntegers<INT>(input_dir / "sfb_offsets.txt");
    auto scalefactors = ReadIntegers<INT>(input_dir / "scalefactor.txt");
    auto gains = ReadIntegers<INT>(input_dir / "global_gain.txt");
    if (gains.size() != 1) throw std::runtime_error("global_gain.txt must have one value");
    const int sfb_cnt = JsonInt(manifest, "sfb_cnt");
    const int max_sfb = JsonInt(manifest, "max_sfb_per_group");
    const int per_group = JsonInt(manifest, "sfb_per_group");
    std::vector<SHORT> output(spectrum.size(), 0);
    FDKaacEnc_QuantizeSpectrum(sfb_cnt, max_sfb, per_group, offsets.data(),
                               spectrum.data(), gains[0], scalefactors.data(),
                               output.data(), JsonInt(manifest, "dzone_quant_enable"));
    std::vector<int> maxima(sfb_cnt, 0), active(spectrum.size(), 0);
    for (int group = 0; group < sfb_cnt; group += per_group) {
      for (int local = 0; local < max_sfb; ++local) {
        const int sfb = group + local;
        for (int line = offsets[sfb]; line < offsets[sfb + 1]; ++line) {
          active[line] = 1;
          maxima[sfb] = std::max(maxima[sfb], std::abs(static_cast<int>(output[line])));
        }
      }
    }
    fs::create_directories(output_dir);
    WriteIntegers(output_dir / "quantized_spectrum_ref.txt", output);
    WriteIntegers(output_dir / "max_value_in_sfb_ref.txt", maxima);
    WriteIntegers(output_dir / "active_line_mask.txt", active);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "fdk_quant_harness: " << error.what() << '\n';
    return 1;
  }
}
