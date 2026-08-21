FROM python:3.12-alpine

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Dedicated unprivileged user; the app never runs as root.
RUN addgroup -S app && adduser -S -G app app
USER app

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--access-logfile", "-", "app:app"]
