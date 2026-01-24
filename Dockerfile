FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
  && mkdir -p /usr/share/keyrings \
  && curl -fsSL https://download.zerotier.com/contact%40zerotier.com.gpg | gpg --dearmor -o /usr/share/keyrings/zerotier.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/zerotier.gpg] http://download.zerotier.com/debian/bookworm bookworm main" > /etc/apt/sources.list.d/zerotier.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends zerotier-one \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
  && pip install -r /app/requirements.txt --retries 10 --timeout 100

COPY app /app/app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

RUN mkdir -p /app/certs && \
    openssl req -x509 -newkey rsa:4096 -nodes \
    -out /app/certs/cert.pem \
    -keyout /app/certs/key.pem \
    -days 365 \
    -subj "/C=RU/ST=Moscow/L=Moscow/O=CorpVPN/CN=10.121.15.102" \
    -addext "subjectAltName=IP:10.121.15.102,DNS:tgadmin.corp.clan"

EXPOSE 8080 443

CMD ["/app/start.sh"]

