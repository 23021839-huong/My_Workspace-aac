# PYNQ-Z2 — build, chạy baseline và profiling encoder

## 1. Vai trò

Hạng mục này đưa working tree FDK-AAC lên PYNQ-Z2, xác nhận encoder software chạy
đúng trên Cortex-A9 và đo thời gian từng khối trước khi quyết định offload thêm
sang PL.

## 2. Mã nguồn đã tổng hợp

| File trong `my_workspace/pynq_z2` | Chức năng |
|---|---|
| `sw/scripts/run_phase_a_native.sh` | Kiểm tra môi trường ARMv7 và WAV; CMake Release; build `aac-enc`/self-test; chạy encode; lưu manifest, checksum và artifact baseline. |
| `sw/scripts/run_encoder_profile.sh` | Build với `FDK_ENABLE_ENCODER_PROFILING=ON`; ghim CPU bằng `taskset`; chạy AAC-LC mono; thu CSV theo khối và thống kê tài nguyên tiến trình. |

## 3. Baseline phần mềm

Input chuẩn được kiểm tra trước khi chạy:

```text
mono, 48 kHz, signed PCM16, uncompressed WAV
```

Flow baseline:

```mermaid
flowchart LR
    A[Working tree] --> B[Kiểm tra ARMv7 + dependency]
    B --> C[CMake Release]
    C --> D[Build encoder + self-test]
    D --> E[Chạy self-test]
    E --> F[Encode WAV → AAC]
    F --> G[Manifest + checksum + logs]
```

Artifact cần giữ gồm thông tin máy/kernel, cấu hình build, revision source nếu có,
metadata input, lệnh chạy, log, file AAC và SHA-256. Baseline chỉ PASS khi build,
self-test và encode đều thành công và output AAC không rỗng.

## 4. Profiling theo khối

Build profiling ghi thời gian từng vùng quan trọng của encoder ra CSV. Điều kiện
đo cần ổn định:

- dùng cùng input và bitrate;
- Release build, cùng compiler flags;
- ghim một CPU Cortex-A9;
- ghi CPU governor và kernel;
- warm-up nếu cần, chạy lặp và báo median/percentile;
- tách wall time toàn tiến trình khỏi thời gian instrument theo khối.

Các khối cần theo dõi gồm input/copy, Block Switching, Transform/MDCT,
Psychoacoustic Model, scalefactor estimation, quantize/max-SFB, dynamic bit count
và bitstream writer.

## 5. Liên hệ với accelerator MDCT

Flow board cho MDCT gồm hai mức:

1. AXI4-Lite + Python driver để bring-up, regression và đo tính đúng.
2. C++ HAL + DMA/AXI-Stream để tích hợp trực tiếp vào FDK-AAC và hướng tới
   realtime.

Nghiệm thu cần chạy ba backend trên cùng input:

- `SW`: transform FDK nguyên bản;
- `SHADOW`: chạy SW và PL, so output nhưng dùng SW để encode;
- `PL`: dùng output phần cứng thật trong encoder.

## 6. Chỉ số báo cáo đề xuất

| Nhóm | Chỉ số |
|---|---|
| Tính đúng | sai khác MDCT theo LSB, exponent, bitstream hợp lệ, decode thành công |
| Hiệu năng | chu kỳ/frame, ms/frame, realtime factor, throughput PS–PL |
| FPGA | LUT, FF, BRAM, DSP, setup/hold slack, clock đạt được |
| Hệ thống | CPU time từng khối, cache/DMA overhead, tổng speedup encoder |
| Tái lập | revision, build flags, input checksum, board image, Vivado version |

## 7. Bước tiếp theo

- thu bộ profiling lặp lại trên Cortex-A9;
- hoàn thiện backend C++ gọi overlay MDCT;
- chạy SHADOW mode và khóa tiêu chí `0 LSB`;
- chuyển bulk data sang DMA/stream;
- chạy PL backend end-to-end, decode file AAC và so sánh chất lượng/tốc độ;
- chỉ đánh giá QMAX PL sau khi profiling chứng minh có lợi.

