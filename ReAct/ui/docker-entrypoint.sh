#!/bin/sh
set -e

if [ -z "$BACKEND_URL" ]; then
  echo "ERROR: BACKEND_URL is not set. Example: https://react-pr-api.xxxx.eastus.azurecontainerapps.io"
  exit 1
fi

export BACKEND_URL
envsubst '${BACKEND_URL}' < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "nginx proxying /api/* -> ${BACKEND_URL}/api/*"
exec nginx -g 'daemon off;'
