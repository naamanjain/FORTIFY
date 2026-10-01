# FORTIFY frontend — static Vite build served by nginx.
#
# Build from the FRONTEND directory:
#
#   docker build -t fortify-frontend .
#
# nginx serves the SPA and proxies /api and /health to the backend service
# named "fortify-backend" (docker-compose service / k8s Service, port 8000),
# so the browser talks same-origin and no CORS setup is required.
FROM node:24-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
