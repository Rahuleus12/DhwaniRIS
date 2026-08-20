S1(silent restarts 2-3 timses per day):
docker-compose.yml-line 23

```
app:
  deploy:
    resources:
      limits:
        memory:256M
```

The application restarts as the limit of 256M causes the app to run out of memory, to stop and restart. This is also the reason for lack of anything unusual or warnings in the logs. The key would be in the container journalctl logs.

To confirm this i would run

```
docker inspect $(docker compose ps -q app) --format '{{.HostConfig.Memory}} {{.RestartCount}}'   # → 268435456, rising count
docker events --since 48h --filter container=$(docker compose ps -q app)                          # die events with exitCode=137 (128+9=SIGKILL)
journalctl -k --grep='oom|Killed process'                                                        # names the app process and the cgroup
docker stats --no-stream   # repeated over hours: watch RSS climb toward 256MiB
```

The fix would be to increase the limit to 1G, since it goes down 3 times this should provide enough memory to be stable.

S2(Server reboot caused data loss):
docker-compose.yml-line 11

```
db:
    volumes:
      - dbdata:/var/lib/mysql/data
```

MariaDB writes to /var/lib/mysql. The mount sits one level too deep, so dbdata stays empty and the data lands in an anonymous volume. `docker compose restart` keeps the container, so the data survives — the earlier restart lost nothing. Patching removes the container (`down`, then `up -d`); the new container gets a new anonymous volume and starts with an empty database.

To confirm this i would run

```
docker compose exec db mariadb-admin variables | grep -i datadir       # → /var/lib/mysql/
docker inspect $(docker compose ps -q db) --format '{{json .Mounts}}'  # dbdata at /var/lib/mysql/data; anonymous volume at /var/lib/mysql
docker volume ls -q   # orphaned 64-hex volumes = the old data
docker run --rm -v <ORPHAN_ID>:/x alpine ls /x   # ibdata1, appdb/ — still on disk
```

Mount the volume at the data directory; first copy the data out of the orphaned volume:

```
docker compose down
docker run --rm -v <ORPHAN_ID>:/from -v <PROJECT>_dbdata:/to alpine cp -a /from/. /to/   # dbdata's real name: <PROJECT>_dbdata
# fix the line: - dbdata:/var/lib/mysql
docker compose up -d
```

Then delete the orphans and add backups (N2).

S3(unreachable links and browser security warning behind the https load balancer):
nginx.conf-lines 5-9 
```
server {
  location / {
    proxy_pass http://app:8000;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 90s;
  }
}
```
The location block has no `proxy_set_header Host` / `X-Forwarded-*` lines

nginx sends no `Host` or `X-Forwarded-Proto`. It forwards the default `Host: app:8000`, so the app builds absolute urls `http://app:8000/...` — a docker-internal name on a port never published, so the browser cannot reach them. TLS ends at the LB; without `X-Forwarded-Proto: https` the app believes it serves plain http and is available at `http://` urls onto an https page — mixed content, the security warning.

To confirm this i would run

```
curl -sI -H 'Host: grants.district.example.gov.in' http://127.0.0.1/login | grep -i '^location'   # → http://app:8000/...
docker compose logs app | grep -o 'http://app:8000[^ "]*' | head
```

The fix would be to add to the location block:

```
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Host $host;
```

plus telling the app to trust them (Django `SECURE_PROXY_SSL_HEADER`, Flask `ProxyFix`).

S4(app starts unable to reach the database on roughly one reboot in three):
docker-compose.yml-lines 15-16

```
app:
  depends_on:
    - db
```

The short form orders container start, not MariaDB readiness. If the app's one connection attempt at boot loses the race, it runs broken — the container is up, so restart: unless-stopped never fires — until someone restarts it by hand. A race, so only ~1 boot in 3.

To confirm this i would run

```
docker compose config | grep -A3 healthcheck   # → nothing defined
docker compose logs -t db  | grep -m1 'ready for connections'
docker compose logs -t app | grep -m1 -i "can't connect"   # on a bad boot this predates the db ready line
```

The fix would be:

```
db:
  healthcheck:
    test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
    interval: 10s
    retries: 5
app:
  depends_on:
    db:
      condition: service_healthy
```

plus connection retry-with-backoff in the app.

N1(database root password committed to git history — explains none of S1-S4):
not a line — .env is recoverable from every commit between 3 and 8; deleting it in commit 9 removed nothing, and the db listens on 127.0.0.1:3306.

To confirm this i would run `git log --all --oneline -- .env` then `git show <commit-3-to-8>:.env` — it prints the password.

The fix would be to rotate the password inside the container (changing the env var does not change an already-initialised DB), update the server's .env, gitignore it, and optionally purge history with `git filter-repo --invert-paths --path .env`.

N2(no database backups — explains none of S1-S4):
not a line — no dump job exists for the database; this turned S2 from 'restore from last night' into 'all data gone'.

To confirm this i would run `crontab -l; systemctl list-timers | grep -i backup` — nothing references the database.

The fix would be a nightly `docker compose exec db mariadb-dump --single-transaction appdb` shipped off the server, with restores rehearsed.
