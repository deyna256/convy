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
    assert await Patience(first=0.01).call(service.request, Places(1)) == "done"
    assert 0.1 <= service.times[1] - service.times[0] < 0.2


async def test_without_a_wait_asked_the_waits_stay_within_a_window_up_to_longest():
    service = Service(*[Busy("503")] * 6)
    assert await Patience(first=0.01, longest=0.04).call(service.request, Places(1)) == "done"
    gaps = [later - earlier for earlier, later in pairwise(service.times)]
    assert len(gaps) == 6
    assert max(gaps) < 0.04 + 0.02  # a little for the event loop


async def test_a_service_still_busy_when_the_time_is_up_is_busy():
    service = Service(*[Busy("503")] * 100)
    patience = Patience(seconds=0.1, first=0.02, longest=0.02)
    start = time.monotonic()
    with pytest.raises(Busy, match=re.escape("503; still busy, and convy waits up to 0.1 s")):
        await patience.call(service.request, Places(1))
    assert time.monotonic() - start < 0.2


async def test_a_wait_longer_than_the_time_left_gives_up_at_once():
    service = Service(Busy("429", 600))
    with pytest.raises(Busy) as busy:
        await Patience(seconds=1).call(service.request, Places(1))
    assert busy.value.retry_after == 600
    assert len(service.times) == 1


async def test_a_busy_service_halves_the_places_and_answers_bring_them_back():
    places = Places(8)
    for allowed in (4, 2, 1, 1):
        places.busy()
        assert places.allowed == allowed
    for _ in range(1 + 2 + 3):  # one more place after as many answers as there are
        places.answered()
    assert places.allowed == 4
    for _ in range(100):
        places.answered()
    assert places.allowed == 8


async def test_no_more_requests_go_than_the_places_allowed():
    places = Places(4)
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
    places = Places(1)
    told, other = Service(Busy("429", 0.2)), Service()

    async def placed(service: Service) -> str:
        async with places:
            return await service.request()

    async def later() -> str:
        await asyncio.sleep(0.05)  # sent while the first waits to try again
        return await Patience(first=0.01).call(lambda: placed(other), places)

    await asyncio.gather(Patience(first=0.01).call(lambda: placed(told), places), later())
    assert other.times[0] < told.times[1]


async def test_patience_tells_the_places_how_the_service_answered():
    places = Places(8)
    service = Service(Busy("429", 0.01), Busy("429", 0.01))
    assert await Patience(first=0.01).call(service.request, places) == "done"
    assert places.allowed == 2  # halved twice; one answer is not yet two
    for _ in range(2):
        await Patience().call(service.request, places)
    assert places.allowed == 3
