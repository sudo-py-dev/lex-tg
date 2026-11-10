from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chats import ChatSettings

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
)
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class AISettings(Base):
    __tablename__ = "aisettings"

    chatId: Mapped[int] = mapped_column(BigInteger, ForeignKey("chatsettings.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(50), default="openai", server_default=sa_text("'openai'")
    )
    apiKey: Mapped[str | None] = mapped_column(Text, nullable=True)
    modelId: Mapped[str | None] = mapped_column(String(100), nullable=True)
    systemPrompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    customInstruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    isAssistantEnabled: Mapped[bool] = mapped_column(default=False, server_default=false())

    chat: Mapped["ChatSettings"] = relationship(
        back_populates="aiSettings", uselist=False, lazy="selectin"
    )


class AIGuardSettings(Base):
    __tablename__ = "aiguardsettings"

    chatId: Mapped[int] = mapped_column(BigInteger, ForeignKey("chatsettings.id"), primary_key=True)
    isTextEnabled: Mapped[bool] = mapped_column(default=False, server_default=false())
    apiKey: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(
        String(50), default="delete", server_default=sa_text("'delete'")
    )
    isImageEnabled: Mapped[bool] = mapped_column(default=False, server_default=false())

    chat: Mapped["ChatSettings"] = relationship(
        back_populates="aiGuardSettings", uselist=False, lazy="selectin"
    )


class AIChatContext(Base):
    __tablename__ = "aichatcontext"

    id: Mapped[int] = mapped_column(primary_key=True)
    chatId: Mapped[int] = mapped_column(BigInteger, ForeignKey("chatsettings.id"), index=True)
    messageId: Mapped[int] = mapped_column(BigInteger)
    userId: Mapped[int] = mapped_column(BigInteger)
    userName: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


class AIConversationTurn(Base):
    """Completed turns scoped to one participant in one chat/topic."""

    __tablename__ = "aiconversationturn"
    __table_args__ = (
        Index("ix_ai_conversation_scope", "chatId", "threadId", "userId", "id"),
        Index("ix_ai_conversation_expiry", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chatId: Mapped[int] = mapped_column(BigInteger, ForeignKey("chatsettings.id"), nullable=False)
    threadId: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    userId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    messageId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    userText: Mapped[str] = mapped_column(Text, nullable=False)
    assistantText: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
