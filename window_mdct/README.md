# Window/MDCT — bộ tăng tốc chính trên Programmable Logic

## 1. Vai trò và datapath

Khối nhận snapshot 2048 mẫu PCM Q15 và tạo 1024 hệ số MDCT Q31 cùng exponent
chung. Datapath bám theo đường generic fixed-point của FDK-AAC:

```text
2048 PCM Q15
  → analysis window + TDAC fold
  → DCT-IV pre-rotation
  → FFT phức radix-2 (512 hoặc 64 điểm)
  → DCT-IV post-rotation/reorder
  → 1024 hệ số MDCT Q31 + exponent
```

LONG/START/STOP chạy một FFT-512; SHORT chạy tám FFT-64. Khối hỗ trợ cửa sổ SINE
và KBD, giữ trạng thái cửa sổ phải của frame trước để dựng sườn trái frame sau.

## 2. Hợp đồng số học

| Thành phần | Định dạng/quy tắc |
|---|---|
| PCM | signed Q1.15, 16 bit |
| Dữ liệu transform | signed Q1.31, 32 bit |
| Hệ số | signed Q1.15, 16 bit |
| Dịch phải | arithmetic shift, truncate |
| Overflow | wrap two's-complement 32 bit |
| Rounding/saturation | không dùng trong datapath transform |
| Exponent LONG/START/STOP | 12 |
| Exponent SHORT | 9 |

## 3. Kiểm kê 56 file code/cấu hình

### 3.1 RTL MDCT chính

| File | Chức năng |
|---|---|
| `rtl/mdct_pkg.vhd` | Kiểu dữ liệu, hằng số, profile số học và khai báo component chung. |
| `rtl/mdct_core.vhd` | Top-level tích hợp fold, DCT-IV, FFT, memory và control. |
| `rtl/mdct_control.vhd` | FSM nạp snapshot, chạy các phase, quản lý 8 short transform và state cửa sổ. |
| `rtl/mdct_window_fold.vhd` | Analysis window và TDAC fold tương thích `mdct_block()`. |
| `rtl/mdct_dct4_pre.vhd` | Pre-rotation từ vector Q31 sang input phức của FFT. |
| `rtl/mdct_dct4_post.vhd` | Post-rotation và reorder để tạo vector DCT-IV. |
| `rtl/mdct_pcm_memory.vhd` | RAM 2048 mẫu PCM, dùng chung cổng giữa loader và fold. |
| `rtl/mdct_work_memory.vhd` | RAM trung gian Q31 giữa fold và pre-rotation. |
| `rtl/mdct_fft_cache_memory.vhd` | Cache kết quả FFT phức theo natural order. |
| `rtl/mdct_spectrum_memory.vhd` | RAM output 1024 bin MDCT. |
| `rtl/mdct_window_rom.vhd` | ROM hệ số SINE/KBD được sinh từ bảng FDK. |
| `rtl/mdct_rotation_rom.vhd` | ROM hệ số pre/post rotation được sinh từ bảng FDK. |

### 3.2 FFT radix-2 dùng chung

| File | Chức năng |
|---|---|
| `fft_radix2_core/rtl/fft_radix2_pkg.vhd` | Hợp đồng Q31/Q15 và khai báo chung FFT. |
| `.../fft_radix2_core.vhd` | Top-level FFT64/FFT512, input/output natural order. |
| `.../fft_radix2_control.vhd` | Sequencer frame/stage và handshake. |
| `.../fft_radix2_addr_gen.vhd` | Sinh địa chỉ DIT tăng dần không dùng divide/modulo trên critical path. |
| `.../fft_radix2_butterfly.vhd` | Butterfly pipeline ba stage, một butterfly/clock. |
| `.../fft_radix2_memory.vhd` | Bộ nhớ phức hai bank, ping-pong giữa các stage. |
| `.../fft_radix2_twiddle_rom.vhd` | ROM twiddle Q15 sinh từ `SineTable512`. |

### 3.3 Reference model và đối chiếu FFT

| File | Chức năng |
|---|---|
| `ref/fixed_mdct_radix2.h` | API/profile cố định của oracle MDCT C++. |
| `ref/fixed_mdct_radix2.cpp` | Oracle C++ portable, bit-exact, không gọi trực tiếp transform FDK. |
| `ref/mdct_radix2_model.py` | Mô hình Python integer/NumPy để sinh và phân tích golden. |
| `fft_radix2_core/ref/fft_radix2_ref.cpp` | Reference C++ bit-exact độc lập cho FFT64/512. |
| `.../fft_radix2_model.py` | Mô hình FFT Python fixed-point. |
| `.../compare_fft_outputs.py` | So sánh output/trace của các implementation. |
| `.../compare_fft_numpy.py` | Đối chiếu kết quả fixed-point với NumPy float. |
| `.../fdk_sinetable512_q15.h` | Bảng Q15 sinh tự động cho C++. |
| `.../fdk_sinetable512_q15.py` | Bảng Q15 sinh tự động cho Python. |

### 3.4 Testbench và kiểm thử tự động

