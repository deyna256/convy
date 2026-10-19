"""A busy service: how its caller reports it, how many requests a participant sends to it at once,
and how long convy waits for it."""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from types import TracebackType

from msgspec import Struct


class Busy(Exception):
    """The service refused a request before acting on it, because it is busy, so the request may
    be sent again: after `retry_after` seconds, or 0 when the service did not say."""

    def __init__(self, message: str, retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class Places:
    """How many requests a participant has under way at once: up to `most`, half as many each time
    its service says it is busy, and one more again for every so many answers, as TCP and
    promptfoo find a pace a service keeps up with. Made in the event loop that waits for it."""

    def __init__(self, most: int):
        self.most = most
        self.allowed = most
        self.taken = 0
        self.answers = 0  # since the last change of `allowed`
        self.changed = asyncio.Condition()

    async def __aenter__(self) -> None:
        async with self.changed:
            await self.changed.wait_for(lambda: self.taken < self.allowed)
            self.taken += 1

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        async with self.changed:
            self.taken -= 1
            self.changed.notify_all()

    def busy(self) -> None:
        self.allowed = max(1, self.allowed // 2)
        self.answers = 0

    def answered(self) -> None:
        """One more place after as many answers as there are places now."""
        self.answers += 1
        if self.answers >= self.allowed and self.allowed < self.most:
            self.allowed += 1
            self.answers = 0


class Patience(Struct, frozen=True, kw_only=True):
    """How long a participant waits for a busy service: `seconds` in all. It waits at least as long
    as the service asks plus up to `first` more, or, when the service does not say, a random time
    up to a window that doubles from `first` to `longest`; random, so that the requests refused
    together do not come back together."""

    seconds: float = 120
    first: float = 1
    longest: float = 30

    async def call[T](self, request: Callable[[], Awaitable[T]], places: Places) -> T:
        """What `request` gives once its service is not busy, telling `places` how the service
        answered; `Busy` when the service asks for longer than is left, or is still busy when the
        time is up. A request takes its place inside `request`, so it does not hold one while it
        waits."""
        deadline = time.monotonic() + self.seconds
        window = self.first
        while True:
            try:
                answer = await request()
            except Busy as busy:
                places.busy()
                if busy.retry_after:
                    wait = busy.retry_after + random.uniform(0, self.first)
                else:
                    wait = random.uniform(0, window)
                    window = min(window * 2, self.longest)
                if time.monotonic() + wait > deadline:
                    raise Busy(
                        f"{busy}; still busy, and convy waits up to {self.seconds:g} s",
                        busy.retry_after,
                    ) from busy
                await asyncio.sleep(wait)
            else:
                places.answered()
                return answer
