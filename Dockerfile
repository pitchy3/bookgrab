FROM python:3.12-slim

ARG PUID=1000
ARG PGID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid "${PGID}" app && \
    useradd --uid "${PUID}" --gid "${PGID}" --create-home --shell /usr/sbin/nologin app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY README.md .

RUN mkdir -p /config && chown -R app:app /app /config && chmod -R u+rwX,g+rwX /config
USER app

EXPOSE 8787
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
