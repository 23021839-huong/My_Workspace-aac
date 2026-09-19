## PYNQ-Z2 user LEDs.  DDR and FIXED_IO belong to the Zynq processing-system
## board preset and are constrained by the processing_system7 IP.
##
## Pin mapping follows the official PYNQ-Z2 base-overlay constraints:
## https://github.com/Xilinx/PYNQ/blob/master/boards/Pynq-Z2/base/vivado/constraints/base.xdc

set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {status_led[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {status_led[1]}]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports {status_led[2]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {status_led[3]}]

set_property DRIVE 8 [get_ports {status_led[*]}]
set_property SLEW SLOW [get_ports {status_led[*]}]

## Human-visible indicators have no external sampling clock or I/O deadline.
## Limit this exception to the four LED ports; internal AXI/MDCT stays timed.
set_false_path -to [get_ports {status_led[*]}]
