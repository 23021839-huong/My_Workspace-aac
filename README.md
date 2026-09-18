# Báo cáo tổng hợp AAC-LC HW/SW Codesign

Thư mục này là bản báo cáo rút gọn của `my_workspace`. Nội dung chỉ giữ tài liệu
tổng hợp; mã nguồn, vector kiểm thử, ảnh, file build và artifact phần cứng không
được sao chép vào đây. Mỗi hạng mục có đúng một `README.md` để thuận tiện đưa lên
Git và gửi đường dẫn báo cáo.

## 1. Mục tiêu dự án

Dự án nghiên cứu bộ mã hóa AAC-LC dựa trên FDK-AAC và phân chia xử lý giữa hai
phần của PYNQ-Z2:

- **PS (Cortex-A9):** đọc input, Block Switching, Psychoacoustic Model,
  Quantization/Coding và tạo bitstream AAC;
- **PL (FPGA):** tăng tốc Window/MDCT bằng số học fixed-point tương thích FDK.

```mermaid
flowchart LR
    A[WAV PCM16] --> B[INPUT]
    B --> C[Block Switching]
    B --> D[Window / MDCT]
    C --> D
    D --> E[Psychoacoustic Model]
    E --> F[Quantization & Coding]
    F --> G[AAC bitstream]

    subgraph PS[Cortex-A9 / Processing System]
      B
      C
      E
      F
      G
    end

    subgraph PL[Programmable Logic]
      D
    end
```

## 2. Các hạng mục

| Hạng mục | Vai trò | Mã nguồn đã khảo sát | Nền tảng | Trạng thái chính |
|---|---|---:|---|---|
| [INPUT](INPUT/) | Đọc WAV, chia frame, dựng buffer 2048 mẫu | 2 file | PS/host | Có reference/stimulus generator |
| [Block Switching](block_switch/) | Phát hiện transient, chọn LONG/START/SHORT/STOP | 5 file | PS | PASS bit-exact 292 frame/25 kịch bản |
| [Window/MDCT](window_mdct/) | Window, TDAC fold, DCT-IV qua FFT radix-2 | 56 file | PL + driver PS | RTL/golden khớp 0 LSB |
| [Psychoacoustic Model](psychoacoustic_model/) | SFB, masking, TNS/PNS và tạo `PSY_OUT` | 0 file riêng; khảo sát source FDK | PS | Đã chốt ranh giới tích hợp MDCT |
| [Quantization/Coding](quantization_coding/) | Scalefactor, quantize, bit count, Huffman | 16 file | PS; QMAX là ứng viên PL | Reference ready, RTL chưa bắt đầu |
| [PYNQ-Z2](pynq_z2/) | Build native, chạy encoder và profiling trên board | 2 script | PS/board | Có quy trình baseline và profiling |

Tổng cộng có **81 file code/cấu hình** trong `my_workspace` được kiểm kê và mô tả
trong sáu README chuyên mục.

## 3. Luồng dữ liệu và giao diện chính

1. `INPUT` nhận WAV mono PCM16, đưa 1024 mẫu mới cho Block Switching và duy trì
   snapshot 2048 mẫu cho Window/MDCT.
2. Block Switching trả `blockType`, `windowShape`, `noOfGroups` và `groupLen[]`.
3. MDCT nhận 2048 mẫu Q15 cùng tín hiệu điều khiển cửa sổ, trả 1024 hệ số Q31 và
   một exponent chung.
4. Psychoacoustic Model tính năng lượng/masking theo SFB, áp dụng các công cụ âm
   học và tạo `PSY_OUT`.
5. Quantization/Coding điều chỉnh threshold, tìm scalefactor/global gain, lượng
   tử hóa phổ, chọn codebook/section và ghi bitstream AAC.

## 4. Kết quả nổi bật

- Block Switching khớp bit-exact trên 292 frame thuộc 25 kịch bản.
- FFT-64, FFT-512 và toàn bộ MDCT RTL khớp golden tại mọi điểm kiểm tra với sai
  số `0 LSB`.
- Mô hình C++ và Python của MDCT khớp nhau; đối chiếu float64 đạt SNR tổng hợp
  khoảng `94.52 dB` trên bộ 18 frame.
- Spectral quantizer reference khớp trực tiếp kernel FDK ở các bộ vector long,
  zero và grouped-short/dead-zone với `0 mismatch`.
- FDK-AAC đã có flow build/chạy trên Cortex-A9 và script profiling theo khối.
- AXI4-Lite phù hợp bring-up/regression; đường dữ liệu thời gian thực vẫn cần
  C++ HAL và AXI DMA/AXI-Stream.

## 5. Cấu trúc bản báo cáo

```text
my_workspace_aac/
├── README.md
├── INPUT/README.md
├── block_switch/README.md
├── window_mdct/README.md
├── psychoacoustic_model/README.md
├── quantization_coding/README.md
└── pynq_z2/README.md
```

## 6. Phạm vi và nguồn tổng hợp

Báo cáo được tổng hợp từ snapshot cục bộ `my_workspace` ngày 18/09/2026. Các
đường dẫn source trong từng README là đường dẫn tương đối của workspace gốc;
chúng được giữ lại để truy vết kỹ thuật, không phải file nằm trong repo báo cáo.

