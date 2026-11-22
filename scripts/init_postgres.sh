#!/bin/sh
set -eu

if [ "$POSTGRES_USER" = lex_bot ] ||
    [ "$POSTGRES_PASSWORD" = bot_password ] ||
    [ "$BOT_DB_PASSWORD" = bot_password ] ||
    [ "$POSTGRES_PASSWORD" = "$BOT_DB_PASSWORD" ]; then
    echo "Use a separate PostgreSQL bootstrap login and password." >&2
    exit 1
fi

psql --no-psqlrc --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" <<'SQL'
\getenv bot_password BOT_DB_PASSWORD
BEGIN;
CREATE ROLE lex_bot LOGIN PASSWORD :'bot_password';
GRANT USAGE, CREATE ON SCHEMA public TO lex_bot;
COMMIT;
SQL
