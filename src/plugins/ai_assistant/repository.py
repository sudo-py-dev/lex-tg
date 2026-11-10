from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from src.core.context import AppContext
from src.db.models.ai import AIChatContext, AIConversationTurn, AISettings
from src.utils.local_cache import get_cache


@dataclass(frozen=True)
class AssistantSettings:
    provider: str
    modelId: str | None
    systemPrompt: str | None
    customInstruction: str | None
    isAssistantEnabled: bool
    apiKey: str | None = field(repr=False)


class AIRepository:
    _CONTEXT_DB_LIMIT = 40
    _CONTEXT_TOTAL_CHAR_BUDGET = 9000
    _CONTEXT_USER_MSG_MAX_CHARS = 900
    _CONTEXT_ASSISTANT_MSG_MAX_CHARS = 1200

    @staticmethod
    async def get_settings(ctx: AppContext, chat_id: int) -> AISettings | None:
        async with ctx.db() as session:
            return await session.get(AISettings, chat_id)

    @staticmethod
    async def update_settings(ctx: AppContext, chat_id: int, **kwargs) -> AISettings:
        async with ctx.db() as session:
            s = await session.get(AISettings, chat_id)
            if not s:
                s = AISettings(chatId=chat_id)
                session.add(s)
            for k, v in kwargs.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            await session.commit()
            await get_cache().delete(f"ai_settings:{chat_id}")
            await session.refresh(s)
            return s

    @staticmethod
    async def add_message(
        ctx: AppContext, chat_id: int, msg_id: int, user_id: int, name: str, text: str
    ) -> None:
        async with ctx.db() as session:
            session.add(
                AIChatContext(
                    chatId=chat_id,
                    messageId=msg_id,
                    userId=user_id,
                    userName=name,
                    text=text,
                    timestamp=datetime.now(UTC),
                )
            )
            # Keep history under limit via subquery delete
            subq = (
                select(AIChatContext.id)
                .where(AIChatContext.chatId == chat_id)
                .order_by(AIChatContext.timestamp.desc())
                .offset(50)
                .scalar_subquery()
            )
            await session.execute(delete(AIChatContext).where(AIChatContext.id.in_(subq)))
            await session.commit()

    @staticmethod
    async def get_context(ctx: AppContext, chat_id: int, bot_id: int) -> list[dict[str, str]]:
        async with ctx.db() as session:
            res = await session.execute(
                select(AIChatContext)
                .where(AIChatContext.chatId == chat_id)
                .order_by(AIChatContext.timestamp.desc())
                .limit(AIRepository._CONTEXT_DB_LIMIT)
            )
            msgs = res.scalars().all()

            ctx_list, cur_chars = [], 0
            for m in msgs:
                role = "assistant" if m.userId == bot_id else "user"
                txt = m.text if role == "assistant" else f"[{m.userName}]: {m.text}"
                limit = (
                    AIRepository._CONTEXT_ASSISTANT_MSG_MAX_CHARS
                    if role == "assistant"
                    else AIRepository._CONTEXT_USER_MSG_MAX_CHARS
                )

                if len(txt) > limit:
                    txt = txt[:limit] + "..."
                if cur_chars + len(txt) > AIRepository._CONTEXT_TOTAL_CHAR_BUDGET:
                    rem = AIRepository._CONTEXT_TOTAL_CHAR_BUDGET - cur_chars
                    if rem > 100:
                        ctx_list.append({"role": role, "content": txt[:rem] + "..."})
                    break

                ctx_list.append({"role": role, "content": txt})
                cur_chars += len(txt)
            return ctx_list[::-1]

    @staticmethod
    async def clear_context(ctx: AppContext, chat_id: int) -> None:
        async with ctx.db() as session:
            await session.execute(delete(AIChatContext).where(AIChatContext.chatId == chat_id))
            await session.execute(
                delete(AIConversationTurn).where(AIConversationTurn.chatId == chat_id)
            )
            await session.commit()

    @staticmethod
    async def get_runtime_settings(ctx: AppContext, chat_id: int) -> AssistantSettings | None:
        async def load():
            async with ctx.db() as session:
                result = await session.execute(
                    select(
                        AISettings.provider,
                        AISettings.modelId,
                        AISettings.systemPrompt,
                        AISettings.customInstruction,
                        AISettings.isAssistantEnabled,
                        AISettings.apiKey,
                    ).where(AISettings.chatId == chat_id)
                )
                row = result.mappings().first()
                # Cache disabled/unconfigured chats too, without storing ORM objects or keys on disk.
                return AssistantSettings(**row) if row else False

        value = await get_cache().get_or_load(f"ai_settings:{chat_id}", load, ttl=60)
        return value if value is not False else None

    @staticmethod
    def _scope(chat_id: int, thread_id: int, user_id: int):
        return (
            AIConversationTurn.chatId == chat_id,
            AIConversationTurn.threadId == thread_id,
            AIConversationTurn.userId == user_id,
        )

    @staticmethod
    async def get_conversation(ctx: AppContext, chat_id: int, thread_id: int, user_id: int):
        async with ctx.db() as session:
            result = await session.execute(
                select(AIConversationTurn)
                .where(
                    *AIRepository._scope(chat_id, thread_id, user_id),
                    AIConversationTurn.timestamp >= datetime.now(UTC) - timedelta(hours=2),
                )
                .order_by(AIConversationTurn.id.desc())
                .limit(12)
            )
            turns = list(result.scalars())
        messages = []
        for turn in reversed(turns):
            messages.extend(
                [
                    {"role": "user", "content": turn.userText},
                    {"role": "assistant", "content": turn.assistantText},
                ]
            )
        return messages

    @staticmethod
    async def save_turn(
        ctx: AppContext,
        chat_id: int,
        thread_id: int,
        user_id: int,
        message_id: int,
        user_text: str,
        assistant_text: str,
    ) -> None:
        scope = AIRepository._scope(chat_id, thread_id, user_id)
        async with ctx.db() as session:
            session.add(
                AIConversationTurn(
                    chatId=chat_id,
                    threadId=thread_id,
                    userId=user_id,
                    messageId=message_id,
                    userText=user_text,  # The bounded request envelope must remain valid JSON.
                    assistantText=assistant_text[:24000],
                )
            )
            await session.flush()
            stale = (
                select(AIConversationTurn.id)
                .where(*scope)
                .order_by(AIConversationTurn.id.desc())
                .offset(12)
            )
            await session.execute(
                delete(AIConversationTurn).where(AIConversationTurn.id.in_(stale))
            )
            await session.execute(
                delete(AIConversationTurn).where(
                    AIConversationTurn.timestamp < datetime.now(UTC) - timedelta(days=7)
                )
            )
            await session.commit()

    @staticmethod
    async def clear_conversation(
        ctx: AppContext, chat_id: int, thread_id: int, user_id: int
    ) -> None:
        async with ctx.db() as session:
            await session.execute(
                delete(AIConversationTurn).where(*AIRepository._scope(chat_id, thread_id, user_id))
            )
            await session.commit()
