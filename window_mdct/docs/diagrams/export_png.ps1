param([string]$OutputDirectory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

function Color([string]$hex) { return [System.Drawing.ColorTranslator]::FromHtml($hex) }
function Text([string]$value, [float]$x, [float]$y, [float]$w, [float]$h, [float]$size = 18, [string]$ink = '#18324B', [bool]$bold = $false) {
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $font = [System.Drawing.Font]::new('Arial', $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = [System.Drawing.SolidBrush]::new((Color $ink))
    $format = [System.Drawing.StringFormat]::new()
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $script:g.DrawString($value, $font, $brush, [System.Drawing.RectangleF]::new($x,$y,$w,$h), $format)
    $font.Dispose(); $brush.Dispose(); $format.Dispose()
}
function Box([float]$x,[float]$y,[float]$w,[float]$h,[string]$title,[string]$body = '',[string]$fill = '#EDF4FC') {
    $brush = [System.Drawing.SolidBrush]::new((Color $fill))
    $pen = [System.Drawing.Pen]::new((Color '#9CB1C4'),1.3)
    $script:g.FillRectangle($brush,$x,$y,$w,$h)
    $script:g.DrawRectangle($pen,$x,$y,$w,$h)
    if ($body) {
        Text $title ($x+10) ($y+5) ($w-20) 34 20 '#18324B' $true
        Text $body ($x+12) ($y+40) ($w-24) ($h-46) 18
    } else { Text $title ($x+10) ($y+5) ($w-20) ($h-10) 20 '#18324B' $true }
    $brush.Dispose(); $pen.Dispose()
}
function Frame([float]$x,[float]$y,[float]$w,[float]$h,[string]$title,[string]$fill = '#F7F9FC') {
    $brush = [System.Drawing.SolidBrush]::new((Color $fill))
    $pen = [System.Drawing.Pen]::new((Color '#C9D4DF'),1.5)
    $script:g.FillRectangle($brush,$x,$y,$w,$h)
    $script:g.DrawRectangle($pen,$x,$y,$w,$h)
    Text $title ($x+10) ($y+8) ($w-20) 34 22 '#18324B' $true
    $brush.Dispose(); $pen.Dispose()
}
function Arrow([float[]]$coords,[string]$ink = '#315A82',[bool]$dashed = $false) {
    $pen = [System.Drawing.Pen]::new((Color $ink),2.4)
    if ($dashed) { $pen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash }
    $cap = [System.Drawing.Drawing2D.AdjustableArrowCap]::new(5,6)
    $pen.CustomEndCap = $cap
    $points = [System.Drawing.PointF[]]::new($coords.Length/2)
    for ($i=0; $i -lt $points.Length; $i++) { $points[$i] = [System.Drawing.PointF]::new($coords[2*$i],$coords[2*$i+1]) }
    $script:g.DrawLines($pen,$points)
    $pen.Dispose(); $cap.Dispose()
}
function Label([string]$value,[float]$x,[float]$y,[float]$w,[float]$h = 28,[string]$ink = '#315A82') {
    $brush = [System.Drawing.SolidBrush]::new((Color '#FFFFFF'))
    $script:g.FillRectangle($brush,$x,$y,$w,$h)
    $brush.Dispose()
    Text $value $x $y $w $h 17 $ink
}
function Canvas([int]$height,[string]$title,[string]$subtitle) {
    $script:bitmap = [System.Drawing.Bitmap]::new(3600,($height*2))
    $script:bitmap.SetResolution(192,192)
    $script:g = [System.Drawing.Graphics]::FromImage($script:bitmap)
    $script:g.Clear([System.Drawing.Color]::White)
    $script:g.ScaleTransform(2,2)
    $script:g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $script:g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    Text $title 30 16 1740 52 32 '#12304C' $true
    Text $subtitle 40 72 1720 40 19 '#51667A'
}
function Save([string]$name,[int]$height) {
    Text 'Nguồn: window_mdct | Sơ đồ kiến trúc theo source; build Vivado và kết quả board cần được kiểm chứng thực tế.' 40 ($height-43) 1720 30 16 '#62778B'
    $path = Join-Path $OutputDirectory $name
    $script:bitmap.Save($path,[System.Drawing.Imaging.ImageFormat]::Png)
    $script:g.Dispose(); $script:bitmap.Dispose()
    Write-Output $path
}

# 1. Build and deployment: each column represents a distinct execution stage.
Canvas 1200 '01  |  TỪ VHDL ĐẾN KẾT QUẢ TRÊN PYNQ-Z2' 'Source và constraint → Vivado 2025 trên server → overlay và kiểm thử trên board'
Frame 30 140 510 970 'ĐẦU VÀO THIẾT KẾ'
Frame 590 140 610 970 'SERVER  |  VIVADO 2025'
Frame 1250 140 520 970 'BOARD  |  LINUX / PYNQ' '#F5FAF7'
Box 65 215 440 120 'RTL tính toán' "mdct_core.vhd + các module MDCT`nfft_radix2_core/rtl/*.vhd"
Box 65 375 440 100 'Adapter giao tiếp' 'mdct_axi_lite.vhd'
Box 65 515 440 120 'Board files + XDC' "XC7Z020CLG400-1; preset PS/DDR/MIO`nÁnh xạ LED và chuẩn điện áp"
Box 65 675 440 115 'Script Tcl' "Danh sách source, top, IP, clock`nTạo project và thực hiện build"
Box 65 850 440 140 'Testbench + golden' "tb_mdct_core.vhd`nPCM / các stage / kết quả chuẩn" '#FFF4DF'
Box 630 205 530 110 'Block Design / IP Integrator' "Zynq PS + AXI fabric + reset`nAdapter + MDCT; mục tiêu 100 MHz"
Box 630 355 530 90 'Sinh top hệ thống' 'mdct_pynq_z2_wrapper'
Box 630 495 530 95 'Synthesis' 'RTL → netlist LUT / FF / BRAM / DSP'
Box 630 640 530 95 'Implementation' 'Placement + routing trên FPGA đích'
Box 630 785 530 105 'Kiểm tra report' 'Resource, setup/hold, clock và DRC' '#FFF4DF'
Box 630 940 250 100 'BIT' 'Cấu hình logic PL' '#E3F2E9'
Box 910 940 250 100 'HWH' 'Metadata PS–PL' '#E3F2E9'
Arrow @(895,315,895,355); Arrow @(895,445,895,495); Arrow @(895,590,895,640); Arrow @(895,735,895,785)
Arrow @(820,890,820,915,755,915,755,940)
Arrow @(1160,260,1180,260,1180,920,1035,920,1035,940) '#6F8194' $true
Arrow @(505,275,570,275,570,245,630,245)
Arrow @(505,425,555,425,555,270,630,270)
Arrow @(505,575,580,575,580,295,630,295)
Arrow @(505,725,610,725,610,280,630,280) '#6F8194' $true
Box 75 1010 420 70 'XSim: chạy native regression' '' '#FFF4DF'
Arrow @(285,990,285,1010)
Arrow @(495,1045,565,1045,565,540,630,540) '#B78420' $true
Label 'PASS chức năng' 485 815 125 50 '#9B731E'
Box 1290 220 440 110 'Boot từ microSD' 'Hệ điều hành Linux + môi trường PYNQ' '#E3F2E9'
Box 1290 435 440 145 'Python Overlay' "Nhận cặp .bit + .hwh cùng build`nThiết lập clock và nạp cấu hình PL" '#E3F2E9'
Box 1290 690 440 130 'Driver mdct_pynq.py' "Nạp 2048 PCM → phát start`nChờ done → đọc 1024 hệ số" '#E3F2E9'
Box 1290 925 440 130 'Kết quả kiểm thử' "1024 hệ số Q31 + exponent`nSo golden: 18 frame / 18.432 bins" '#FFF4DF'
Arrow @(1510,330,1510,435)
Arrow @(1510,580,1510,690)
Arrow @(1510,820,1510,925)
Arrow @(880,990,895,990,895,1065,1225,1065,1225,500,1290,500)
Arrow @(1160,990,1210,990,1210,540,1290,540)
Label 'SCP / SFTP' 1195 610 85 48
Save '01-vhdl-to-pynq-z2.png' 1200

# 2. PS / PL integration.  Separate return lanes prevent bidirectional-label ambiguity.
Canvas 1400 '02  |  ARM ↔ MDCT TRONG HỆ THỐNG PYNQ-Z2' 'PS chạy phần mềm; PL thực hiện MDCT bằng phần cứng. Dữ liệu và điều khiển hiện đều truyền qua AXI4-Lite.'
Frame 30 130 1740 1210 'BOARD PYNQ-Z2  |  ZYNQ-7020 + DDR + microSD + LED'
Frame 65 200 475 1040 'PS  |  PROCESSING SYSTEM' '#F1F6FC'
Frame 580 200 1150 1040 'PL  |  PROGRAMMABLE LOGIC' '#F5FAF7'
Box 95 275 415 100 'ARM Cortex-A9' 'Linux / PYNQ / Jupyter'
Box 95 415 415 100 'mdct_pynq.py' 'Python điều khiển bằng MMIO'
Box 95 600 415 110 'M_AXI_GP0' 'Cổng master từ PS sang PL'
Box 95 840 190 115 'microSD' "Boot Linux`nLưu file" '#FFF4DF'
Box 310 840 200 115 'DDR board' "Bộ nhớ ARM`nPCM / kết quả" '#FFF4DF'
Box 95 1055 190 130 'FCLK_CLK0' "Mục tiêu`n100 MHz" '#EDE8FA'
Box 310 1055 200 130 'PS reset' 'FCLK_RESET0_N' '#EDE8FA'
Arrow @(302,375,302,415); Arrow @(302,515,302,600)
Arrow @(185,840,185,780,80,780,80,325,95,325)
Arrow @(410,840,410,785,530,785,530,325,510,325)
Box 645 280 410 110 'AXI Interconnect' 'Định tuyến giao dịch AXI'
Box 1130 280 520 110 'Processor System Reset' 'Reset AXI/core; đồng bộ nhả reset' '#EDE8FA'
Frame 640 455 1020 430 'mdct_axi_lite.vhd  |  S_AXI @ 0x43C00000' '#EDF6F0'
Box 675 520 950 110 'Thanh ghi AXI4-Lite 32-bit' "CONTROL / STATUS / PCM_DATA / SPEC_INDEX / SPEC_DATA / MDCT_EXP`nĐịa chỉ PCM tự tăng; trạng thái done và error được chốt"
Box 675 680 280 150 'Bộ nạp PCM' "Index 0–2047`nGiữ valid đến ready"
Box 1000 680 280 150 'Lệnh frame' "start / block_type`nright_shape / clear_history"
Box 1325 680 300 150 'Bộ đọc spectrum' "Index 0–1023`nChốt dữ liệu khi valid"
Box 675 1040 950 150 'mdct_core.vhd  |  Trace tắt khi synthesis' "Window + TDAC fold → DCT-IV pre → FFT → DCT-IV post`nRAM snapshot: 2048 × 16-bit  |  RAM spectrum: 1024 × 32-bit" '#E3F2E9'
Arrow @(510,625,600,625,600,320,645,320)
Arrow @(645,355,565,355,565,690,510,690)
Label 'Ghi / đọc MMIO' 535 405 155 28
Arrow @(830,390,830,520); Arrow @(915,520,915,390)
Label 'AXI4-Lite' 730 408 130 28
Arrow @(815,630,815,680); Arrow @(1140,630,1140,680); Arrow @(1475,630,1475,680)
Arrow @(770,830,770,1040); Arrow @(875,1040,875,830)
Label "pcm_valid / index / data`nready trả về" 675 910 270 70
Arrow @(1080,830,1080,1040); Arrow @(1205,1040,1205,830)
Label "Lệnh + metadata`nbusy / done / exponent" 970 910 320 70
Arrow @(1390,830,1390,1040); Arrow @(1550,1040,1550,830)
Label "rd_en / rd_index`nrd_valid / rd_data" 1310 910 320 70
Arrow @(285,1100,565,1100,565,1260,1700,1260,1700,335,1650,335) '#8265AC' $true
Arrow @(510,1150,550,1150,550,1280,1710,1280,1710,360,1650,360) '#8265AC' $true
Label 'Clock chung: GP0_ACLK, AXI fabric, adapter, core và reset synchronizer' 645 1240 995 30 '#8265AC'
Arrow @(1390,390,1390,455) '#8265AC' $true
Box 85 1260 425 55 'LD0 ready | LD1 active | LD2 done | LD3 error' '' '#FFF4DF'
Arrow @(640,815,615,815,615,1220,520,1220,520,1288,510,1288)
Save '02-pynq-z2-ps-pl-mdct.png' 1400

# 3. Native datapath, with engine-local RAM and separate coefficient/control lanes.
Canvas 1460 '03  |  DATAPATH BÊN TRONG mdct_core.vhd' 'Mũi tên liền: dữ liệu / hệ số. Mũi tên nét đứt: điều khiển. Các RAM được mô tả trong RTL để Vivado ánh xạ.'
Frame 425 130 940 1235 'mdct_core.vhd  |  LÕI BIẾN ĐỔI'
Box 60 215 310 200 'mdct_control.vhd' "FSM điều phối engine`nLONG / START / SHORT / STOP`nLưu history SINE / KBD" '#FFF4DF'
Box 65 515 300 135 'Metadata từ adapter' "start, block_type, right_shape`nclear_history"
Arrow @(215,515,215,415)
Box 60 850 310 180 'Cấu hình biến đổi' "LONG / START / STOP:`n1 × FFT-512; exponent 12`nSHORT:`n8 × FFT-64; exponent 9" '#FFF4DF'
Box 480 200 830 90 'mdct_pcm_memory.vhd' 'Snapshot PCM: 2048 × signed 16-bit'
Box 480 345 830 95 'mdct_window_fold.vhd' 'Nhân cửa sổ Q15 và TDAC fold'
Box 480 495 830 120 'mdct_dct4_pre.vhd' "mdct_work_memory.vhd: đệm sau fold`nPre-rotation → dữ liệu phức Q31"
Frame 480 675 830 240 'fft_radix2_core.vhd' '#EAF1FA'
Box 510 735 200 130 'FFT control' "Stage counter`nAddress generator"
Box 750 735 240 130 'RAM ping-pong' 'Dữ liệu phức Q31'
Box 1030 735 250 130 'Butterfly pipeline' 'Nhân + cộng / trừ'
Arrow @(710,800,750,800) '#B78420' $true
Arrow @(990,770,1030,770); Arrow @(1030,830,990,830)
Box 480 970 830 120 'mdct_dct4_post.vhd' "mdct_fft_cache_memory.vhd: đệm kết quả FFT`nPost-rotation → hệ số MDCT"
Box 480 1145 830 90 'mdct_spectrum_memory.vhd' 'Spectrum: 1024 × signed Q31, thứ tự tự nhiên'
Box 480 1285 830 60 'Trả 1024 hệ số + mdct_exp về adapter / ARM' '' '#E3F2E9'
Arrow @(895,290,895,345); Arrow @(895,440,895,495); Arrow @(895,615,895,675)
Arrow @(895,915,895,970); Arrow @(895,1090,895,1145); Arrow @(895,1235,895,1285)
Box 1430 200 310 90 'Input từ adapter' 'PCM, index, valid / ready'
Arrow @(1430,245,1310,245)
Box 1430 350 310 110 'mdct_window_rom.vhd' "Hệ số SINE / KBD`nLong và short" '#EDE8FA'
Arrow @(1430,395,1310,395) '#8265AC'
Box 1430 535 310 110 'mdct_rotation_rom.vhd' 'Instance PRE: hệ số Q15' '#EDE8FA'
Arrow @(1430,575,1310,575) '#8265AC'
Box 1430 745 310 120 'fft_radix2_twiddle_rom.vhd' 'Twiddle FFT Q15' '#EDE8FA'
Arrow @(1430,805,1280,805) '#8265AC'
Box 1430 975 310 115 'mdct_rotation_rom.vhd' 'Instance POST: hệ số Q15' '#EDE8FA'
Arrow @(1430,1030,1310,1030) '#8265AC'
Arrow @(370,275,395,275,395,390,480,390) '#B78420' $true
Arrow @(395,390,395,550,480,550) '#B78420' $true
Arrow @(395,550,395,800,480,800) '#B78420' $true
Arrow @(395,800,395,1030,480,1030) '#B78420' $true
Label 'start / done' 260 710 145 28 '#9B731E'
Arrow @(220,1030,220,1315,480,1315) '#B78420' $true
Label 'mdct_exp' 250 1298 135 30 '#9B731E'
Text 'Clock / reset chung cho toàn bộ core. Trace nội bộ được tắt qua ENABLE_TRACE=false trong adapter board.' 435 1372 1290 30 17 '#51667A'
Save '03-mdct-core-datapath.png' 1460
