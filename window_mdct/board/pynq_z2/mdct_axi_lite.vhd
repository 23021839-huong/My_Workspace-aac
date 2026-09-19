-------------------------------------------------------------------------------
-- PYNQ-Z2 AXI4-Lite adapter for mdct_core.
--
-- The adapter deliberately keeps the bulk sample traffic behind one 32-bit
-- AXI4-Lite aperture.  It is intended for bring-up, software-controlled
-- regression and low-rate frame processing.  A future real-time design can
-- replace this adapter with AXI DMA/AXI-Stream without changing mdct_core.
-------------------------------------------------------------------------------
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.mdct_pkg.all;

entity mdct_axi_lite is
  generic (
    C_S_AXI_DATA_WIDTH : positive := 32;
    C_S_AXI_ADDR_WIDTH : positive := 6
  );
  port (
    -- LD0..LD3: loader-ready, active, result-ready, protocol-error.
    status_led : out std_logic_vector(3 downto 0);

    s_axi_aclk    : in  std_logic;
    s_axi_aresetn : in  std_logic;
    s_axi_awaddr  : in  std_logic_vector(C_S_AXI_ADDR_WIDTH - 1 downto 0);
    s_axi_awprot  : in  std_logic_vector(2 downto 0);
    s_axi_awvalid : in  std_logic;
    s_axi_awready : out std_logic;
    s_axi_wdata   : in  std_logic_vector(C_S_AXI_DATA_WIDTH - 1 downto 0);
    s_axi_wstrb   : in  std_logic_vector((C_S_AXI_DATA_WIDTH / 8) - 1 downto 0);
    s_axi_wvalid  : in  std_logic;
    s_axi_wready  : out std_logic;
    s_axi_bresp   : out std_logic_vector(1 downto 0);
    s_axi_bvalid  : out std_logic;
    s_axi_bready  : in  std_logic;
    s_axi_araddr  : in  std_logic_vector(C_S_AXI_ADDR_WIDTH - 1 downto 0);
    s_axi_arprot  : in  std_logic_vector(2 downto 0);
    s_axi_arvalid : in  std_logic;
    s_axi_arready : out std_logic;
    s_axi_rdata   : out std_logic_vector(C_S_AXI_DATA_WIDTH - 1 downto 0);
    s_axi_rresp   : out std_logic_vector(1 downto 0);
    s_axi_rvalid  : out std_logic;
    s_axi_rready  : in  std_logic
  );
end entity mdct_axi_lite;

