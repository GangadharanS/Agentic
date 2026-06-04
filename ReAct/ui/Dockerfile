FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Leave empty for Azure — nginx proxies /api to BACKEND_URL at runtime.
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:alpine
RUN apk add --no-cache gettext
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY react-entrypoint.sh /react-entrypoint.sh
RUN chmod +x /react-entrypoint.sh \
    && rm -f /docker-entrypoint.d/20-envsubst-on-templates.sh
EXPOSE 80
ENV BACKEND_URL=
ENTRYPOINT ["/react-entrypoint.sh"]
