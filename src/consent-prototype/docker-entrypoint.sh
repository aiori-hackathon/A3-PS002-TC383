#!/bin/sh
# Starts as root only so a freshly mounted data volume (e.g. a Render disk) is writable,
# then drops to the unprivileged user before running the app.
set -e
umask 077   # files the app creates (database, logs) are readable by their owner only
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/logs
  chown -R appuser:appuser /data 2>/dev/null || true
  exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
fi
exec "$@"
