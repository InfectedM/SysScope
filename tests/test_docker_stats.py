from sysscope.collector.docker_stats import (
    ContainerStat, parse_docker_stats, read_container_stats,
)

SAMPLE = (
    "radarr|0.11%|202.1MiB / 19.21GiB|182MB / 99.3MB|742MB / 1.08GB\n"
    "bazarr|0.20%|308.9MiB / 19.21GiB|133MB / 14.5MB|839MB / 318MB\n"
)


def test_parse_basic():
    stats = parse_docker_stats(SAMPLE)
    assert len(stats) == 2
    r = stats[0]
    assert r.name == "radarr"
    assert r.cpu_pct == 0.11
    assert r.mem_used == round(202.1 * 1024 ** 2, 6)
    assert r.blk_read == 742 * 1000 ** 2
    assert r.blk_write == 1.08 * 1000 ** 3


def test_parse_ignores_malformed_lines():
    assert parse_docker_stats("linha-má\n\n") == []


def test_read_returns_empty_on_failure():
    def boom(argv):
        raise RuntimeError("docker em falta")
    assert read_container_stats(runner=boom) == []
