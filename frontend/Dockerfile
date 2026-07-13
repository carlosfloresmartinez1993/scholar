FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# BACKEND_URL: http://backend.railway.internal:8000 (Railway private net) or an https public URL.
# DNS_RESOLVER defaults to Railway's private-network resolver.
ENV PORT=8080
CMD ["sh", "-c", "export DNS_RESOLVER=\"${DNS_RESOLVER:-[fd12::10]}\" BACKEND_HOST=$(echo $BACKEND_URL | sed 's|https\\?://||'); envsubst '${PORT} ${BACKEND_URL} ${BACKEND_HOST} ${DNS_RESOLVER}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
