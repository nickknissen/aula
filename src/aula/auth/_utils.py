"""Shared utility functions for the auth module."""

import binascii


def int_to_bytes(x: int) -> bytes:
    """Convert a positive integer to big-endian bytes."""
    return x.to_bytes((x.bit_length() + 7) // 8, "big")


def hex_to_int(x: str) -> int:
    """Convert a hex string to an integer."""
    return int(x, 16)


def bytes_to_hex(x: bytes) -> str:
    """Convert bytes to a hex string."""
    return binascii.hexlify(x).decode("utf-8")
