"""64-bit SimHash over transcript 3-grams, for catching the same viral
format reposted by dozens of accounts with slightly different wording."""

from __future__ import annotations

import hashlib


def _ngrams(text: str, n: int = 3) -> list[str]:
    tokens = text.lower().split()
    if len(tokens) < n:
        return [" ".join(tokens)] if tokens else []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def simhash64(text: str) -> int:
    weights = [0] * 64
    for gram in _ngrams(text):
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1

    result = 0
    for bit in range(64):
        if weights[bit] > 0:
            result |= 1 << bit
    return result


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def to_sqlite_int64(value: int) -> int:
    """simhash64() returns an unsigned 64-bit value; SQLite INTEGER is
    signed 64-bit, so values >= 2**63 overflow unless converted."""
    return value - (1 << 64) if value >= (1 << 63) else value


def from_sqlite_int64(value: int) -> int:
    return value + (1 << 64) if value < 0 else value
