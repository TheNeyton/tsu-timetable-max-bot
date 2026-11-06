from maxapi.types import MessageCreated


async def echo_message(event: MessageCreated) -> None:
    message = event.message
    if message.sender is None or message.sender.is_bot:
        return
    if message.body is None or not message.body.text:
        return

    await message.answer(message.body.text)
