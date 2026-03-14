# ── Stage 1: build React app ──────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .
RUN npm run build

# ── Stage 2: serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Remove the default catch-all vhost so our conf.d file takes effect cleanly
RUN rm /etc/nginx/conf.d/default.conf

# Copy static build artefact
COPY --from=builder /app/dist /usr/share/nginx/html

# Default nginx vhost — overridden at runtime by the Kubernetes ConfigMap mount
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
