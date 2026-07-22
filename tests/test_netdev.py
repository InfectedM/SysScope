from sysscope.collector.netdev import NetStat, parse_net_dev, net_rates

SAMPLE = (
    "Inter-|   Receive                                                |  Transmit\n"
    " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
    "    lo:  12345      10    0    0    0     0          0         0    12345      10    0    0    0     0       0          0\n"
    "  eno1: 1000000    500    0    0    0     0          0         0  2000000     600    0    0    0     0       0          0\n"
)


def test_parse_skips_loopback_by_default():
    d = parse_net_dev(SAMPLE)
    assert "lo" not in d
    assert d["eno1"] == NetStat(rx_bytes=1000000, tx_bytes=2000000)


def test_parse_can_include_loopback():
    d = parse_net_dev(SAMPLE, skip_loopback=False)
    assert d["lo"].rx_bytes == 12345


def test_net_rates():
    prev = NetStat(1000, 2000); curr = NetStat(3000, 6000)
    rx, tx = net_rates(prev, curr, dt=2.0)
    assert rx == 1000.0 and tx == 2000.0


def test_net_rates_zero_dt():
    assert net_rates(NetStat(1, 1), NetStat(2, 2), 0.0) == (0.0, 0.0)
