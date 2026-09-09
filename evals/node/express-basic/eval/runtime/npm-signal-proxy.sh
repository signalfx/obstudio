#!/bin/sh
set -u

signal_leaves() {
  children="$(sed -n '1p' "/proc/$1/task/$1/children" 2>/dev/null)"
  if [ -z "$children" ]; then
    kill -TERM "$1" 2>/dev/null || true
    return
  fi
  for child in $children; do
    signal_leaves "$child"
  done
}

"$@" &
runner_pid=$!
forward_and_wait() {
  trap - TERM INT
  signal_leaves "$runner_pid"
  wait "$runner_pid"
  exit $?
}
trap forward_and_wait TERM INT

wait "$runner_pid"
exit $?
