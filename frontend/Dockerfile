# syntax=docker/dockerfile:1
#
# Stage 1 (build) installs deps and runs the production Vite build.
# Stage 2 (runtime) serves the static output via nginx's official
# unprivileged image — nginxinc/nginx-unprivileged runs as a non-root
# user (uid 101) and listens on 8080 by design, rather than needing us to
# bolt on a `USER` directive after the fact.
#
# No secrets are baked in: the only thing this image needs at runtime is
# API_BASE_URL, and even that is applied at container *start* (via
# docker-entrypoint.sh), not at build time — see src/api/client.ts's
# runtime-config precedence and DECISIONS.md's Sprint 11 entry.

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

USER root

COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget --quiet --spider http://localhost:8080/ || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
