"""Per-username access tokens.

There are no accounts here — a Letterboxd username is just a string anyone can
type. The first import for a username *claims* it and mints a token; every later
read or write for that username has to present the token back. That is the whole
model: it stops a stranger reading your taste profile or overwriting your import,
without needing passwords, email, or a session store.

Only the SHA-256 of a token is stored, so a leaked database does not hand over
working tokens.
"""
import hashlib
import secrets

TOKEN_HEADER = "X-Access-Code"

def mint_token() -> str:
    """A fresh access code. 32 bytes url-safe — long enough that guessing is not
    a threat model, short enough to paste into a second browser."""
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def token_matches(token: str | None, stored_hash: str | None) -> bool:
    """Constant-time compare, so a wrong code cannot be narrowed down by timing."""
    if not token or not stored_hash:
        return False
    return secrets.compare_digest(hash_token(token), stored_hash)
