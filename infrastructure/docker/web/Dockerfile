# React frontend served by unprivileged nginx, which also proxies /api to the backend.
#   docker build -f infrastructure/docker/web/Dockerfile -t sei-web .
FROM node:25-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30.6-alpine
# Apply Alpine security fixes released after the base image was built, then drop back to the
# image's unprivileged nginx user (uid 101).
USER root
RUN apk upgrade --no-cache
USER 101
COPY infrastructure/docker/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY infrastructure/docker/web/security-headers.inc /etc/nginx/conf.d/security-headers.inc
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