architecture rtl of mdct_axi_lite is
  attribute X_INTERFACE_INFO : string;
  attribute X_INTERFACE_PARAMETER : string;

  attribute X_INTERFACE_INFO of s_axi_aclk : signal is
    "xilinx.com:signal:clock:1.0 S_AXI_CLK CLK";
  attribute X_INTERFACE_PARAMETER of s_axi_aclk : signal is
    "XIL_INTERFACENAME S_AXI_CLK, ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET s_axi_aresetn";
  attribute X_INTERFACE_INFO of s_axi_aresetn : signal is
    "xilinx.com:signal:reset:1.0 S_AXI_RST RST";
  attribute X_INTERFACE_PARAMETER of s_axi_aresetn : signal is
    "XIL_INTERFACENAME S_AXI_RST, POLARITY ACTIVE_LOW";

  attribute X_INTERFACE_INFO of s_axi_awaddr  : signal is "xilinx.com:interface:aximm:1.0 S_AXI AWADDR";
  attribute X_INTERFACE_INFO of s_axi_awprot  : signal is "xilinx.com:interface:aximm:1.0 S_AXI AWPROT";
  attribute X_INTERFACE_INFO of s_axi_awvalid : signal is "xilinx.com:interface:aximm:1.0 S_AXI AWVALID";
  attribute X_INTERFACE_INFO of s_axi_awready : signal is "xilinx.com:interface:aximm:1.0 S_AXI AWREADY";
  attribute X_INTERFACE_INFO of s_axi_wdata   : signal is "xilinx.com:interface:aximm:1.0 S_AXI WDATA";
  attribute X_INTERFACE_INFO of s_axi_wstrb   : signal is "xilinx.com:interface:aximm:1.0 S_AXI WSTRB";
  attribute X_INTERFACE_INFO of s_axi_wvalid  : signal is "xilinx.com:interface:aximm:1.0 S_AXI WVALID";
  attribute X_INTERFACE_INFO of s_axi_wready  : signal is "xilinx.com:interface:aximm:1.0 S_AXI WREADY";
  attribute X_INTERFACE_INFO of s_axi_bresp   : signal is "xilinx.com:interface:aximm:1.0 S_AXI BRESP";
  attribute X_INTERFACE_INFO of s_axi_bvalid  : signal is "xilinx.com:interface:aximm:1.0 S_AXI BVALID";
  attribute X_INTERFACE_INFO of s_axi_bready  : signal is "xilinx.com:interface:aximm:1.0 S_AXI BREADY";
  attribute X_INTERFACE_INFO of s_axi_araddr  : signal is "xilinx.com:interface:aximm:1.0 S_AXI ARADDR";
  attribute X_INTERFACE_INFO of s_axi_arprot  : signal is "xilinx.com:interface:aximm:1.0 S_AXI ARPROT";
  attribute X_INTERFACE_INFO of s_axi_arvalid : signal is "xilinx.com:interface:aximm:1.0 S_AXI ARVALID";
  attribute X_INTERFACE_INFO of s_axi_arready : signal is "xilinx.com:interface:aximm:1.0 S_AXI ARREADY";
  attribute X_INTERFACE_INFO of s_axi_rdata   : signal is "xilinx.com:interface:aximm:1.0 S_AXI RDATA";
  attribute X_INTERFACE_INFO of s_axi_rresp   : signal is "xilinx.com:interface:aximm:1.0 S_AXI RRESP";
  attribute X_INTERFACE_INFO of s_axi_rvalid  : signal is "xilinx.com:interface:aximm:1.0 S_AXI RVALID";
  attribute X_INTERFACE_INFO of s_axi_rready  : signal is "xilinx.com:interface:aximm:1.0 S_AXI RREADY";

  -- Word offsets inside the 64-byte AXI aperture.
  constant REG_CONTROL    : natural := 0; -- 0x00
  constant REG_STATUS     : natural := 1; -- 0x04
  constant REG_PCM_INDEX  : natural := 2; -- 0x08
  constant REG_PCM_DATA   : natural := 3; -- 0x0c, write enqueues one sample
  constant REG_SPEC_INDEX : natural := 4; -- 0x10
  constant REG_SPEC_DATA  : natural := 5; -- 0x14
  constant REG_MDCT_EXP   : natural := 6; -- 0x18
  constant REG_ID         : natural := 7; -- 0x1c
  constant REG_PCM_COUNT  : natural := 8; -- 0x20

  signal aw_hold_r : std_logic := '0';
  signal awaddr_r  : std_logic_vector(C_S_AXI_ADDR_WIDTH - 1 downto 0) := (others => '0');
  signal w_hold_r  : std_logic := '0';
  signal wdata_r   : std_logic_vector(C_S_AXI_DATA_WIDTH - 1 downto 0) := (others => '0');
  signal wstrb_r   : std_logic_vector((C_S_AXI_DATA_WIDTH / 8) - 1 downto 0) := (others => '0');
  signal bvalid_r  : std_logic := '0';
  signal rvalid_r  : std_logic := '0';
  signal rdata_r   : std_logic_vector(C_S_AXI_DATA_WIDTH - 1 downto 0) := (others => '0');

  signal pcm_valid_r       : std_logic := '0';
  signal pcm_ready_s       : std_logic;
  signal pcm_issue_index_r : mdct_pcm_addr_t := (others => '0');
  signal pcm_next_index_r  : mdct_pcm_addr_t := (others => '0');
  signal pcm_issue_data_r  : mdct_pcm_t := (others => '0');
  signal pcm_count_r       : natural range 0 to MDCT_SNAPSHOT_N := 0;
  signal pcm_loader_ready_s : std_logic;

  signal start_r         : std_logic := '0';
  signal clear_history_r : std_logic := '0';
  signal block_type_r    : mdct_block_t := MDCT_LONG;
  signal right_shape_r   : mdct_shape_t := MDCT_SINE;
  signal core_busy_s     : std_logic;
  signal core_done_s     : std_logic;
  signal frame_active_r  : std_logic := '0';
  signal done_sticky_r   : std_logic := '0';
  signal protocol_error_r : std_logic := '0';
  signal mdct_exp_s      : unsigned(4 downto 0);

  signal spec_rd_en_r       : std_logic := '0';
  signal spec_issue_index_r : mdct_data_addr_t := (others => '0');
  signal spec_next_index_r  : mdct_data_addr_t := (others => '0');
  signal spec_pending_r     : std_logic := '0';
  signal spec_rd_valid_s    : std_logic;
  signal spec_rd_data_s     : mdct_data_t;
  signal spec_data_r        : mdct_data_t := (others => '0');
  signal spec_data_valid_r  : std_logic := '0';

  function merge_wstrb(
    old_value : std_logic_vector(31 downto 0);
    new_value : std_logic_vector(31 downto 0);
    byte_en   : std_logic_vector(3 downto 0)
  ) return std_logic_vector is
    variable result : std_logic_vector(31 downto 0) := old_value;
  begin
    for lane in 0 to 3 loop
      if byte_en(lane) = '1' then
        result(8 * lane + 7 downto 8 * lane) :=
          new_value(8 * lane + 7 downto 8 * lane);
      end if;
    end loop;
    return result;
  end function;
