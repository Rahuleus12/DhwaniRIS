# Part A — three-service stack (app + MariaDB + nginx)

A deliberately small stack: a Flask app behind nginx, writing one row to
MariaDB per visit. The application is a vehicle for the infrastructure
requirements, nothing more.

## Start from a clean clone

```bash
cp .env.example .env    # then edit .env and set real passwords
docker compose up -d --build
```

Then check it:

```bash
curl http://localhost/health   # {"database":"up","status":"ok"}
curl http://localhost/         # HTML page showing the visit counter
```

There are no other manual steps. Everything else (secrets, limits,
readiness gating) is in `docker-compose.yml`, the `Dockerfile` and
`proxy/nginx.conf`.

## Verify the requirements

```bash
# App does not run as root -> prints "app"
docker compose exec app whoami

# All three services up, db reports "healthy"
docker compose ps

# Data survives down/up: visit the page a few times, then
docker compose down && docker compose up -d
curl http://localhost/   # counter continues from where it left off

# Memory limits are enforced (512M / 128M / 64M)
docker stats --no-stream
```

## Memory limits

| Service | Limit | Why this number |
|---|---|---|
| db | 512M | MariaDB 10.6 defaults to a 128M InnoDB buffer pool; idle RSS is ~200-250M. 512M is ~2x headroom without any tuning. |
| app | 128M | Two gunicorn workers at ~25-35M each under load. 128M is ~2-3x headroom. |
| proxy | 64M | nginx alpine runs at ~3-8M RSS. 64M is already generous; there is nothing meaningful to save by going lower. |

If usage ever presses against these, the first number to revisit is the
db limit — the symptom would be `docker inspect` showing `OOMKilled` on
the db container during month-end load.

## Image size

`docker images` after build:

```
<!-- TODO(rahul): paste the real `docker images` output here after building -->
```

The app image is a single-stage build on `python:3.12-alpine`. All three
dependencies are pure Python, so nothing needs compiling, and
`--no-cache-dir` keeps pip's download cache out of the image. A
multi-stage build would save only a few megabytes here — pip and the
standard library are part of the base image either way — and was judged
not worth the extra complexity.

## Design decisions

- **Two layers of "database is ready".** Compose gates the app container
  on the MariaDB healthcheck (`healthcheck.sh --connect
  --innodb_initialized`, i.e. InnoDB is actually initialised, not merely
  "the port answered"). On top of that the app itself retries with a
  `SELECT 1` before serving. The healthcheck handles startup ordering;
  the in-app retry covers the database restarting later. `depends_on`
  without a condition — the Part B failure mode — would only order
  container starts, not readiness.
- **The db service publishes no ports.** It is reachable only on the
  compose network by the app. Publishing `127.0.0.1:3306:3306` would be
  defensible for local debugging; publishing nothing is the smaller
  surface, and nothing in this stack needs host access to the database.
- **The named volume mounts at `/var/lib/mysql`** — the directory
  MariaDB actually writes to. (The Part B config mounts `/var/lib/mysql/data`,
  which the database never uses.)
- **Secrets live only in `.env`**, which is gitignored from the first
  commit. Compose interpolates values from it; the app receives only the
  least-privilege `DB_USER`/`DB_PASSWORD`, never the root password.
- **nginx sets `Host` and `X-Forwarded-*` headers** so the app would
  generate correct absolute URLs if it ever needed to — the omission
  that causes symptom S3 in Part B.
- **App runs as the unprivileged `app` user** created in the Dockerfile;
  nothing in the stack runs as root.

## Most awkward requirement

<!-- TODO(rahul): one short, honest paragraph — which requirement above
     was most awkward to get working, and what you tried before it
     worked. Write this after you've built and tested the stack, from
     real experience. An honest "the healthcheck kept passing before
     InnoDB was actually ready so I ..." is exactly what is wanted. -->
     recording and uploading was awkward and so was not letting ai paint my opinions at all times.

## Recording

<!-- TODO(rahul): unlisted YouTube or Google Drive link goes here.
     Confirm it opens in a private browser window before submitting. -->
https://youtu.be/S-zmy3MMv8s
