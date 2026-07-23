from sysscope.collector.connections import Connection, parse_ss, read_connections

SAMPLE = (
    'tcp   ESTAB 0 0 192.168.1.72:8989 172.19.0.7:49510 users:(("sonarr",pid=1234,fd=20))\n'
    'udp   UNCONN 0 0 192.168.1.72%wlp1s0:68 192.168.1.254:67 \n'
    'tcp   ESTAB 0 0 192.168.1.72:443 2.80.171.105:53504 users:(("jellyfin",pid=3181,fd=44))\n'
)


def test_parse_with_process():
    conns = parse_ss(SAMPLE)
    assert len(conns) == 3
    c = conns[0]
    assert c.proto == "tcp" and c.state == "ESTAB"
    assert c.local == "192.168.1.72:8989" and c.remote == "172.19.0.7:49510"
    assert c.process == "sonarr" and c.pid == 1234


def test_parse_without_process():
    c = parse_ss(SAMPLE)[1]
    assert c.proto == "udp" and c.process is None and c.pid is None


def test_read_empty_on_failure():
    def boom(argv):
        raise RuntimeError("ss em falta")
    assert read_connections(runner=boom) == []
