FROM python:3.12-slim

ARG PUID=1000
ARG PGID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN set -eux; \
    if ! getent group "${PGID}" >/dev/null; then \
        groupadd --gid "${PGID}" app; \
    fi; \
    if ! getent passwd "${PUID}" >/dev/null; then \
        useradd --uid "${PUID}" --gid "${PGID}" --create-home --shell /usr/sbin/nologin app; \
    fi

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY README.md .

RUN mkdir -p /config && chown -R "${PUID}:${PGID}" /app /config && chmod -R u+rwX,g+rwX /config
USER ${PUID}:${PGID}

EXPOSE 8787
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
