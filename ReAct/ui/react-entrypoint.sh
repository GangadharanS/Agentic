#!/bin/sh
# Custom entrypoint (not /docker-entrypoint.sh — that path is the stock nginx image script).
set -e

if [ -z "${BACKEND_URL:-}" ]; then
  echo "ERROR: BACKEND_URL is not set. Example: http://react-pr-api"
  exit 1
fi

export BACKEND_URL
envsubst '${BACKEND_URL}' < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "ReAct UI: nginx proxying /api/* -> ${BACKEND_URL}/api/*"
exec nginx -g 'daemon off;'
