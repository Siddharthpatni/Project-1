# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# The rewrite destination is evaluated at build time by Next.js,
# so we set the internal Docker URL here.
ENV INTERNAL_API_URL=http://api:8000
RUN npm run build

# Stage 2: Runner
FROM node:20-alpine AS runner

WORKDIR /app
COPY --from=builder /app/package.json .
COPY --from=builder /app/package-lock.json .
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules

# Keep at runtime too (Next.js re-evaluates rewrites on each request)
ENV INTERNAL_API_URL=http://api:8000

EXPOSE 3000
CMD ["npm", "start"]
