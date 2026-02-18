"""Tests for aula.auth._utils."""

from aula.auth._utils import bytes_to_hex, hex_to_int, int_to_bytes


def test_int_to_bytes_small():
    assert int_to_bytes(0xFF) == b"\xff"


def test_int_to_bytes_multi_byte():
    assert int_to_bytes(0x0100) == b"\x01\x00"


def test_int_to_bytes_large():
    result = int_to_bytes(0xDEADBEEF)
    assert result == b"\xde\xad\xbe\xef"
    assert len(result) == 4


def test_hex_to_int():
    assert hex_to_int("ff") == 255
    assert hex_to_int("100") == 256


def test_hex_to_int_uppercase():
    assert hex_to_int("FF") == 255
    assert hex_to_int("DeAd") == 0xDEAD


def test_bytes_to_hex():
    assert bytes_to_hex(b"\xde\xad") == "dead"
    assert bytes_to_hex(b"") == ""


def test_bytes_to_hex_single():
    assert bytes_to_hex(b"\x0a") == "0a"


def test_roundtrip_int_bytes():
    original = 123456789
    b = int_to_bytes(original)
    assert int.from_bytes(b, "big") == original


def test_roundtrip_hex_int():
    assert hex_to_int(bytes_to_hex(int_to_bytes(42))) == 42
