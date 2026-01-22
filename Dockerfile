FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
  && mkdir -p /usr/share/keyrings \
  && curl -fsSL https://download.zerotier.com/contact%40zerotier.com.gpg | gpg --dearmor -o /usr/share/keyrings/zerotier.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/zerotier.gpg] http://download.zerotier.com/debian/bookworm bookworm main" > /etc/apt/sources.list.d/zerotier.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends zerotier-one \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["/app/start.sh"]

