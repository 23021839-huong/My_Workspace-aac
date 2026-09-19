cmake_minimum_required(VERSION 3.16)
project(aac_lc_quantization_reference LANGUAGES CXX)

add_library(quantization_ref quantization_ref.cpp)
target_include_directories(quantization_ref PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(quantization_ref PUBLIC cxx_std_20)

add_executable(quantization_ref_cli main.cpp)
target_link_libraries(quantization_ref_cli PRIVATE quantization_ref)

# Verification-only executable: compile the unmodified FDK spectral kernel and
# its ROM next to a thin case-file adapter.  It is not linked into the standalone
# reference library.
get_filename_component(FDK_REPOSITORY_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../.." ABSOLUTE)
add_executable(fdk_quant_harness
  ../tools/fdk_quant_harness.cpp
  ${FDK_REPOSITORY_ROOT}/libAACenc/src/quantize.cpp
  ${FDK_REPOSITORY_ROOT}/libAACenc/src/aacEnc_rom.cpp)
target_compile_features(fdk_quant_harness PRIVATE cxx_std_20)
target_include_directories(fdk_quant_harness PRIVATE
  ${FDK_REPOSITORY_ROOT}/libAACenc/src
  ${FDK_REPOSITORY_ROOT}/libAACenc/include
  ${FDK_REPOSITORY_ROOT}/libSYS/include
  ${FDK_REPOSITORY_ROOT}/libFDK/include
  ${FDK_REPOSITORY_ROOT}/libMpegTPEnc/include
  ${FDK_REPOSITORY_ROOT}/libMpegTPDec/include
  ${FDK_REPOSITORY_ROOT}/libPCMutils/include
  ${FDK_REPOSITORY_ROOT}/libArithCoding/include
  ${FDK_REPOSITORY_ROOT}/libDRCdec/include
  ${FDK_REPOSITORY_ROOT}/libSACdec/include
  ${FDK_REPOSITORY_ROOT}/libSACenc/include
  ${FDK_REPOSITORY_ROOT}/libSBRdec/include
  ${FDK_REPOSITORY_ROOT}/libSBRenc/include)

if(MINGW)
  target_link_options(quantization_ref_cli PRIVATE -static -static-libgcc -static-libstdc++)
  target_link_options(fdk_quant_harness PRIVATE -static -static-libgcc -static-libstdc++)
endif()

if(MSVC)
  target_compile_options(quantization_ref PRIVATE /W4)
else()
  target_compile_options(quantization_ref PRIVATE -Wall -Wextra -Wpedantic)
endif()
