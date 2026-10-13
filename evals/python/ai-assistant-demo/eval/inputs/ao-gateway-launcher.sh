#!/bin/sh
set -eu
ao_profile=${AO_ENV_FILE:-.local/real.env}
set -a
. "$ao_profile"
set +a
exec "$@"
