import hashlib
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash("constant-time-unknown-user-placeholder")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RateLimiter:
    """Single-process protection. Replace with shared storage before multiple workers."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.entries: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str) -> None:
        now = monotonic()
        with self.lock:
            stale = [k for k, values in self.entries.items() if values[-1] <= now - self.window]
            for item in stale:
                del self.entries[item]
            attempts = self.entries[key]
            if len(attempts) >= self.limit:
                raise HTTPException(
                    429,
                    {"code": "rate_limited", "message": "操作过于频繁，请稍后再试"},
                    headers={"Retry-After": str(self.window)},
                )
            attempts.append(now)
