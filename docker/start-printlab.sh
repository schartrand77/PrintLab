#!/usr/bin/env sh
set -eu

: "${REQUIRE_AUTH:=true}"
export REQUIRE_AUTH

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
