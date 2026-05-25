"""In-memory ring buffer of structured log entries.

Powers the Admin Logs page (recent fetch + live SSE stream). Captures
every record emitted through Python's standard logging machinery via a
custom handler installed at process startup.

Design choices:
- Fixed-size deque so memory is bounded regardless of activity.
- Monotonically increasing `seq` lets the browser dedupe between the
  initial back-fill and the SSE stream.
- An asyncio.Queue per subscriber; we never block the producer if a
  consumer is slow — we just drop the oldest event in their queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque


# uvicorn.access emits messages shaped like:
#   '172.19.0.1:38256 - "GET /api/health HTTP/1.1" 200 OK'
# We split that into structured fields so the UI can render IP / method /
# path / status / protocol as separate columns instead of one opaque line.
_ACCESS_RE = re.compile(
    r'^(?P<client>\S+)\s+-\s+"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+(?P<proto>HTTP/\d\.\d)"\s+(?P<status>\d+)'
)

# Bounded ring. 5k entries ≈ a few MB max; bump via env if needed.
_RING_CAPACITY = int(os.environ.get("LOG_RING_CAPACITY", "5000"))
_ring: Deque[dict] = deque(maxlen=_RING_CAPACITY)
_seq = 0
_subscribers: list[asyncio.Queue] = []


def _record_to_dict(record: logging.LogRecord) -> dict[str, Any]:
    """Convert a stdlib LogRecord into the wire shape consumed by the UI."""
    global _seq
    _seq += 1

    # Stable, ISO-8601 timestamp. Local TZ would surprise users running the
    # API in a different timezone than their browser; stick to UTC and let
    # the frontend localize.
    ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

    # Standard fields go up top; everything else (the structured payload)
    # gets pushed into `fields` so the UI can render them as key/value rows.
    #
    # `message` and `asctime` aren't on the bare LogRecord skeleton but get
    # added by other handlers' formatters that run before us on the same
    # logger (e.g. uvicorn's StreamHandler) — exclude them explicitly so
    # they don't pollute the structured fields with the same string the UI
    # already shows as `event`.
    base_keys = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__.keys())
    base_keys.update({"message", "asctime", "color_message", "scope"})
    extras: dict[str, Any] = {}
    for k, v in record.__dict__.items():
        if k in base_keys or k.startswith("_"):
            continue
        # JSON-encode non-serializable values so the SSE stream never breaks.
        try:
            json.dumps(v)
            extras[k] = v
        except Exception:
            extras[k] = repr(v)

    if record.exc_info:
        try:
            import traceback
            extras["traceback"] = "".join(traceback.format_exception(*record.exc_info))
        except Exception:
            pass

    event = record.getMessage()

    # Promote uvicorn.access lines into structured fields so the UI can show
    # IP / method / path / status as its own columns. The raw line stays
    # available as `event` for grep-style searches, but a friendlier label
    # is set on the event to keep the list scannable.
    if record.name == "uvicorn.access":
        m = _ACCESS_RE.match(event)
        if m:
            extras["ip"] = m.group("client").split(":", 1)[0]  # drop ephemeral port
            extras["method"] = m.group("method")
            extras["path"] = m.group("path")
            extras["status"] = int(m.group("status"))
            extras["proto"] = m.group("proto")
            event = f'{m.group("method")} {m.group("path")} → {m.group("status")}'

    return {
        "seq": _seq,
        "ts": ts,
        "level": record.levelname.lower(),
        "event": event,
        "logger": record.name,
        "fields": extras,
    }


class RingHandler(logging.Handler):
    """Installs into the root logger and captures everything."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            entry = _record_to_dict(record)
        except Exception:
            return
        _ring.append(entry)
        # Fan out to live subscribers without ever blocking the logger.
        for q in list(_subscribers):
            try:
                if q.full():
                    # Drop the oldest event for that subscriber rather than
                    # the producer. Keeps the live stream responsive.
                    try: q.get_nowait()
                    except asyncio.QueueEmpty: pass
                q.put_nowait(entry)
            except Exception:
                # Don't let a broken subscriber bring down logging.
                try: _subscribers.remove(q)
                except ValueError: pass


def install() -> None:
    """Idempotently install the ring handler on the root logger AND on the
    uvicorn loggers (their default config sets propagate=False, so without
    explicit attachment we'd miss every HTTP request).
    """
    handler = RingHandler()
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    if not any(isinstance(h, RingHandler) for h in root.handlers):
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)

    # uvicorn's "uvicorn", "uvicorn.access" and "uvicorn.error" loggers
    # use their own handlers and `propagate=False`. Attach the ring handler
    # to each so the Admin Logs page can see HTTP activity.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        if not any(isinstance(h, RingHandler) for h in lg.handlers):
            lg.addHandler(handler)
        if lg.level == logging.NOTSET:
            lg.setLevel(logging.INFO)


def recent(limit: int = 2000) -> dict:
    """Return up to `limit` newest entries plus the current high-water seq."""
    limit = max(1, min(limit, _RING_CAPACITY))
    items = list(_ring)[-limit:]
    last = items[-1]["seq"] if items else 0
    return {"items": items, "last_seq": last}


def subscribe(maxsize: int = 256) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try: _subscribers.remove(q)
    except ValueError: pass


def heartbeat_payload() -> str:
    """Comment line clients ignore, used to keep the SSE connection alive
    through middleboxes that close idle connections."""
    return f": ping {int(time.time())}\n\n"
