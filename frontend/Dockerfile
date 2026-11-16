# Multi-stage: build the React SPA with Node, then serve the static output
# with nginx. This matches the original tool's deployment pattern (static
# hosting + API elsewhere) and is appropriate for a pure client-side SPA with
# no server-side rendering.

# --- Build stage ------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

# Install exactly what the lockfile pins with `npm ci` (reproducible builds)
# BEFORE copying the rest of the source, so this layer only rebuilds when
# package.json / package-lock.json change (layer-caching optimization).
COPY package.json package-lock.json ./
RUN npm ci

# VITE_API_BASE_URL is a COMPILE-TIME variable, not a runtime one: Vite embeds
# it into the static JS bundle during `npm run build`. A static SPA has no
# server process to read env from at request time, so it must be supplied to
# the image build (--build-arg), not at container start. It tells the bundle
# where the end user's BROWSER can reach the backend (the browser, not the
# frontend container, makes the API calls).
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Copy the rest of the frontend source and build.
# `npm run build` runs `tsc -b && vite build` (see package.json scripts).
COPY . .
RUN npm run build

# --- Serve stage ------------------------------------------------------------
FROM nginx:alpine

# Serve the built static output from nginx's default html root.
COPY --from=build /app/dist /usr/share/nginx/html

# SPA fallback: client-side routes (React Router) must be served index.html
# on refresh / direct-URL access, otherwise /devices/sw-ot would 404 here.
# nginx.conf also sets the security headers.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Its Content-Security-Policy lets the page connect to the API and to nothing
# else, so it has to name the API: the origin (scheme://host:port) of the same
# VITE_API_BASE_URL that was baked into the bundle above, with the same
# fallback as src/lib/api.ts. `nginx -t` fails the build on a broken result.
ARG VITE_API_BASE_URL
RUN origin="$(echo "${VITE_API_BASE_URL:-http://localhost:8410}" | sed -E 's|^([a-z]+://[^/]+).*|\1|')" \
    && sed -i "s|__API_ORIGIN__|${origin}|" /etc/nginx/conf.d/default.conf \
    && nginx -t

EXPOSE 8411
