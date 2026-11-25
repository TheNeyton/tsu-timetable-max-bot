import asyncio
from collections.abc import Awaitable, Callable, Iterator


def _message_parts(text: str, limit: int = 4000) -> Iterator[str]:
    while len(text) > limit:
        boundary = text.rfind("\n", 0, limit + 1)
        if boundary < 1:
            boundary = limit
        yield text[:boundary]
        text = text[boundary:].lstrip("\n")
    if text:
        yield text


async def send_schedule(text: str, reply: Callable[[str], Awaitable[object]]) -> bool:
    for position, part in enumerate(_message_parts(text)):
        if position:
            await asyncio.sleep(0.55)
        if await reply(part) is None:
            return False
    return True
