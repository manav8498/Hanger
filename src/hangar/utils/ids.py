from __future__ import annotations

import secrets
import time

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    return f"{prefix}_{_ulid()}"


def _ulid() -> str:
    timestamp_ms = int(time.time() * 1000)
    random_bits = secrets.randbits(80)
    value = (timestamp_ms << 80) | random_bits
    chars: list[str] = []

    for shift in range(125, -1, -5):
        chars.append(CROCKFORD[(value >> shift) & 31])

    return "".join(chars)
