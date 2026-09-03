import re

class Cancelled(Exception):
    """Raised when a refresh run is cancelled mid-flight by the user."""

# requests puts the full request URL in its HTTPError message, and TMDB/OMDB
# take the key as a *query parameter* — so an upstream 401 or 404 turns
# str(exc) into a message containing a live API key. That message is surfaced to
# the browser as refresh progress, which would publish the key to anyone who can
# reach the endpoint. Redact before anything user-facing sees it.
_SECRET_QUERY_PARAM = re.compile(
    r"((?:api_?key|apikey|access_token|token|session_id|password)=)[^&\s\"']+",
    re.IGNORECASE)

MAX_MESSAGE_CHARS = 300

def safe_message(exc: BaseException | str) -> str:
    """An exception rendered for display to an untrusted client: secrets in URLs
    replaced, length capped so a huge upstream body cannot be echoed back."""
    text = exc if isinstance(exc, str) else str(exc)
    text = _SECRET_QUERY_PARAM.sub(r"\1[redacted]", text)
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "…"
    return text
