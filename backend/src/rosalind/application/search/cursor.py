"""Opaque, signed paging-token codec for online search.

A cursor is a ``base64url(payload) + "." + base64url(hmac)`` token. The payload
binds the token to one account and one index version, and carries the decoded
``Cursor`` (fingerprint + a window offset or list position). ``decode`` verifies
the signature, the account, and the index version; the caller (Prepare) then
compares the cursor's fingerprint against the completed plan.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime

from rosalind.application.search.plan import Cursor, ListPosition
from rosalind.application.search.ports import CursorDecodeError

__all__ = ["HmacCursorCodec"]


class HmacCursorCodec:
    """HMAC-SHA256 cursor codec with a caller-supplied signing key."""

    def __init__(self, key: bytes):
        if not key:
            raise ValueError("cursor signing key must not be empty")
        self._key = key

    def encode(
        self,
        cursor: Cursor,
        *,
        account_id: uuid.UUID,
        index_version: str,
    ) -> str:
        data = _encode_payload(
            {
                "account": str(account_id),
                "index_version": index_version,
                "fingerprint": cursor.fingerprint,
                "window_offset": cursor.window_offset,
                "list_position": _encode_list_position(cursor.list_position),
            }
        )
        return f"{_b64(data)}.{_b64(self._sign(data))}"

    def decode(
        self,
        token: str,
        *,
        account_id: uuid.UUID,
        index_version: str,
    ) -> Cursor:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            data = _unb64(payload_b64)
            signature = _unb64(sig_b64)
        except ValueError as exc:
            raise CursorDecodeError("malformed cursor token") from exc

        if not hmac.compare_digest(signature, self._sign(data)):
            raise CursorDecodeError("cursor signature is invalid")

        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CursorDecodeError("malformed cursor payload") from exc

        if payload.get("account") != str(account_id):
            raise CursorDecodeError("cursor does not belong to this account")
        if payload.get("index_version") != index_version:
            raise CursorDecodeError("cursor was issued for a different index version")

        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, str):
            raise CursorDecodeError("cursor has no fingerprint")

        window_offset = payload.get("window_offset")
        list_position = _decode_list_position(payload.get("list_position"))

        try:
            return Cursor(
                fingerprint=fingerprint,
                window_offset=window_offset if isinstance(window_offset, int) else None,
                list_position=list_position,
            )
        except ValueError as exc:
            raise CursorDecodeError("malformed cursor position") from exc

    def _sign(self, data: bytes) -> bytes:
        return hmac.new(self._key, data, hashlib.sha256).digest()


def _encode_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _encode_list_position(position: ListPosition | None) -> object:
    if position is None:
        return None
    return {
        "occurred_at": position.occurred_at.isoformat(),
        "email_id": str(position.email_id),
    }


def _decode_list_position(raw: object) -> ListPosition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CursorDecodeError("list_position must be an object")
    occurred_at = raw.get("occurred_at")
    email_id = raw.get("email_id")
    if not isinstance(occurred_at, str) or not isinstance(email_id, str):
        raise CursorDecodeError("list_position is malformed")
    try:
        return ListPosition(
            occurred_at=datetime.fromisoformat(occurred_at),
            email_id=uuid.UUID(email_id),
        )
    except (ValueError, TypeError) as exc:
        raise CursorDecodeError("list_position is malformed") from exc


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise CursorDecodeError("malformed cursor token") from exc
