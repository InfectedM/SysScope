from sysscope.common.config import Disk, Config, default_config, load_config


def test_default_config_has_four_hdds():
    cfg = default_config()
    names = {d.name for d in cfg.disks}
    assert names == {"sdb", "sdc", "sdd", "sde"}


def test_default_disk_fields():
    cfg = default_config()
    sde = next(d for d in cfg.disks if d.name == "sde")
    assert sde.device == "/dev/sde"
    assert sde.mount == "/media/HDD8TB"
    assert (sde.major, sde.minor) == (8, 64)


def test_default_paths_and_intervals():
    cfg = default_config()
    assert cfg.db_path == "/var/lib/sysscope/sysscope.db"
    assert cfg.web_host == "127.0.0.1"
    assert cfg.web_port == 8787
    assert cfg.sample_interval > 0
    assert cfg.retention_days == 14


def test_load_config_falls_back_to_default(tmp_path):
    cfg = load_config(str(tmp_path / "missing.toml"))
    assert cfg.web_port == 8787


def test_load_config_overrides_from_toml(tmp_path):
    p = tmp_path / "sysscope.toml"
    p.write_text('[web]\nport = 9999\n')
    cfg = load_config(str(p))
    assert cfg.web_port == 9999
