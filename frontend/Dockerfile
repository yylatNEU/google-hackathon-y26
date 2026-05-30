FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build:local

FROM node:20-alpine

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
EXPOSE ${PORT}

COPY --from=build /app/dist ./dist
COPY server.mjs ./server.mjs

CMD ["node", "server.mjs"]
