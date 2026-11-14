"""Transport guards shared by every generated API route."""

import json

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class JsonNulGuardMiddleware:
    """Reject JSON bodies containing NUL bytes with 422 instead of a DB error.

    PostgreSQL text columns cannot store NUL; catching it at the HTTP boundary
    keeps malformed client input out of the database and out of 500 responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _location_has_nul(scope):
            response = JSONResponse(
                {"detail": "NUL bytes are not allowed in request paths or queries"},
                status_code=422,
            )
            await response(scope, receive, send)
            return
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if "application/json" not in headers.get("content-type", "").lower():
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        if b"\x00" in body or _contains_nul(parsed):
            response = JSONResponse(
                {"detail": "NUL bytes are not allowed in JSON requests"},
                status_code=422,
            )
            await response(scope, receive, send)
            return

        delivered = False

        async def replay() -> dict:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, replay, send)


def _contains_nul(value: object) -> bool:
    """True when a parsed JSON value contains a NUL in any string key/value."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, list):
        return any(_contains_nul(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_nul(key) or _contains_nul(item) for key, item in value.items())
    return False


def _location_has_nul(scope: Scope) -> bool:
    if "\x00" in scope.get("path", ""):
        return True
    query = scope.get("query_string", b"")
    return b"\x00" in query or b"%00" in query.lower()
