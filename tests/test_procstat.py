from sysscope.collector import procstat


def test_read_top_processes_shape():
    procs = procstat.read_top_processes(limit=5)
    assert isinstance(procs, list)
    assert len(procs) <= 5
    if procs:
        p = procs[0]
        for k in ("pid", "name", "cpu_percent", "mem_bytes",
                  "read_bytes", "write_bytes"):
            assert k in p
    # ordenado por cpu desc
    cpus = [p["cpu_percent"] for p in procs]
    assert cpus == sorted(cpus, reverse=True)