| File | Chức năng |
|---|---|
| `tb/tb_mdct_core.vhd` | Regression self-checking qua mọi điểm fold/pre/FFT/post/output, yêu cầu 0 LSB. |
| `tb/tb_mdct_axi_lite.vhd` | Regression qua wrapper AXI4-Lite, bao phủ thứ tự kênh và backpressure. |
| `tb/gen_mdct_golden.cpp` | Sinh vector biên xác định từ oracle C++. |
| `tb/verify_mdct_fdk.cpp` | Đối chiếu end-to-end với `mdct_block()`/DCT-IV nguyên bản của FDK. |
| `fft_radix2_core/tb/tb_fft_radix2_core.vhd` | Regression hỗn hợp FFT64/512, kiểm tra từng stage và latency. |
| `tests/test_bringup.py` | Unit test driver/MMIO bằng thiết bị giả. |
| `tools/run_bringup_sim.py` | Điều phối regression core và wrapper trước khi chạy board. |
| `tools/compare_rtl_numpy.py` | So sánh RTL/fixed-point với mô hình NumPy. |

### 3.5 Công cụ sinh dữ liệu và ROM

| File | Chức năng |
|---|---|
| `tools/gen_mdct_vectors.py` | Sinh bộ vector MDCT versioned. |
| `tools/gen_mdct_window_rom.py` | Trích/chuyển hệ số window FDK Q31 sang profile Q15. |
| `tools/gen_mdct_rotation_rom.py` | Sinh ROM rotation cho pre/post DCT-IV. |
| `tools/pack_pynq_z2.py` | Kiểm tra manifest/timing rồi đóng gói bit/hwh/golden. |
| `fft_radix2_core/tools/gen_fdk_twiddle.py` | Sinh twiddle ROM và bảng C++/Python từ FDK. |
| `.../gen_fft_vectors.py` | Sinh vector/trace FFT golden. |
| `.../verify_fdk_equivalence.py` | Kiểm tra tương đương số học với FDK. |
| `.../plot_fft_comparison.py` | Trực quan hóa chênh lệch FFT. |
| `docs/diagrams/export_png.ps1` | Xuất các sơ đồ kiến trúc thành PNG. |

### 3.6 Driver phần mềm và build Vivado

| File | Chức năng |
|---|---|
| `sw/mdct_pynq.py` | Driver Python/MMIO cho overlay MDCT. |
| `sw/mdct_golden.py` | Đọc, kiểm checksum và ánh xạ golden frame. |
| `sw/run_mdct_board.py` | Chạy corpus trên PYNQ-Z2, kiểm output và tổng hợp timing. |
| `sw/compare_board_float.py` | Đối chiếu kết quả board với NumPy float. |
| `board/pynq_z2/mdct_axi_lite.vhd` | Adapter AXI4-Lite để bring-up và regression software-controlled. |
| `board/pynq_z2/pynq_z2_mdct.xdc` | Ràng buộc board/clock/pin cho overlay. |
| `synth/mdct_core.xdc` | Ràng buộc timing của core MDCT. |
| `synth/vivado_mdct_runtime.tcl` | Synthesis/place/route core MDCT cho Zynq-7020. |
| `synth/vivado_pynq_z2_bitstream.tcl` | Tạo block design/bitstream/HWH PYNQ-Z2. |
| `fft_radix2_core/synth/fft_radix2_core.xdc` | Ràng buộc timing FFT. |
| `fft_radix2_core/synth/vivado_fft_runtime.tcl` | Synthesis/place/route riêng core FFT. |

## 4. Kết quả kiểm chứng

- C++ và Python integer khớp `0 LSB` trên 18 frame, 39 sub-transform.
- RTL khớp golden `0 LSB` ở fold, pre-rotation, từng stage FFT,
  post-rotation và toàn bộ 1024 output.
- Reference radix-2 khớp đường transform FDK gốc `0 LSB` trên chuỗi
  LONG/START/8-SHORT/STOP.
- So với NumPy float64 trên 18.432 hệ số: relative RMS khoảng
  `1.878981e-05`, SNR `94.521552 dB`, sai số tuyệt đối lớn nhất
  `1.526404e-02`.
- Corpus mở rộng 100 frame bao phủ tone, multitone, chirp, transient, clipping,
  noise và tín hiệu gần tiếng nói.

## 5. Tích hợp PYNQ-Z2

Wrapper AXI4-Lite dùng một aperture 32-bit, phù hợp kiểm thử và xử lý tốc độ thấp.
Luồng sản phẩm thời gian thực nên thay lớp truyền mẫu bằng AXI DMA/AXI-Stream
nhưng giữ nguyên `mdct_core`.

Giao diện logic tối thiểu gồm:

- load 2048 mẫu PCM và cấu hình block/window;
- phát xung `start`, theo dõi `busy/done/error`;
- đọc 1024 hệ số Q31 và exponent;
- kiểm soát timeout, cache coherency và thứ tự frame ở driver.

## 6. Việc còn lại

- hoàn thiện C++ HAL/backend gọi được từ FDK-AAC;
- thay AXI4-Lite bulk transfer bằng DMA/stream cho realtime;
- khóa clock mục tiêu, kiểm setup/hold và resource trên build cuối;
- chạy shadow mode software/PL trên cùng frame;
- nghiệm thu end-to-end bằng file AAC hợp lệ và audio decode.

