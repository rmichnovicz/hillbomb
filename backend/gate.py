"""
In-process FIFO admission control for the expensive elevation-fetch stage.

Cold elevation fetches (3DEP/SRTM tile reads over HTTP) are the pipeline's
slowest step and the one that most easily overwhelms the box when many searches
of different, uncached areas land at once. This gate caps how many run
concurrently and holds the rest in an arrival-ordered line, reporting each
waiter's position so the pipeline can stream it to the client over SSE.

Warm searches never touch this gate — the pipeline probes the elevation cache
first (ElevationService.missing_coords) and only enters the line when there's
real fetching to do.

Single-process only: the queue lives in this worker's event loop. Run the app
with one uvicorn worker (or move this to Redis) if you scale out. All state is
mutated only from synchronous, await-free methods, so within one event loop the
coroutines can't interleave mid-update and no locking is needed.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import AsyncGenerator


class Ticket:
    """A place in line. `admitted` flips true when the gate grants a slot;
    `changed` fires on admission or any position shift so a waiter can re-report."""

    __slots__ = ("admitted", "changed")

    def __init__(self) -> None:
        self.admitted = False
        self.changed = asyncio.Event()


class RequestGate:
    def __init__(self, max_concurrent: int, max_waiting: int) -> None:
        self._max = max_concurrent
        self._max_waiting = max_waiting
        self._active = 0
        self._q: deque[Ticket] = deque()

    def enqueue(self) -> Ticket | None:
        """Take a ticket. Admitted immediately if a slot is free and no one is
        already waiting (FIFO — never jump the line); otherwise queued.

        Returns None when the line is already at `max_waiting` — the caller
        should shed the request (tell the client we're at capacity) rather than
        let the backlog grow without bound."""
        t = Ticket()
        if self._active < self._max and not self._q:
            self._active += 1
            t.admitted = True
            t.changed.set()
            return t
        if len(self._q) >= self._max_waiting:
            return None
        self._q.append(t)
        return t

    def position(self, t: Ticket) -> int:
        """1-based place in line (1 = next up). 0 once admitted / not waiting."""
        try:
            return self._q.index(t) + 1
        except ValueError:
            return 0

    def release(self, t: Ticket) -> None:
        """Give up the ticket — release the held slot, or drop from the line if
        still waiting (client disconnected). Idempotent: safe to call in finally."""
        if t.admitted:
            t.admitted = False
            self._active -= 1
            self._promote()
        elif t in self._q:
            self._q.remove(t)
            self._wake_all()  # everyone behind moves up one

    async def wait(
        self,
        t: Ticket,
        is_cancelled: Callable[[], Awaitable[bool]],
    ) -> AsyncGenerator[int, None]:
        """Yield this ticket's 1-based position whenever it changes, until the
        gate admits it. Returns (slot held) on admission; returns early without
        admission if `is_cancelled` trips — the caller releases in either case.

        `is_cancelled` reads the pipeline's shared disconnect flag rather than
        polling request.is_disconnected() here, so we don't race the lone
        disconnect watcher on the ASGI receive channel."""
        last = -1
        while not t.admitted:
            if await is_cancelled():
                return
            pos = self.position(t)
            if pos != last:
                yield pos
                last = pos
            # Clear-then-recheck closes most of the set/clear race; the 1s
            # timeout is a backstop so a missed signal costs at most a second.
            t.changed.clear()
            if t.admitted:
                break
            try:
                await asyncio.wait_for(t.changed.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    def _promote(self) -> None:
        while self._q and self._active < self._max:
            nxt = self._q.popleft()
            self._active += 1
            nxt.admitted = True
            nxt.changed.set()
        self._wake_all()

    def _wake_all(self) -> None:
        for t in self._q:
            t.changed.set()
