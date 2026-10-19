import asyncio
import re
import time
from itertools import pairwise

import pytest

from convy.busy import Busy, Patience, Places


class Service:
    """A service that refuses its first requests as busy, then answers; it keeps when each request
    came."""

    def __init__(self, *refusals: Busy):
        self.refusals = list(refusals)
        self.times: list[float] = []

    async def request(self) -> str:
        self.times.append(time.monotonic())
        if self.refusals:
            raise self.refusals.pop(0)
        return "done"


async def test_a_request_waits_at_least_as_long_as_the_service_asks():
    service = Service(Busy("429", 0.1))
    assert await Places(1, Patience(first=0.01)).retry(service.request) == "done"
    assert 0.1 <= service.times[1] - service.times[0] < 0.2


async def test_without_a_wait_asked_the_waits_stay_within_a_window_up_to_longest():
    service = Service(*[Busy("503")] * 6)
    assert await Places(1, Patience(first=0.01, longest=0.04)).retry(service.request) == "done"
    gaps = [later - earlier for earlier, later in pairwise(service.times)]
    assert len(gaps) == 6
    assert max(gaps) < 0.04 + 0.02  # a little for the event loop


async def test_a_service_still_busy_when_the_time_is_up_is_busy():
    service = Service(*[Busy("503")] * 100)
    places = Places(1, Patience(seconds=0.1, first=0.02, longest=0.02))
    start = time.monotonic()
    with pytest.raises(Busy, match=re.escape("503; still busy, and convy waits up to 0.1 s")):
        await places.retry(service.request)
    assert time.monotonic() - start < 0.2


async def test_a_wait_longer_than_the_time_left_gives_up_at_once():
    service = Service(Busy("429", 600))
    with pytest.raises(Busy) as busy:
        await Places(1, Patience(seconds=1)).retry(service.request)
    assert busy.value.retry_after == 600
    assert len(service.times) == 1


async def test_a_busy_service_halves_the_places_and_answers_bring_them_back():
    places = Places(8, Patience())
    for allowed in (4, 2, 1, 1):
        places.busy()
        assert places.allowed == allowed
    for _ in range(1 + 2 + 3):  # one more place after as many answers as there are
        await places.answered()
    assert places.allowed == 4
    for _ in range(100):
        await places.answered()
    assert places.allowed == 8


async def test_no_more_requests_go_than_the_places_allowed():
    places = Places(4, Patience())
    places.busy()
    entered = 0

    async def enter() -> None:
        nonlocal entered
        async with places:
            entered += 1
            await asyncio.sleep(1)

    tasks = [asyncio.create_task(enter()) for _ in range(3)]
    await asyncio.sleep(0.05)
    assert entered == 2
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert places.taken == 0  # a cancelled request gives its place back


async def test_a_request_holds_no_place_while_it_waits():
    places = Places(1, Patience(first=0.01))
    told, other = Service(Busy("429", 0.2)), Service()

    async def later() -> str:
        await asyncio.sleep(0.05)  # sent while the first waits to try again
        return await places.call(other.request)

    await asyncio.gather(places.call(told.request), later())
    assert other.times[0] < told.times[1]


async def test_retries_tell_the_places_how_the_service_answered():
    places = Places(8, Patience(first=0.01))
    service = Service(Busy("429", 0.01), Busy("429", 0.01))
    assert await places.retry(service.request) == "done"
    assert places.allowed == 2  # halved twice; one answer is not yet two
    for _ in range(2):
        await places.retry(service.request)
    assert places.allowed == 3


async def test_a_place_that_comes_back_lets_a_waiting_request_in_at_once():
    places = Places(2, Patience())
    places.busy()  # one place left
    entered = asyncio.Event()

    async def holding() -> None:
        async with places:
            await asyncio.sleep(1)

    async def waiting() -> None:
        async with places:
            entered.set()

    holder = asyncio.create_task(holding())
    waiter = asyncio.create_task(waiting())
    await asyncio.sleep(0.01)
    assert not entered.is_set()
    await places.retry(Service().request)  # an answer brings the second place back
    await asyncio.wait_for(entered.wait(), 0.1)
    holder.cancel()
    await asyncio.gather(holder, waiter, return_exceptions=True)


async def test_without_a_wait_asked_convy_keeps_trying_until_the_time_is_up():
    places = Places(1, Patience(seconds=0.3, first=0.3, longest=0.3))
    service = Service(*[Busy("503")] * 1000)
    start = time.monotonic()
    with pytest.raises(Busy):
        await places.retry(service.request)
    assert 0.28 <= time.monotonic() - start < 0.4  # a random wait is cut to the time left
