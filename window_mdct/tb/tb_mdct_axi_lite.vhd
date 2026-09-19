-- Full golden regression through the actual AXI wrapper. Vary AW/W ordering
-- and stall B/R responses to exercise independent channels and backpressure.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use ieee.std_logic_textio.all;
use std.textio.all;
use std.env.all;

entity tb_mdct_axi_lite is
  generic (GOLDEN_DIR : string := "my_workspace/window_mdct/golden/radix2_q31_v1");
end entity;

architecture sim of tb_mdct_axi_lite is
  signal clk : std_logic := '0';
  signal resetn : std_logic := '0';
  signal leds : std_logic_vector(3 downto 0);
  signal awaddr, araddr : std_logic_vector(5 downto 0) := (others => '0');
  signal wdata, rdata : std_logic_vector(31 downto 0) := (others => '0');
  signal wstrb : std_logic_vector(3 downto 0) := "1111";
  signal awvalid, awready, wvalid, wready, bvalid, bready : std_logic := '0';
  signal arvalid, arready, rvalid, rready : std_logic := '0';
  signal bresp, rresp : std_logic_vector(1 downto 0);
  type modes_t is array (0 to 5) of natural;
  constant BLOCKS : modes_t := (0, 0, 1, 2, 3, 0);
  constant SHAPES : modes_t := (0, 1, 0, 1, 0, 1);
