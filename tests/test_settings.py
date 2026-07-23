import json
import pytest
from sysscope.web import settings as s


def test_default_when_missing(tmp_path):
    assert s.read_bind_mode(str(tmp_path / "nope.json")) == "localhost"


def test_roundtrip(tmp_path):
    p = str(tmp_path / "w.json")
    s.write_bind_mode(p, "lan")
    assert s.read_bind_mode(p) == "lan"
    assert json.loads(open(p).read())["bind_mode"] == "lan"


def test_corrupt_file_defaults_localhost(tmp_path):
    p = tmp_path / "bad.json"; p.write_text("{lixo")
    assert s.read_bind_mode(str(p)) == "localhost"


def test_invalid_stored_value_defaults_localhost(tmp_path):
    p = tmp_path / "x.json"; p.write_text('{"bind_mode": "0.0.0.0"}')
    assert s.read_bind_mode(str(p)) == "localhost"


def test_write_rejects_invalid_mode(tmp_path):
    with pytest.raises(ValueError):
        s.write_bind_mode(str(tmp_path / "z.json"), "wan")


def test_host_for_mode():
    assert s.host_for_mode("localhost") == "127.0.0.1"
    assert s.host_for_mode("lan") == "0.0.0.0"
    assert s.host_for_mode("qualquer") == "127.0.0.1"  # fail-safe


def test_lan_addresses_is_list_without_loopback():
    addrs = s.lan_ipv4_addresses()
    assert isinstance(addrs, list)
    assert "127.0.0.1" not in addrs
