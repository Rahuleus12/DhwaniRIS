C1(allocating the 4 GB):
docker-compose.yml — not a line: no service in the file carries a memory limit, so everything shares the 4 GB unplanned.

The figures i would allocate: os + docker 400M — takes what it needs, db 1.2G with innodb_buffer_pool_size = 1G; redis 200M with maxmemory 150mb; nginx 64M; app 1.5G for 4 gunicorn workers and 2 background workers; ~600M headroom for stability. Without limits the services run into out of memory errors at random, with them a we lose one service, not all of them at once.

To confirm this i would run

```
free -m                                            # → 'available' under ~600M at month-end = too tight
docker stats --no-stream                           # → which container rides its limit
docker events --since 24h --filter event=die | grep exitCode=137   # → OOM kills: the allocation is wrong
```

The fix would be:

```
services:
  db:
    deploy:
      resources:
        limits: {memory: 1.2g}      # plus --innodb-buffer-pool-size=1G
  redis:
    deploy:
      resources:
        limits: {memory: 200m}      # plus maxmemory 150mb
  nginx:
    deploy:
      resources:
        limits: {memory: 64m}
  app:
    deploy:
      resources:
        limits: {memory: 1.5g}
```

When it proves too tight the first thing i would cut is the web workers, 4 to 2 — each is a full Python process, that frees about 500M and 2 still serve 40 users. The cache is next, the buffer pool last: shrink it and every query slows. The symptom of a wrong allocation is S1's: containers die with exit 137 and restart, logs clean.

C2(backups i would rely on):
not a line — no dump job exists; the only copy of the data is the live database on this one VM.

The arrangement: nightly at 01:00 a `mariadb-dump --single-transaction appdb` — no lock, the app stays up — gzipped to /var/backups beside a tar of the files dir and site_config.json (uploads and secrets live on disk, not in the db). At 01:30 rsync both off the VM to the department's file server; a copy on the same disk as the database is not a backup. Retention: 7 dailies on the VM (80 GB disk), 30 dailies plus every month-end dump off it, kept for the audit. RPO 24 hours, RTO 4 hours — rebuild the VM, load the dump, copy the files, `up -d`.

To confirm this i would run — a dump can lie: it runs, exits 0, holds half the rows — the 02:00 check:

```
docker run -d --name verify -e MARIADB_ROOT_PASSWORD=x mariadb:11
zcat /var/backups/appdb-$(date +%F).sql.gz | docker exec -i verify mariadb appdb    # loads, or dies loudly
docker exec verify mariadb -N -e 'SELECT COUNT(*) FROM appdb.beneficiary'           # → one number
docker compose exec db mariadb -N -e 'SELECT COUNT(*) FROM appdb.beneficiary'       # → must match; script mails me both
```

The fix would be the cron that makes it routine:

```
0  1 * * *  docker compose exec -T db mariadb-dump --single-transaction appdb | gzip > /var/backups/appdb-$(date +\%F).sql.gz && tar czf /var/backups/files-$(date +\%F).tgz <sites>/public/files <sites>/site_config.json
30 1 * * *  rsync -a /var/backups/ backup@datacentre:/srv/grants-backups/
0  2 * * *  /usr/local/bin/verify-restore.sh    # the block above; a mismatch mails me
```

One morning a week i also load a dump on my laptop, log in, open a record. A backup never restored is a guess.

C3(reply to the junior):
sent at 15:04 —

> "The schema migration is ready. I'll run it on production now, it only takes
> a few minutes. I took a backup this morning, so if anything breaks we just
> restore it and we're back to normal."

No. Three problems.

The backup is six hours old at 3 PM. Staff have keyed records since 9. A restore drops every one of them — a hard delete at scale, which audit forbids. The morning dump does not save you.

"A few minutes" is your timing on a test database. The migration locks and rebuilds tables while 40 users work. At 3 PM you hang the department; at month-end you hang it at its busiest hour.

If it dies halfway you are left half-migrated, and your only fix is the stale restore. That is problem one again, at five, with everyone gone home.

See it yourself before touching production:

```
ls -l --time-style=+%T /var/backups/appdb-*.sql.gz | tail -1                                                # → 09:0x, six hours stale
docker compose exec db mariadb -N -e "SELECT COUNT(*) FROM appdb.beneficiary WHERE created_at > CURDATE()"  # → the rows a restore wipes
```

Today we rehearse on a scratch copy — last night's dump, migration, real duration, real errors. Tonight at 20:00: maintenance page up, fresh dump, migrate, smoke test — login, one beneficiary record. Page off only when that passes. The rollback is the dump taken minutes before, never this morning's.

C4(deployment without a second server):
No. Zero downtime would not be recommended on this setup as a server restart would be a necessity. Best possible arrangement would be to restart the server later in the night at around 2 AM so the least amount of people would be affected. Almost nobody uses the system overnight, and the district links already drop for minutes at a time, so a short planned gap sits inside what users tolerate today.

The restart takes minutes, not hours. The arrangement:

```
day before   users told: maintenance at 2 AM, a few minutes
01:55        maintenance page on (nginx 503, plain page); fresh dump taken
02:00        pull the new images; docker compose up -d; run migrations
             smoke test: login, one beneficiary record, one report
02:05        page off — or, on failure: previous images back up, restore the dump if the schema moved
```

The window is 2 to 5 minutes behind a page that says "back shortly", not behind errors. I run the whole thing over ssh; nobody on site types anything. If the smoke test fails, the old version is back before the offices open.

What this does not cover: if the VM itself dies, downtime is the RTO from C2 — 4 hours, not minutes. A migration the rehearsal says is too long for the window moves to a weekend, announced a week ahead.

What i would tell the department: "Zero downtime needs a second server — that is next year's budget. What you get now is a few planned minutes at 2 AM, announced a day ahead, with a tested way back."
