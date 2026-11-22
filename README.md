# Lex-TG

<img src="assets/lex_bot_banner.png" alt="Lex-TG banner" width="300">

Lex-TG is a Telegram bot for moderating groups and automating channel posts. Admins can configure it from a private settings panel inside Telegram.

[עברית](README.he.md) · [Quick start](#quick-start) · [Deployment](#deployment) · [Development](#development)

## What it does

- **Moderation** — Manage bans, mutes, warnings, and bulk message cleanup.
- **Group protection** — Configure anti-flood and anti-raid rules, CAPTCHA, filters, and blacklists.
- **Group automation** — Set welcome messages, rules, reminders, and scheduled chat locks.
- **Channel automation** — Add reactions, signatures, links, and watermarks to posts.
- **AI tools** — Configure the optional AI assistant and content guard from the admin panel.

## Quick start

You’ll need Python 3.12 or newer, `uv`, a bot token from BotFather, and an API ID and hash from `my.telegram.org`.

From the repository root, install dependencies and create a local configuration. If you already have a `.env`, keep it and edit it in place.

```sh
uv sync
test -f .env || cp .env.example .env
mkdir -p data sessions logs
```

Set these values in `.env`.

| Variable | Value |
| --- | --- |
| `API_ID` and `API_HASH` | Telegram API credentials from `my.telegram.org`. |
| `BOT_TOKEN` | The token issued by BotFather. |
| `OWNER_ID` | Your numeric Telegram user ID. |
| `DATABASE_URL` | Use `sqlite+aiosqlite:///data/bot.sqlite3` for a persistent local database, or enter your PostgreSQL connection URL. |

Keep your `.env` and Telegram session files private. Then start the bot.

```sh
uv run bot
```

In Telegram, open the bot privately and send `/start`. Add it to your group or channel and grant the permissions needed for the features you plan to use. In a group, send `/settings` to open the private admin panel. You can also send `/settings` privately to choose a managed chat, or `/help` to browse commands.

## Deployment

**Docker Compose.** Set the Telegram and owner values in `.env`. Set `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`, then make sure `DATABASE_URL` uses the same credentials and the Compose database host `db`. Start the services and follow the bot logs.

```sh
docker compose up -d
docker compose logs -f bot
```

**Railway.** Create a project with a PostgreSQL service and configure the bot’s environment variables and persistent storage. [Railway deployment guide](RAILWAY_GUIDE.md)

## Development

| Task | Command |
| --- | --- |
| Run tests | `uv run pytest -q` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type-check | `uv run mypy src/` |
| Apply database migrations | `uv run alembic upgrade head` |
| Run the locale sync tool | `uv run translate` |

Telegram handlers live in [`src/plugins/`](src/plugins), the settings UI in [`src/plugins/admin_panel/`](src/plugins/admin_panel), and database models and repositories in [`src/db/`](src/db). Translations are in [`src/locales/`](src/locales), and automated checks are in [`tests/`](tests).
