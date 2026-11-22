#!/bin/sh
set -eu

: "${POSTGRES_PASSWORD:?Set a unique PostgreSQL bootstrap password}"
: "${BOT_DB_PASSWORD:?Set a separate password for lex_bot}"

if [ "${POSTGRES_USER:-postgres}" = lex_bot ] ||
    [ "$POSTGRES_PASSWORD" = bot_password ] ||
    [ "$BOT_DB_PASSWORD" = bot_password ] ||
    [ "$POSTGRES_PASSWORD" = "$BOT_DB_PASSWORD" ]; then
    echo "Use a separate PostgreSQL bootstrap login and password." >&2
    exit 1
fi

exec docker-entrypoint.sh "$@"
