from pyrogram import Client

from src.core.context import AppContext
from src.core.plugin import Plugin, register

from . import handlers


class AIAssistantPlugin(Plugin):
    name = "ai_assistant"
    priority = 50

    async def setup(self, client: Client, ctx: AppContext) -> None:
        pass

    async def teardown(self) -> None:
        from .service import AIService

        await AIService.close()


register(AIAssistantPlugin())
