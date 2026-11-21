"""Tests for aula.auth.srp."""

import hashlib

from aula.auth._utils import int_to_bytes
from aula.auth.srp import _N, CustomSRP, _pad_to_n_length

N_LENGTH = len(int_to_bytes(_N))


def test_pad_to_n_length_fills_with_zero_bytes():
    assert _pad_to_n_length(b"\x01\x02") == b"\x00" * (N_LENGTH - 2) + b"\x01\x02"


def test_pad_to_n_length_fills_before_a_leading_sign_character():
    """bytes.zfill would keep + and - in front of the fill."""
    for first in (b"+", b"-"):
        assert _pad_to_n_length(first + b"\x01") == b"\x00" * (N_LENGTH - 2) + first + b"\x01"


def test_pad_to_n_length_keeps_a_full_length_value():
    value = b"\x01" * N_LENGTH
    assert _pad_to_n_length(value) == value


def test_scrambling_parameter_pads_short_keys_with_zero_bytes():
    srp = CustomSRP()
    srp._public_key = 0x0102
    srp._server_public_key = 0x0304
    padding = b"\x00" * (N_LENGTH - 2)
    digest = hashlib.sha256(padding + b"\x01\x02" + padding + b"\x03\x04").hexdigest()

    assert srp._compute_u() == int(digest, 16) % _N


def test_multiplier_pads_g_with_zero_bytes():
    padded_g = b"\x00" * (N_LENGTH - 1) + b"\x02"
    digest = hashlib.sha256(str(_N).encode() + padded_g).hexdigest()

    assert CustomSRP()._compute_little_s() == int(digest, 16)
