#!/bin/sh
set -eu

psql --no-psqlrc --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" <<'SQL'
\getenv bot_password BOT_DB_PASSWORD
BEGIN;
CREATE ROLE lex_bot LOGIN PASSWORD :'bot_password';
GRANT USAGE, CREATE ON SCHEMA public TO lex_bot;
COMMIT;
SQL
