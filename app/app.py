"""Minimal web app: serves /health and records one row per visit.

Deliberately tiny — the assignment assesses the infrastructure around
the app, not the app itself.
"""

import logging
import os
import time
from contextlib import contextmanager

import pymysql
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("app")

DB_CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "30"))
DB_CONNECT_DELAY = int(os.environ.get("DB_CONNECT_DELAY", "2"))


def connect() -> pymysql.connections.Connection:
    """Open a connection using the environment-provided settings."""
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def wait_for_db():
    """Block until the database answers a real query.

    The compose healthcheck already gates container start; this retry
    loop is a second line of defence for the case where the database
    restarts later or passes its ping marginally early.
    """
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            with db() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            logger.info("database ready after %d attempt(s)", attempt)
            return
        except pymysql.MySQLError as exc:
            logger.warning(
                "database not ready (attempt %d/%d): %s",
                attempt, DB_CONNECT_RETRIES, exc,
            )
            time.sleep(DB_CONNECT_DELAY)
    raise SystemExit(
        f"database still unreachable after {DB_CONNECT_RETRIES} attempts, giving up"
    )


wait_for_db()

with db() as conn, conn.cursor() as cur:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS visits (
            id INT AUTO_INCREMENT PRIMARY KEY,
            visited_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

app = Flask(__name__)


@app.get("/")
def index():
    with db() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO visits () VALUES ()")
        cur.execute("SELECT COUNT(*), MAX(visited_at) FROM visits")
        row = cur.fetchone()
    count, latest = row if row is not None else (0, None)
    return (
        "<!doctype html><html><head><title>Part A stack</title></head>"
        "<body style='font-family: sans-serif; margin: 3rem'>"
        "<h1>Hello from the Part A stack</h1>"
        f"<p>This is visit number <strong>{count}</strong>.</p>"
        f"<p>Last visit recorded at {latest}.</p>"
        "<p>The counter lives in MariaDB — restart the stack and it survives.</p>"
        "</body></html>"
    )


@app.get("/health")
def health():
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
        return jsonify(status="ok", database="up")
    except pymysql.MySQLError as exc:
        return jsonify(status="degraded", database="down", error=str(exc)), 503
