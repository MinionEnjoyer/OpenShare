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

COPY main.py auth.py db.py thumbs.py ./
COPY templates ./templates
COPY static ./static

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
