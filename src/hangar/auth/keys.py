from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from hangar.utils.ids import new_id

_HASHER = PasswordHasher()


@dataclass(frozen=True)
class CreatedApiKey:
    id: str
    raw_key: str
    hashed_key: str


def create_api_key(name: str) -> CreatedApiKey:
    del name
    raw_key = f"hgr_{secrets.token_urlsafe(32)}"
    return CreatedApiKey(
        id=new_id("key"),
        raw_key=raw_key,
        hashed_key=_HASHER.hash(raw_key),
    )


def verify_api_key(raw_key: str, hashed_key: str) -> bool:
    try:
        return _HASHER.verify(hashed_key, raw_key)
    except VerifyMismatchError:
        return False
