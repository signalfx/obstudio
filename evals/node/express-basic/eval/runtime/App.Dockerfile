FROM node:22.23.4-bookworm-slim

WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .

EXPOSE 8000
CMD ["node", "--import", "./instrumentation.js", "app.js"]
