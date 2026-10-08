"""A support bot for a made-up shop. SHOP_BOT_BUILD picks the build: 1.0 or 1.1."""

import os
from contextlib import asynccontextmanager

from convy import Answer, Message, Usage

from gateway import MODEL, gateway

POLICY = """You are the support assistant of Northwind, an online shop for home goods.
Policy: refunds within 30 days with the order number; delivery to the EU only, 3-7 days;
damaged items are replaced for free after a photo. If you do not know, say so and offer a human."""

BUILDS = {
    "1.0": POLICY + "\nAsk for any detail you need before you act.",
    # 1.1 shortens the prompt to save tokens, and loses the policy on the way.
    "1.1": "You are the friendly support assistant of Northwind, an online shop for home goods. "
    "Help quickly and always offer a solution.",
}

version = os.environ.get("SHOP_BOT_BUILD", "1.0")
if version not in BUILDS:
    raise ValueError(f"SHOP_BOT_BUILD must be one of {', '.join(BUILDS)}")


class ShopBot:
    @asynccontextmanager
    async def conversation(self):
        async with gateway.connection() as connection:
            yield ShopChat(connection)


class ShopChat:
    def __init__(self, connection):
        self.connection = connection
        self.history = [{"role": "system", "content": BUILDS[version]}]

    async def answer(self, message: Message) -> Answer:
        self.history.append({"role": "user", "content": message.text})
        data = await self.connection.post({"model": MODEL, "messages": self.history})
        text = data["choices"][0]["message"]["content"]
        self.history.append({"role": "assistant", "content": text})
        usage = data["usage"]
        return Answer(text, Usage(input=usage["prompt_tokens"], output=usage["completion_tokens"]))


agent = ShopBot()
