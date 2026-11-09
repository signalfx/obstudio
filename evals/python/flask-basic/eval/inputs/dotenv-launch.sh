#!/bin/sh
set -eu
set -a
. ./.env
set +a
exec "$@"
