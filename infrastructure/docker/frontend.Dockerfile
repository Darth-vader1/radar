# Next.js frontend. Build context: repository root.
#   target "dev"    -> `next dev` with hot reload (docker-compose.yml)
#   target "runner" -> minimal production server from `output: "standalone"` (docker-compose.prod.yml)

# ---- dependencies (exact versions from package-lock.json) ----
FROM node:26-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# ---- development ----
FROM deps AS dev
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- production build ----
FROM deps AS build
# Next.js resolves rewrites at build time, so the proxy target must be known here.
ARG BACKEND_INTERNAL_URL=http://backend:8000
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL \
    NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production
COPY frontend/ ./
RUN npm run build

# ---- production runtime ----
FROM node:26-alpine AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S nextjs && adduser -S nextjs -G nextjs
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", "server.js"]
