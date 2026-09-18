# Quantization & Coding — từ PSY_OUT tới bitstream AAC

## 1. Vai trò

Khối bắt đầu sau Psychoacoustic Model và thực hiện:

```text
PSY_OUT
  → Perceptual Entropy và phân bổ bit
  → điều chỉnh masking threshold
  → ước lượng global gain/scalefactor
  → lượng tử hóa spectrum
  → chọn Huffman codebook/section
  → đếm bit và lặp điều chỉnh gain
  → ghi AAC bitstream
```

## 2. Kiểm kê 16 file code

### 2.1 Reference C++

| File | Chức năng |
|---|---|
| `quantization_reference/cpp_ref/quantization_ref.h` | API, cấu trúc vector và hợp đồng quantizer C++. |
| `.../quantization_ref.cpp` | Hiện thực fixed-point portable của spectral quantization và thống kê theo SFB. |
| `.../main.cpp` | CLI đọc vector input, chạy reference và ghi output/trace. |

### 2.2 Reference Python

| File | Chức năng |
|---|---|
| `quantization_reference/python_ref/__init__.py` | Khai báo package reference. |
| `.../fdk_tables.py` | LUT/hằng số được trích từ FDK-AAC. |
| `.../quantization_fixed.py` | Mô hình fixed-point bám quy tắc normalize, LUT, shift và wrap FDK. |
| `.../quantization_float.py` | Mô hình float giải thích công thức và dùng làm đối chiếu mức thuật toán. |
| `.../utils.py` | Tiện ích int32/int16, leading-bit, wrap và chuyển đổi số. |

### 2.3 Sinh vector, adapter FDK và regression

| File | Chức năng |
|---|---|
| `quantization_reference/tools/extract_fdk_tables.py` | Trích bảng số từ source FDK sang reference. |
| `.../fdk_quant_harness.cpp` | Adapter mỏng gọi trực tiếp kernel `FDKaacEnc_QuantizeSpectrum()` không sửa đổi. |
| `.../generate_test_vectors.py` | Sinh các case long, zero và grouped-short/dead-zone. |
| `quantization_reference/verification/compare_models.py` | So vector/output/trace giữa FDK, C++ và Python. |
| `.../run_regression.py` | Điều phối sinh vector và chạy toàn bộ regression. |
| `.../verification/__init__.py` | Khai báo package verification. |
| `quantization_reference/tests/test_quantization.py` | Unit test LUT, dấu, zero, inverse và sai số float/fixed. |
| `docs/audit_2026-09-06/checks.py` | Tái tạo case audit và kiểm consistency của artifact. |

## 3. Source FDK-AAC liên quan

| Source | Vai trò |
|---|---|
| `aacenc.cpp` | Thứ tự xử lý frame. |
| `qc_main.cpp` | Rate control và quantization loop. |
| `adj_thr.cpp` | PE, bit allocation, threshold adjustment. |
| `sf_estim.cpp` | Ước lượng và cải thiện scalefactor. |
| `quantize.cpp` | Quantize, inverse quantize, distortion. |
| `dyn_bits.cpp` | Sectioning và dynamic bit count. |
| `bit_cnt.cpp` | Bit cost/codeword Huffman. |
| `bitenc.cpp` | Ghi syntax/bitstream. |

## 4. Phân chia PS/PL đề xuất

Ứng viên PL tốt nhất là **QMAX**:

- lượng tử hóa độc lập/đều theo tối đa 1024 spectral line;
- tìm max magnitude theo từng SFB bằng reduction;
- fixed-point và ROM lookup phù hợp datapath pipeline.

Các phần nên giữ trên PS:

- PE, threshold adjustment và bit reservoir;
- scalefactor search cấp cao;
- vòng điều khiển `QCMain()` có số lần lặp thay đổi;
- greedy section merging và chọn codebook cuối;
- phát Huffman variable-length, syntax AAC và ADTS.

Quantizer PL phải nhận spectrum **sau** Psy/TNS/stereo processing cùng
`globalGain`, `scf[]`, `sfbOffsets[]` và cờ dead-zone. Không nối trực tiếp output
MDCT PL sang QMAX trong kiến trúc hiện tại.

## 5. Trạng thái kiểm chứng

- đã reverse-engineer hợp đồng fixed-point;
- đã có Python float/fixed và C++ standalone;
- vector long, zero và grouped-short/dead-zone khớp trực tiếp kernel FDK với
  `0 mismatch`;
- đã có profiler tách `quantize_and_max_sfb` và script chạy trên Z2;
- chưa có số đo Cortex-A9 chính thức, RTL QMAX, AXI wrapper, bitstream/HWH hoặc
  kết quả hardware-in-the-loop.

Trạng thái ngắn gọn: **golden/reference ready — RTL not started**.

## 6. Gate trước khi viết RTL

Cần profiling trên Cortex-A9 cho:

- `FDKaacEnc_EstimateScaleFactors()`;
- `FDKaacEnc_QuantizeSpectrum()`;
- `FDKaacEnc_calcMaxValueInSfb()`;
- `FDKaacEnc_dynBitCount()`;
- số vòng lặp quantization trung bình/tối đa;
- tỷ lệ thời gian QC trong toàn encoder và chi phí DMA/cache.

Chỉ triển khai QMAX PL nếu lợi ích dự kiến lớn hơn chi phí truyền spectrum qua
PS–PL và không làm giảm throughput hệ thống.

## 7. Phạm vi RTL đầu tiên nếu đạt gate

AAC-LC mono, frame 1024, input Q31, output signed 16-bit, layout SFB runtime,
hỗ trợ LONG/START/SHORT/STOP, dead-zone runtime và trả cả quantized spectrum lẫn
max magnitude/SFB. Mọi LUT, normalize, shift, offset, wrap và cast phải giữ đúng
hành vi FDK để đạt bit-exact.

