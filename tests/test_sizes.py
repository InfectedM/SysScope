from sysscope.common.sizes import parse_size


def test_iec_and_si():
    assert parse_size("1KiB") == 1024
    assert parse_size("1MiB") == 1024 ** 2
    assert parse_size("1GiB") == 1024 ** 3
    assert parse_size("1kB") == 1000
    assert parse_size("1MB") == 1_000_000
    assert parse_size("1GB") == 1_000_000_000


def test_decimals_and_bytes():
    assert parse_size("308.9MiB") == round(308.9 * 1024 ** 2, 6)
    assert parse_size("126B") == 126
    assert parse_size("0B") == 0.0


def test_garbage_is_zero():
    assert parse_size("") == 0.0
    assert parse_size("--") == 0.0
    assert parse_size("N/A") == 0.0
