# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

# The rewrite destination is evaluated at build time by Next.js,
# so we set the internal Docker URL here.
ENV INTERNAL_API_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 2: Runner — standalone output only (no full node_modules, ~10x smaller)
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# next.config.js `output: "standalone"` emits a self-contained server.js
# with its own pruned node_modules subset.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

# Keep at runtime too (Next.js re-evaluates rewrites on each request)
ENV INTERNAL_API_URL=http://api:8000
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

USER node
EXPOSE 3000
CMD ["node", "server.js"]
