FROM node:24-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL
ARG VITE_BUSINESS_TIMEZONE
RUN npm run build

FROM alpine:3.23 AS dist
COPY --from=build /app/dist /dist

FROM build AS preview
EXPOSE 3000
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "3000"]
