FROM python:3.11-slim

WORKDIR /app

ENV GOOGLE_CLOUD_PROJECT="365383383851"
ENV GOOGLE_CLIENT_CONFIG_SECRET_ID="spotify-oauth-client-secret"
ENV REDIRECT_URI="https://spotify-oauth-365383383851.us-central1.run.app/oauth2callback"
ENV PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips=*"]