import json
from sysscope.collector.systemd_units import (
    Unit, parse_units, summarize, read_units,
)

SAMPLE = json.dumps([
    {"unit": "a.service", "active": "active", "sub": "running", "description": "A"},
    {"unit": "b.service", "active": "failed", "sub": "failed", "description": "B"},
    {"unit": "c.service", "active": "inactive", "sub": "dead", "description": "C"},
])


def test_parse():
    units = parse_units(SAMPLE)
    assert len(units) == 3
    assert units[0] == Unit("a.service", "active", "running", "A")


def test_summarize():
    s = summarize(parse_units(SAMPLE))
    assert s["total"] == 3
    assert s["active"] == 1
    assert s["failed"] == ["b.service"]
    assert s["counts"]["inactive"] == 1


def test_parse_bad_json():
    assert parse_units("não é json") == []


def test_read_empty_on_failure():
    def boom(argv):
        raise RuntimeError("systemctl em falta")
    assert read_units(runner=boom) == []
