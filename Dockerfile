FROM node:22-alpine AS web-build

WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    poppler-utils \
    libegl1 libgles2 libgl1 \
    fonts-dejavu-core \
    assimp-utils \
 && rm -rf /var/lib/apt/lists/*

ENV PYOPENGL_PLATFORM=egl

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY VERSION main.py auth.py contacts.py db.py mirror.py spreadsheets.py thumbs.py ./
COPY templates ./templates
COPY static ./static
COPY --from=web-build /src/static/react ./static/react

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
