FROM node:20-bookworm-slim AS builder
WORKDIR /app
COPY scripts ./scripts
COPY web ./web
WORKDIR /app/web
RUN npm ci
RUN npx prisma generate
ENV SCRIPTS_ROOT=/app/scripts
ARG DATABASE_URL="file:./build.db"
RUN npx prisma migrate deploy
RUN node scripts/sync-scripts-to-db.mjs
RUN npm run build

FROM node:20-bookworm-slim AS runner
WORKDIR /app/web
ENV NODE_ENV=production
ENV SCRIPTS_ROOT=/app/scripts
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/web/package.json ./
COPY --from=builder /app/web/package-lock.json ./
COPY --from=builder /app/web/node_modules ./node_modules
COPY --from=builder /app/web/.next ./.next
COPY --from=builder /app/web/public ./public
COPY --from=builder /app/web/prisma ./prisma
EXPOSE 3000
CMD ["npm", "start"]
