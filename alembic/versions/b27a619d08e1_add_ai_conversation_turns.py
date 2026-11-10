"""Add participant/topic-scoped AI conversation turns.

Revision ID: b27a619d08e1
Revises: a1b2c3d4e5f6
"""

import sqlalchemy as sa

from alembic import op

revision = "b27a619d08e1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "aiconversationturn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chatId", sa.BigInteger(), sa.ForeignKey("chatsettings.id"), nullable=False),
        sa.Column("threadId", sa.BigInteger(), nullable=False),
        sa.Column("userId", sa.BigInteger(), nullable=False),
        sa.Column("messageId", sa.BigInteger(), nullable=False),
        sa.Column("userText", sa.Text(), nullable=False),
        sa.Column("assistantText", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_conversation_scope", "aiconversationturn", ["chatId", "threadId", "userId", "id"]
    )
    op.create_index("ix_ai_conversation_expiry", "aiconversationturn", ["timestamp"])


def downgrade():
    op.drop_table("aiconversationturn")
