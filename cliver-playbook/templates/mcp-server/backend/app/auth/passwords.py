"""Password hashing: PBKDF2-SHA256 with per-hash salt and iteration count.

Format: `pbkdf2_sha256$<iterations>$<salt-hex>$<dk-hex>`.

Why PBKDF2 (and not bcrypt/argon2): it ships in the standard library — zero
native dependencies, which keeps the template portable onto any host a small
service lands on. The iteration count is embedded in every stored hash, so
raising the work factor later re-hashes transparently on next successful
login (call `needs_rehash` there and update the stored row).

All functions here are pure CPU work and synchronous. Async callers must use
the `a*` wrappers, which push the work onto a worker thread so the event loop
is never blocked (ADR-0001 consequence).
"""

import asyncio
import hashlib
import hmac
import secrets

# OWASP 2023 guidance for PBKDF2-SHA256 is 600k; 200k keeps login at ~50ms on a
# modest VPS while still far beyond brute-force reach for online attacks, which
# the lockout counter already throttles.
ITERATIONS = 200_000
_SALT_BYTES = 16
_DK_BYTES = 32


def hash_password(plain: str) -> str:
    """Hash a plaintext password into the storable format."""
    salt = secrets.token_hex(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", plain.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time check of a plaintext candidate against a stored hash.

    Returns False for malformed stored values (e.g. the `""` used to mark
    OIDC-only accounts) instead of raising — a bad stored hash must never
    turn a login attempt into a 500.
    """
    try:
        scheme, iterations_s, salt_hex, dk_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", plain.encode(), bytes.fromhex(salt_hex), iterations
        )
        return hmac.compare_digest(candidate.hex(), dk_hex)
    except (ValueError, AttributeError):
        return False


def needs_rehash(stored: str) -> bool:
    """True when the stored hash was made with fewer iterations than current.

    Call after a successful login and re-store `hash_password(plain)` — that is
    the only moment the plaintext is available.
    """
    try:
        return int(stored.split("$")[1]) < ITERATIONS
    except (ValueError, IndexError):
        return True


async def ahash_password(plain: str) -> str:
    """Async wrapper — PBKDF2 is CPU-bound; keep it off the event loop."""
    return await asyncio.to_thread(hash_password, plain)


async def averify_password(plain: str, stored: str) -> bool:
    """Async wrapper — see `ahash_password`."""
    return await asyncio.to_thread(verify_password, plain, stored)