begin
  assert C_S_AXI_DATA_WIDTH = 32
    report "mdct_axi_lite requires a 32-bit AXI4-Lite data bus"
    severity failure;
  assert C_S_AXI_ADDR_WIDTH >= 6
    report "mdct_axi_lite requires at least six AXI address bits"
    severity failure;

  s_axi_awready <= s_axi_aresetn and not aw_hold_r;
  s_axi_wready  <= s_axi_aresetn and not w_hold_r;
  s_axi_bresp   <= "00";
  s_axi_bvalid  <= bvalid_r;
  s_axi_arready <= s_axi_aresetn and not rvalid_r;
  s_axi_rdata   <= rdata_r;
  s_axi_rresp   <= "00";
  s_axi_rvalid  <= rvalid_r;

  pcm_loader_ready_s <= '1' when frame_active_r = '0' and pcm_valid_r = '0' and
                                pcm_count_r < MDCT_SNAPSHOT_N else '0';
  status_led(0) <= pcm_loader_ready_s;
  status_led(1) <= frame_active_r or core_busy_s;
  status_led(2) <= done_sticky_r;
  status_led(3) <= protocol_error_r;

  u_mdct_core : entity work.mdct_core
    generic map (
      ENABLE_TRACE => false
    )
    port map (
      clk => s_axi_aclk,
      rst_n => s_axi_aresetn,
      pcm_valid => pcm_valid_r,
      pcm_ready => pcm_ready_s,
      pcm_index => pcm_issue_index_r,
      pcm_data => pcm_issue_data_r,
      start => start_r,
      block_type => block_type_r,
      right_shape => right_shape_r,
      clear_history => clear_history_r,
      busy => core_busy_s,
      done => core_done_s,
      mdct_exp => mdct_exp_s,
      spec_rd_en => spec_rd_en_r,
      spec_rd_index => spec_issue_index_r,
      spec_rd_valid => spec_rd_valid_s,
      spec_rd_data => spec_rd_data_s,
      trace_sub_index => open,
      trace_fold_valid => open,
      trace_fold_index => open,
      trace_fold_data => open,
      trace_pre_valid => open,
      trace_pre_index => open,
      trace_pre_re => open,
      trace_pre_im => open,
      trace_fft_valid => open,
      trace_fft_index => open,
      trace_fft_re => open,
      trace_fft_im => open,
      trace_post_valid => open,
      trace_post_index => open,
      trace_post_data => open,
      trace_fft_stage_valid => open,
      trace_fft_stage_last => open,
      trace_fft_stage => open,
      trace_fft_addr_a => open,
      trace_fft_addr_b => open,
      trace_fft_a_re => open,
      trace_fft_a_im => open,
      trace_fft_b_re => open,
      trace_fft_b_im => open
    );

  process(s_axi_aclk)
    variable write_word_v : natural;
    variable read_word_v  : natural;
    variable old_value_v  : std_logic_vector(31 downto 0);
    variable merged_v     : std_logic_vector(31 downto 0);
    variable read_v       : std_logic_vector(31 downto 0);
  begin
    if rising_edge(s_axi_aclk) then
      if s_axi_aresetn = '0' then
        aw_hold_r <= '0';
        awaddr_r <= (others => '0');
        w_hold_r <= '0';
        wdata_r <= (others => '0');
        wstrb_r <= (others => '0');
        bvalid_r <= '0';
        rvalid_r <= '0';
        rdata_r <= (others => '0');

        pcm_valid_r <= '0';
        pcm_issue_index_r <= (others => '0');
        pcm_next_index_r <= (others => '0');
        pcm_issue_data_r <= (others => '0');
        pcm_count_r <= 0;
        start_r <= '0';
        clear_history_r <= '0';
        block_type_r <= MDCT_LONG;
        right_shape_r <= MDCT_SINE;
        frame_active_r <= '0';
        done_sticky_r <= '0';
        protocol_error_r <= '0';

        spec_rd_en_r <= '0';
        spec_issue_index_r <= (others => '0');
        spec_next_index_r <= (others => '0');
        spec_pending_r <= '0';
        spec_data_r <= (others => '0');
        spec_data_valid_r <= '0';
      else
        start_r <= '0';
        clear_history_r <= '0';
        spec_rd_en_r <= '0';

        -- Keep PCM valid asserted until mdct_core accepts the indexed sample.
        if pcm_valid_r = '1' and pcm_ready_s = '1' then
          pcm_valid_r <= '0';
          if pcm_count_r < MDCT_SNAPSHOT_N then
            pcm_count_r <= pcm_count_r + 1;
          end if;
          if pcm_next_index_r = to_unsigned(MDCT_SNAPSHOT_N - 1,
                                             pcm_next_index_r'length) then
            pcm_next_index_r <= (others => '0');
          else
            pcm_next_index_r <= pcm_next_index_r + 1;
          end if;
        end if;

        if core_done_s = '1' then
          frame_active_r <= '0';
          done_sticky_r <= '1';
          spec_next_index_r <= (others => '0');
        end if;

        if spec_rd_valid_s = '1' then
          spec_data_r <= spec_rd_data_s;
          spec_data_valid_r <= '1';
          spec_pending_r <= '0';
        end if;

        if bvalid_r = '1' and s_axi_bready = '1' then
          bvalid_r <= '0';
        end if;
        if rvalid_r = '1' and s_axi_rready = '1' then
          rvalid_r <= '0';
        end if;

        if s_axi_awvalid = '1' and aw_hold_r = '0' then
          awaddr_r <= s_axi_awaddr;
          aw_hold_r <= '1';
        end if;
        if s_axi_wvalid = '1' and w_hold_r = '0' then
          wdata_r <= s_axi_wdata;
          wstrb_r <= s_axi_wstrb;
          w_hold_r <= '1';
        end if;

        -- Address and data channels are buffered independently, as required by
        -- AXI4-Lite.  Commit only after both halves of a write have arrived.
        if aw_hold_r = '1' and w_hold_r = '1' and bvalid_r = '0' then
          write_word_v := to_integer(unsigned(awaddr_r(5 downto 2)));
          aw_hold_r <= '0';
          w_hold_r <= '0';
          bvalid_r <= '1';

          -- AXI permits an aborted write with all strobes deasserted. It must
          -- acknowledge without changing counters, flags or issuing commands.
          if wstrb_r /= "0000" then
          case write_word_v is
            when REG_CONTROL =>
              old_value_v := (others => '0');
              old_value_v(9 downto 8) := std_logic_vector(block_type_r);
              old_value_v(10) := right_shape_r;
              merged_v := merge_wstrb(old_value_v, wdata_r, wstrb_r);
              block_type_r <= unsigned(merged_v(9 downto 8));
              right_shape_r <= merged_v(10);

              if merged_v(3) = '1' then
                done_sticky_r <= '0';
                spec_data_valid_r <= '0';
                protocol_error_r <= '0';
              end if;

              if merged_v(0) = '1' and merged_v(2) = '1' then
                -- Starting a frame and issuing a spectrum read in the same
                -- command is ambiguous and therefore rejected.
                protocol_error_r <= '1';
              elsif merged_v(0) = '1' then
                if frame_active_r = '0' and pcm_valid_r = '0' and
                   spec_pending_r = '0' and pcm_count_r = MDCT_SNAPSHOT_N then
                  start_r <= '1';
                  clear_history_r <= merged_v(1);
                  frame_active_r <= '1';
                  done_sticky_r <= '0';
                  spec_data_valid_r <= '0';
                  pcm_count_r <= 0;
                else
                  protocol_error_r <= '1';
                end if;
              elsif merged_v(2) = '1' then
                if frame_active_r = '0' and spec_pending_r = '0' and
                   done_sticky_r = '1' then
                  spec_issue_index_r <= spec_next_index_r;
                  spec_rd_en_r <= '1';
                  spec_pending_r <= '1';
                  spec_data_valid_r <= '0';
                  if spec_next_index_r = to_unsigned(MDCT_FRAME_LEN - 1,
                                                      spec_next_index_r'length) then
                    spec_next_index_r <= (others => '0');
                  else
                    spec_next_index_r <= spec_next_index_r + 1;
                  end if;
                else
                  protocol_error_r <= '1';
                end if;
              end if;

            when REG_PCM_INDEX =>
              -- The PCM address is deliberately auto-incremented.  Making it
              -- software-writable would desynchronise it from mdct_core's own
              -- contiguous-load counter.
              protocol_error_r <= '1';

            when REG_PCM_DATA =>
              if pcm_valid_r = '0' and frame_active_r = '0' and
                 pcm_count_r < MDCT_SNAPSHOT_N and wstrb_r(1 downto 0) = "11" then
                old_value_v := (others => '0');
                merged_v := merge_wstrb(old_value_v, wdata_r, wstrb_r);
                pcm_issue_index_r <= pcm_next_index_r;
                pcm_issue_data_r <= signed(merged_v(15 downto 0));
                pcm_valid_r <= '1';
              else
                protocol_error_r <= '1';
              end if;

            when REG_SPEC_INDEX =>
              old_value_v := (others => '0');
              old_value_v(9 downto 0) := std_logic_vector(spec_next_index_r);
              merged_v := merge_wstrb(old_value_v, wdata_r, wstrb_r);
              if spec_pending_r = '0' and
                 unsigned(merged_v(9 downto 0)) < MDCT_FRAME_LEN then
                spec_next_index_r <= unsigned(merged_v(9 downto 0));
                spec_data_valid_r <= '0';
              else
                protocol_error_r <= '1';
              end if;

            when others =>
              null;
          end case;
          end if;
        end if;

        if s_axi_arvalid = '1' and rvalid_r = '0' then
          read_word_v := to_integer(unsigned(s_axi_araddr(5 downto 2)));
          read_v := (others => '0');
          case read_word_v is
            when REG_CONTROL =>
              read_v(9 downto 8) := std_logic_vector(block_type_r);
              read_v(10) := right_shape_r;
            when REG_STATUS =>
              -- Use the internal status signal so this adapter remains valid
              -- VHDL-93 for use as a Vivado IP Integrator Module Reference.
              read_v(0) := pcm_loader_ready_s;
              read_v(1) := frame_active_r or core_busy_s;
              read_v(2) := done_sticky_r;
              read_v(3) := spec_data_valid_r;
              read_v(4) := protocol_error_r;
              read_v(5) := pcm_valid_r;
              read_v(6) := spec_pending_r;
            when REG_PCM_INDEX =>
              read_v(10 downto 0) := std_logic_vector(pcm_next_index_r);
            when REG_PCM_DATA =>
              read_v(15 downto 0) := std_logic_vector(pcm_issue_data_r);
            when REG_SPEC_INDEX =>
              read_v(9 downto 0) := std_logic_vector(spec_next_index_r);
            when REG_SPEC_DATA =>
              read_v := std_logic_vector(spec_data_r);
            when REG_MDCT_EXP =>
              read_v(4 downto 0) := std_logic_vector(mdct_exp_s);
            when REG_ID =>
              read_v := x"4D444354"; -- ASCII "MDCT"
            when REG_PCM_COUNT =>
              read_v(11 downto 0) := std_logic_vector(to_unsigned(pcm_count_r, 12));
            when others =>
              null;
          end case;
          rdata_r <= read_v;
          rvalid_r <= '1';
        end if;
      end if;
    end if;
  end process;
end architecture rtl;
