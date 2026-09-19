#include "quantization_ref.h"

#include <filesystem>
#include <fstream>
#include <iostream>
#include <regex>
#include <sstream>
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
  const std::regex pattern("\\\"" + key + "\\\"\\s*:\\s*(-?[0-9]+)");
  std::smatch match;
  if (!std::regex_search(json, match, pattern)) throw std::runtime_error("missing JSON key " + key);
  return std::stoi(match[1].str());
}
}  // namespace

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: quantization_ref <case_dir> <output_dir>\n";
    return 2;
  }
  try {
    const fs::path case_dir = argv[1];
    const std::string manifest = ReadText(case_dir / "manifest.json");
    auto spectrum = ReadIntegers<std::int32_t>(case_dir / "input_mdct_q31.txt");
    auto offsets = ReadIntegers<int>(case_dir / "sfb_offsets.txt");
    auto scalefactors = ReadIntegers<int>(case_dir / "scalefactor.txt");
    auto gains = ReadIntegers<int>(case_dir / "global_gain.txt");
    if (gains.size() != 1) throw std::runtime_error("global_gain.txt must have one value");
    const auto result = aac_quant_ref::QuantizeSpectrum(
        spectrum, offsets, JsonInt(manifest, "sfb_cnt"),
        JsonInt(manifest, "max_sfb_per_group"),
        JsonInt(manifest, "sfb_per_group"), gains[0], scalefactors,
        JsonInt(manifest, "dzone_quant_enable") != 0);
    aac_quant_ref::WriteResult(argv[2], result);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "quantization_ref: " << error.what() << '\n';
    return 1;
  }
}
