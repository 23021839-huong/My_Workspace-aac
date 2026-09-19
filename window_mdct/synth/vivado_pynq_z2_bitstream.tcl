# Build a software-controlled PYNQ-Z2 overlay for mdct_core.
#
# Run from my_workspace/window_mdct (or pass an absolute script path):
#   vivado -mode batch -source synth/vivado_pynq_z2_bitstream.tcl
#
# Requirements:
#   * PYNQ-Z2 board files installed in Vivado
#   * processing_system7 and AXI interconnect/SmartConnect IP available

set script_dir [file dirname [file normalize [info script]]]
set mdct_root [file dirname $script_dir]
set fft_root [file join $mdct_root fft_radix2_core]
set project_dir [file join $mdct_root .vivado_pynq_z2]
set project_name mdct_pynq_z2
set design_name mdct_pynq_z2
set part_name xc7z020clg400-1

if {[info exists ::env(VIVADO_JOBS)] && $::env(VIVADO_JOBS) ne ""} {
  set jobs $::env(VIVADO_JOBS)
} else {
  set jobs 4
}
if {![string is integer -strict $jobs] || $jobs < 1} {
  error "VIVADO_JOBS must be a positive integer"
}

# The current Q31/Q15 datapath routes at about 66.1 MHz on XC7Z020-1
# (15.139 ns effective critical period).  Use 50 MHz by default to leave safe
# timing margin.
# Override before sourcing the script when characterizing another frequency:
#   set ::env(MDCT_FCLK_MHZ) 62.5
if {[info exists ::env(MDCT_FCLK_MHZ)] && $::env(MDCT_FCLK_MHZ) ne ""} {
  set mdct_fclk_mhz $::env(MDCT_FCLK_MHZ)
} else {
  set mdct_fclk_mhz 50.000000
}
if {![string is double -strict $mdct_fclk_mhz] || $mdct_fclk_mhz <= 0.0} {
  error "MDCT_FCLK_MHZ must be a positive number, got '$mdct_fclk_mhz'"
}
set mdct_fclk_hz [expr {int(round(double($mdct_fclk_mhz) * 1000000.0))}]

create_project $project_name $project_dir -part $part_name -force
set_property target_language VHDL [current_project]
set_property simulator_language Mixed [current_project]

# Prefer an explicitly selected board part.  Otherwise use the newest PYNQ-Z2
# board definition installed in this Vivado instance.
if {[info exists ::env(BOARD_PART)] && $::env(BOARD_PART) ne ""} {
  set board_part $::env(BOARD_PART)
} else {
  set board_parts [get_board_parts -quiet "tul.com.tw:pynq-z2:part0:*"]
  if {[llength $board_parts] == 0} {
    error "PYNQ-Z2 board files are not installed. Install the TUL PYNQ-Z2 board definition, or set BOARD_PART to its exact Vivado board-part name."
  }
  set board_part [lindex [lsort -dictionary $board_parts] end]
}
puts "Target board part: $board_part"
set_property board_part $board_part [current_project]

# Packages first, followed by FFT, MDCT and the AXI adapter.
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_pkg.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_pkg.vhd]

read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_twiddle_rom.vhd]
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_addr_gen.vhd]
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_memory.vhd]
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_butterfly.vhd]
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_control.vhd]
read_vhdl -vhdl2008 [file join $fft_root rtl fft_radix2_core.vhd]

read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_window_rom.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_rotation_rom.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_pcm_memory.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_work_memory.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_fft_cache_memory.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_spectrum_memory.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_window_fold.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_dct4_pre.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_dct4_post.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_control.vhd]
read_vhdl -vhdl2008 [file join $mdct_root rtl mdct_core.vhd]
# Vivado IP Integrator does not accept a VHDL-2008 source as the top file of a
# Module Reference (FileMgmt 56-195).  The AXI adapter itself is VHDL-93
# compatible, while the MDCT/FFT dependencies above remain VHDL-2008.
read_vhdl [file join $mdct_root board pynq_z2 mdct_axi_lite.vhd]
read_xdc [file join $mdct_root board pynq_z2 pynq_z2_mdct.xdc]
update_compile_order -fileset sources_1

create_bd_design $design_name
set ps7 [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
  -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} \
  $ps7
set_property -dict [list \
  CONFIG.PCW_USE_M_AXI_GP0 {1} \
  CONFIG.PCW_EN_CLK0_PORT {1} \
  CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $mdct_fclk_mhz \
] $ps7
puts "MDCT/AXI PL clock requested: $mdct_fclk_mhz MHz"

set mdct_axi [create_bd_cell -type module -reference mdct_axi_lite mdct_axi_0]
# The module-reference source intentionally does not hard-code FREQ_HZ.  Keep
# its AXI clock metadata equal to the selected PS FCLK so Connection Automation
# connects FCLK_CLK0 directly instead of inserting an orphan clock wizard.
set_property CONFIG.FREQ_HZ $mdct_fclk_hz [get_bd_pins $mdct_axi/s_axi_aclk]
make_bd_pins_external [get_bd_pins $mdct_axi/status_led]
set_property name status_led [get_bd_ports status_led_0]

# Let Vivado insert the AXI fabric and reset synchronizer between PS GP0 and
# the module-reference AXI4-Lite slave.
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
  -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/ps7/M_AXI_GP0} Slave {/mdct_axi_0/S_AXI} ddr_seg {Auto} intc_ip {New AXI Interconnect} master_apm {0}} \
  [get_bd_intf_pins $mdct_axi/S_AXI]

