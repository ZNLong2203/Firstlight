# syntax=docker/dockerfile:1.7
FROM node:24.22.0-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY . .
ARG VITE_DD_RUM_APPLICATION_ID="" VITE_DD_RUM_CLIENT_TOKEN="" VITE_DD_SITE="" VITE_DD_ENV="local" VITE_DD_VERSION="dev"
ENV VITE_DD_RUM_APPLICATION_ID=$VITE_DD_RUM_APPLICATION_ID VITE_DD_RUM_CLIENT_TOKEN=$VITE_DD_RUM_CLIENT_TOKEN \
    VITE_DD_SITE=$VITE_DD_SITE VITE_DD_ENV=$VITE_DD_ENV VITE_DD_VERSION=$VITE_DD_VERSION
RUN npm run build

FROM nginx:1.30.6-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
