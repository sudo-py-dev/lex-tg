from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.db.repositories.chats import get_chat_settings, update_chat_setting
from src.plugins.channels import ChannelsPlugin
from src.utils.channel_content import build_content_plan, calculate_target_content
from tests.factories import ChannelSettingsFactory


@pytest.fixture
def mock_ctx(db_session):
    """Mock AppContext to work with repository functions."""
    ctx = MagicMock()
    # Mock the 'async with ctx.db() as session:' pattern
    ctx.db.return_value.__aenter__.return_value = db_session
    return ctx


@pytest.mark.asyncio
async def test_channel_settings_creation(mock_ctx, db_session):
    """Test that ChannelSettings can be created and retrieved."""
    # Create via factory
    settings = ChannelSettingsFactory.build(id=-1001, reactions="❤️ 🔥")
    db_session.add(settings)
    await db_session.flush()

    # Retrieve via repository
    fetched = await get_chat_settings(mock_ctx, -1001)
    assert fetched is not None
    assert fetched.id == -1001
    assert fetched.reactions == "❤️ 🔥"


@pytest.mark.asyncio
async def test_update_channel_setting(mock_ctx, db_session):
    """Test updating a specific channel setting."""
    settings = ChannelSettingsFactory.build(id=-1002, reactionsEnabled=False)
    db_session.add(settings)
    await db_session.flush()

    # Update via repository
    await update_chat_setting(mock_ctx, -1002, "reactionsEnabled", True)

    # Verify
    fetched = await get_chat_settings(mock_ctx, -1002)
    assert fetched.reactionsEnabled is True


@pytest.mark.asyncio
async def test_reaction_logic_all_mode():
    """Unit test for the reaction logic (All mode)."""
    plugin = ChannelsPlugin()
    settings = MagicMock()
    settings.reactionsEnabled = True
    settings.reactions = "👍 ❤️"
    settings.reactionMode = "all"

    message = AsyncMock()

    await plugin._handle_reactions(settings, message)

    # Should react with the FIRST emoji in 'all' mode (since bot limit is 1)
    message.react.assert_called_once_with("👍")


@pytest.mark.asyncio
async def test_signature_length_limit():
    """Test that signatures are not added if they exceed the limit."""
    settings = MagicMock()
    settings.signatureEnabled = True
    settings.signatureText = "My Awesome Bot"

    # Text message limit is 4096. Try a message that is 4090 chars long.
    message = AsyncMock()
    message.text = "A" * 4090
    message.caption = None

    # Calculate target (should be None because 4090 + 16 > 4096)
    result = calculate_target_content(settings, message, is_media=False, is_caption_host=True)
    assert result is None


@pytest.mark.asyncio
async def test_combined_watermark_and_signature():
    """Test the unified flow for both enhancements on a photo."""
    plugin = ChannelsPlugin()
    settings = MagicMock()
    settings.watermarkEnabled = True
    settings.watermarkText = '{"text": "@MyChannel", "image_enabled": true}'
    settings.signatureEnabled = True
    settings.signatureText = "Visit us!"
    settings.reactionsEnabled = False
    settings.buttons = None

    message = AsyncMock()
    message.photo = MagicMock()
    message.caption = "Hello world"
    message.media_group_id = None

    # We should see _handle_watermarking called with the combined caption
    with (
        patch.object(plugin, "_handle_watermarking", new_callable=AsyncMock) as mock_water,
        patch.object(plugin, "_is_caption_host", return_value=True),
        patch("src.plugins.channels.get_context", return_value=mock_ctx),
        patch("src.plugins.channels.get_chat_settings", return_value=settings),
    ):
        await plugin._process_message(AsyncMock(), message)

        # Signature should be appended: "Hello world\n\nVisit us!"
        expected_caption = "Hello world\n\nVisit us!"
        mock_water.assert_called_once()
        args = mock_water.call_args[0]
        assert args[1] == expected_caption


@pytest.mark.asyncio
async def test_album_non_host_skips_watermarking(mock_ctx):
    """Test that non-caption host messages in an album skip the watermarking flow."""
    from unittest.mock import AsyncMock, MagicMock, patch

    plugin = ChannelsPlugin()
    settings = MagicMock()
    settings.watermarkEnabled = True
    settings.watermarkText = "@MyChannel"
    settings.reactionsEnabled = False

    message = AsyncMock()
    message.photo = MagicMock()
    message.media_group_id = "album123"
    settings.buttons = None

    # We should see _handle_watermarking NOT called if is_caption_host is False
    with (
        patch.object(plugin, "_handle_watermarking", new_callable=AsyncMock) as mock_water,
        patch.object(plugin, "_is_caption_host", return_value=False),
        patch("src.plugins.channels.get_context", return_value=mock_ctx),
        patch("src.plugins.channels.get_chat_settings", return_value=settings),
    ):
        await plugin._process_message(AsyncMock(), message)

        mock_water.assert_not_called()


def test_album_signature_and_buttons_only_attach_to_caption_host():
    settings = MagicMock(
        signatureEnabled=True,
        signatureText="Visit us",
        buttons='[[{"text":"Read more","url":"https://example.com"}]]',
    )
    photo = SimpleNamespace(
        photo=object(),
        video=None,
        document=None,
        animation=None,
        audio=None,
        voice=None,
        video_note=None,
        caption="Photo caption",
        text=None,
    )
    host = build_content_plan(settings, photo, is_caption_host=True)
    assert host.target_content == "Photo caption\n\nVisit us"
    assert host.reply_markup.inline_keyboard[0][0].text == "Read more"
    other = build_content_plan(settings, photo, is_caption_host=False)
    assert other.target_content is None
    assert other.reply_markup is None


async def test_settings_repository_serializes_concurrent_first_writes(tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.db import Base
    from src.db.repositories.chats import toggle_setting, update_settings

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'settings.sqlite3'}")
    ctx = SimpleNamespace(db=async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        values = await asyncio.gather(
            toggle_setting(ctx, -301, "reactionsEnabled"),
            toggle_setting(ctx, -301, "reactionsEnabled"),
            update_chat_setting(ctx, -301, "title", "Concurrent changes"),
        )
        assert set(values[:2]) == {True, False}
        settings = await get_chat_settings(ctx, -301)
        assert settings.reactionsEnabled is False
        assert settings.title == "Concurrent changes"
        for chat_id in (-301, -302):
            with pytest.raises(ValueError, match="Unknown or immutable"):
                await update_settings(ctx, chat_id, unsupportedField=True)
    finally:
        await engine.dispose()