set mdct_addr_segs [get_bd_addr_segs -quiet $mdct_axi/S_AXI/*]
if {[llength $mdct_addr_segs] != 1} {
  error "Expected one inferred AXI address segment on mdct_axi_0/S_AXI, found [llength $mdct_addr_segs]"
}
assign_bd_address -offset 0x43C00000 -range 0x00010000 \
  -target_address_space [get_bd_addr_spaces $ps7/Data] \
  [lindex $mdct_addr_segs 0] -force

validate_bd_design
save_bd_design

set bd_file [get_files -quiet ${design_name}.bd]
generate_target all $bd_file
set wrapper_files [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper_files
set_property top ${design_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
if {![string match "*Complete*" $synth_status]} {
  error "Synthesis failed: $synth_status"
}

open_run synth_1
report_utilization -hierarchical \
  -file [file join $mdct_root synth pynq_z2_utilization_post_synth.rpt]
close_design

# Stop after route first: Vivado can write a bitstream despite negative slack.
launch_runs impl_1 -to_step route_design -jobs $jobs
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match "*Complete*" $impl_status]} {
  error "Implementation failed: $impl_status"
}

open_run impl_1
report_timing_summary -delay_type min_max -max_paths 20 -report_unconstrained \
  -file [file join $mdct_root synth pynq_z2_timing_post_route.rpt]
report_utilization -hierarchical \
  -file [file join $mdct_root synth pynq_z2_utilization_post_route.rpt]
report_clock_utilization \
  -file [file join $mdct_root synth pynq_z2_clock_utilization_post_route.rpt]
report_power \
  -file [file join $mdct_root synth pynq_z2_power_post_route.rpt]
report_methodology \
  -file [file join $mdct_root synth pynq_z2_methodology_post_route.rpt]
report_drc -file [file join $mdct_root synth pynq_z2_drc_post_route.rpt]
check_timing -verbose \
  -file [file join $mdct_root synth pynq_z2_check_timing_post_route.rpt]

# Check internal coverage explicitly. LED outputs are asynchronous indicators;
# their paths are excepted in the board XDC, not internal register paths.
foreach check_name {no_clock unconstrained_internal_endpoints} {
  set check_text [check_timing -override_defaults [list $check_name] -return_string]
  set counts [regexp -all -inline -nocase {There (?:are|is) ([0-9]+)} $check_text]
  if {[llength $counts] == 0} {
    error "Cannot parse check_timing $check_name; inspect the check_timing report. No overlay exported."
  }
  foreach {match count} $counts {
    if {$count != 0} {
      error "check_timing $check_name found $count issues. No overlay exported."
    }
  }
}
foreach delay_type {max min} {
  set worst_path [get_timing_paths -delay_type $delay_type -max_paths 1 -nworst 1]
  if {[llength $worst_path] != 1} {
    error "No constrained $delay_type timing path found. No overlay exported."
  }
  set slack [get_property SLACK $worst_path]
  if {![string is double -strict $slack] || $slack < 0.0} {
    error "Timing failed ($delay_type slack=$slack ns) at $mdct_fclk_mhz MHz. No overlay exported."
  }
  set timing_slack($delay_type) $slack
}
close_design

launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
if {![string match "*Complete*" $impl_status]} {
  error "Bitstream generation failed: $impl_status"
}

# HWH locations differ between Vivado releases. Require a nonempty companion.
set hwh_src ""
foreach generated_dir [list ${project_name}.gen ${project_name}.srcs] {
  set candidate [file join $project_dir $generated_dir sources_1 bd $design_name hw_handoff ${design_name}.hwh]
  if {[file exists $candidate] && [file size $candidate] > 0} {
    set hwh_src $candidate
    break
  }
}
if {$hwh_src eq ""} {
  error "No HWH generated for $design_name. No overlay exported."
}
set bit_src [file join $project_dir ${project_name}.runs impl_1 ${design_name}_wrapper.bit]
if {![file exists $bit_src] || [file size $bit_src] == 0} {
  error "Missing or empty bitstream: $bit_src"
}

# Each successful export gets a fresh directory, avoiding stale .bit/.hwh pairs
# from previous failed builds. The packer requires build_info.txt written last.
set build_id "[clock format [clock seconds] -gmt 1 -format %Y%m%dT%H%M%SZ]_[pid]"
set export_dir [file join $mdct_root build pynq_z2 $build_id]
if {[file exists $export_dir]} { error "Export directory already exists: $export_dir" }
file mkdir $export_dir
set bit_dst [file join $export_dir mdct_pynq_z2.bit]
file copy $bit_src $bit_dst
file copy $hwh_src [file join $export_dir mdct_pynq_z2.hwh]
file mkdir [file join $export_dir reports]
foreach report_file [glob [file join $mdct_root synth pynq_z2_*.rpt]] {
  file copy $report_file [file join $export_dir reports [file tail $report_file]]
}
set info_file [open [file join $export_dir build_info.txt] w]
puts $info_file "build_id=$build_id"
puts $info_file "vivado=[version -short]"
puts $info_file "part=$part_name"
puts $info_file "board_part=$board_part"
puts $info_file "fclk_mhz=$mdct_fclk_mhz"
puts $info_file "base_address=0x43C00000"
puts $info_file "setup_slack_ns=$timing_slack(max)"
puts $info_file "hold_slack_ns=$timing_slack(min)"
puts $info_file "internal_timing_coverage=PASS"
puts $info_file "export_status=PASS"
close $info_file

puts "PYNQ-Z2 overlay generated:"
puts "  $bit_dst"
puts "  [file join $export_dir mdct_pynq_z2.hwh]"
puts "AXI4-Lite base address: 0x43C00000"
puts "MDCT/AXI PL clock: $mdct_fclk_mhz MHz"
puts "Next: python tools/pack_pynq_z2.py --overlay-dir $export_dir"