begin
  clk <= not clk after 10 ns;
  dut : entity work.mdct_axi_lite port map (
    status_led => leds, s_axi_aclk => clk, s_axi_aresetn => resetn,
    s_axi_awaddr => awaddr, s_axi_awprot => "000", s_axi_awvalid => awvalid,
    s_axi_awready => awready, s_axi_wdata => wdata, s_axi_wstrb => wstrb,
    s_axi_wvalid => wvalid, s_axi_wready => wready, s_axi_bresp => bresp,
    s_axi_bvalid => bvalid, s_axi_bready => bready, s_axi_araddr => araddr,
    s_axi_arprot => "000", s_axi_arvalid => arvalid, s_axi_arready => arready,
    s_axi_rdata => rdata, s_axi_rresp => rresp, s_axi_rvalid => rvalid,
    s_axi_rready => rready
  );

  watchdog : process
  begin
    wait for 100 ms;
    assert false report "AXI regression watchdog expired" severity failure;
    wait;
  end process;

  stimulus : process
    file pcm_file : text open read_mode is GOLDEN_DIR & "/pcm_in_s16.txt";
    file expected_file : text open read_mode is GOLDEN_DIR & "/mdct_out_q31.txt";
    variable line_v : line;
    variable case_v, frame_v, index_v, exp_v : integer;
    variable pcm_v : std_logic_vector(15 downto 0);
    variable expected_v, value_v : std_logic_vector(31 downto 0);
    variable config_v : natural;
    variable write_number : natural := 0;

    procedure axi_write(address : natural; data : std_logic_vector(31 downto 0);
                        strobes : std_logic_vector(3 downto 0) := "1111") is
      variable aw_done, w_done : boolean := false;
      variable aw_delay, w_delay : natural := 0;
    begin
      if write_number mod 3 = 0 then aw_delay := 3;
      elsif write_number mod 3 = 1 then w_delay := 3;
      end if;
      write_number := write_number + 1;
      for cycle in 0 to 30 loop
        wait until falling_edge(clk);
        awaddr <= std_logic_vector(to_unsigned(address, 6));
        wdata <= data;
        wstrb <= strobes;
        if not aw_done and cycle >= aw_delay then awvalid <= '1';
        else awvalid <= '0'; end if;
        if not w_done and cycle >= w_delay then wvalid <= '1';
        else wvalid <= '0'; end if;
        wait until rising_edge(clk);
        if awvalid = '1' and awready = '1' then aw_done := true; awvalid <= '0'; end if;
        if wvalid = '1' and wready = '1' then w_done := true; wvalid <= '0'; end if;
        exit when aw_done and w_done;
      end loop;
      assert aw_done and w_done report "AXI AW/W timeout" severity failure;
      for cycle in 0 to 30 loop
        wait until rising_edge(clk);
        exit when bvalid = '1';
      end loop;
      assert bvalid = '1' and bresp = "00" report "AXI write response error" severity failure;
      for cycle in 1 to 3 loop
        wait until rising_edge(clk);
        assert bvalid = '1' and bresp = "00" report "B changed under backpressure" severity failure;
      end loop;
      wait until falling_edge(clk); bready <= '1';
      wait until rising_edge(clk);
      wait until falling_edge(clk); bready <= '0';
    end procedure;

    procedure write_word(address, data : natural) is
    begin
      axi_write(address, std_logic_vector(to_unsigned(data, 32)));
    end procedure;

    procedure axi_read(address : natural; variable data : out std_logic_vector(31 downto 0)) is
      variable accepted : boolean := false;
    begin
      wait until falling_edge(clk);
      araddr <= std_logic_vector(to_unsigned(address, 6)); arvalid <= '1';
      for cycle in 0 to 30 loop
        wait until rising_edge(clk);
        if arready = '1' then accepted := true; exit; end if;
      end loop;
      assert accepted report "AXI AR timeout" severity failure;
      arvalid <= '0';
      for cycle in 0 to 30 loop
        wait until rising_edge(clk);
        exit when rvalid = '1';
      end loop;
      assert rvalid = '1' and rresp = "00" report "AXI read response error" severity failure;
      data := rdata;
      for cycle in 1 to 3 loop
        wait until rising_edge(clk);
        assert rvalid = '1' and rdata = data and rresp = "00"
          report "R changed under backpressure" severity failure;
      end loop;
      wait until falling_edge(clk); rready <= '1';
      wait until rising_edge(clk);
      wait until falling_edge(clk); rready <= '0';
    end procedure;

    procedure wait_status(bit_index : natural) is
      variable status_v : std_logic_vector(31 downto 0);
    begin
      for attempt in 0 to 3000 loop
        axi_read(4, status_v);
        assert status_v(4) = '0' report "Unexpected MDCT protocol error" severity failure;
        if status_v(bit_index) = '1' then return; end if;
      end loop;
      assert false report "MDCT status timeout" severity failure;
    end procedure;
  begin
    wait for 100 ns;
    assert awready = '0' and wready = '0' and arready = '0'
      report "AXI ready must be low during reset" severity failure;
    wait until falling_edge(clk); resetn <= '1';
    axi_read(16#1c#, value_v);
    assert value_v = x"4D444354" report "Wrong MDCT ID" severity failure;

    -- Aborted writes must have no side effects, even on the read-only index.
    axi_write(12, x"00001234", "0000");
    axi_write(8, x"00000001", "0000");
    axi_read(32, value_v);
    assert unsigned(value_v) = 0 report "Zero WSTRB enqueued PCM" severity failure;
    axi_read(4, value_v);
    assert value_v(4) = '0' report "Zero WSTRB changed flags" severity failure;
    -- A PCM sample is atomic: both low bytes must be present.
    axi_write(12, x"00001234", "0001");
    axi_read(32, value_v);
    assert unsigned(value_v) = 0 report "Partial PCM write was accepted" severity failure;
    axi_read(4, value_v);
    assert value_v(4) = '1' report "Partial PCM write not rejected" severity failure;
    write_word(0, 8);
    write_word(0, 1); -- start before 2048 samples
    axi_read(4, value_v);
    assert value_v(4) = '1' and value_v(1) = '0' report "Early start accepted" severity failure;
    write_word(0, 8);
    write_word(0, 4); -- no result yet
    axi_read(4, value_v);
    assert value_v(4) = '1' report "Read of uninitialized spectrum accepted" severity failure;
    write_word(0, 8);

    -- A physical reset must clear a partial load as well as the flags/history.
    write_word(12, 123);
    wait until falling_edge(clk); resetn <= '0';
    wait for 100 ns;
    wait until falling_edge(clk); resetn <= '1';
    axi_read(32, value_v);
    assert unsigned(value_v) = 0 report "Reset did not clear partial PCM load" severity failure;

    for case_id in 0 to 2 loop
      for frame_id in 0 to 5 loop
        config_v := BLOCKS(frame_id) * 256 + SHAPES(frame_id) * 1024;
        write_word(0, config_v + 8);
        for sample in 0 to 2047 loop
          readline(pcm_file, line_v);
          read(line_v, case_v); read(line_v, frame_v); read(line_v, index_v); hread(line_v, pcm_v);
          assert case_v = case_id and frame_v = frame_id and index_v = sample
            report "Bad PCM fixture ordering" severity failure;
          axi_write(12, x"0000" & pcm_v);
        end loop;
        axi_read(32, value_v);
        assert unsigned(value_v) = 2048 report "PCM count mismatch" severity failure;
        if frame_id = 0 then write_word(0, config_v + 3);
        else write_word(0, config_v + 1); end if;
        wait_status(2);
        write_word(16, 0);
        for bin in 0 to 1023 loop
          readline(expected_file, line_v);
          read(line_v, case_v); read(line_v, frame_v); read(line_v, index_v);
          hread(line_v, expected_v); read(line_v, exp_v);
          assert case_v = case_id and frame_v = frame_id and index_v = bin
            report "Bad spectrum fixture ordering" severity failure;
          write_word(0, config_v + 4);
          wait_status(3);
          axi_read(20, value_v);
          assert value_v = expected_v
            report "AXI MDCT mismatch case=" & integer'image(case_id) &
                   " frame=" & integer'image(frame_id) & " bin=" & integer'image(bin)
            severity failure;
        end loop;
        axi_read(24, value_v);
        assert to_integer(unsigned(value_v)) = exp_v report "MDCT exponent mismatch" severity failure;
        report "PASS AXI frame case=" & integer'image(case_id) & " frame=" & integer'image(frame_id);
      end loop;
    end loop;
    assert endfile(pcm_file) and endfile(expected_file) report "Unused golden rows" severity failure;
    report "PASS: mdct_axi_lite 18 frames / 18432 bins at 0 LSB; AXI stalls and protocol checks";
    finish;
    wait;
  end process;
end architecture;
