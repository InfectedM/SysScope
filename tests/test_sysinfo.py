from sysscope.collector import sysinfo


def test_read_system_shape():
    d = sysinfo.read_system()
    for k in ("cpu_percent", "load", "mem_total", "mem_used", "mem_percent",
              "swap_total", "swap_used", "uptime_seconds", "temps", "cpu_count"):
        assert k in d
    assert isinstance(d["load"], list) and len(d["load"]) == 3
    assert isinstance(d["temps"], dict)
    assert d["mem_total"] > 0
    assert d["cpu_count"] >= 1
