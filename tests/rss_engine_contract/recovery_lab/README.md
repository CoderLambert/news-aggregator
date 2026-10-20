# Isolated channel recovery fixture

This fixture uses only synthetic users/data and a disposable PostgreSQL tmpfs.
Use a fresh local Docker project; never point it at an existing Miniflux/DB.
No production settings, tokens or databases are required.

From this directory, create a task-local TLS certificate (never commit certs):

```sh
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/key.pem -out certs/ca.pem \
  -days 2 -subj /CN=fixture.example -addext subjectAltName=DNS:fixture.example
```

Choose a new `newshub-rss-recovery-<unique>` project and verify it has no existing
containers/network. Start `compose.yaml` with `up -d --wait`. Run
`tests/rss_engine_contract/live_admin_recovery.py` in a compatible Python 3.12
NewsHub image on that project's default network, with the repository mounted at
`/work` and these synthetic-only variables:

```text
PYTHONPATH=backend:crawler
DJANGO_SETTINGS_MODULE=newsaggregator.settings
DJANGO_ENV=development
DJANGO_DB_PATH=/tmp/live-recovery.sqlite3
RUN_MAIN=true
RSS_RECOVERY_LIVE=synthetic-isolated
```

The script migrates its disposable app DB, creates a new non-admin collector,
and proves create, reuse of old unknown, and final parse-failure behavior.
Remove only this freshly named project using `down --volumes --remove-orphans`.
The `FETCHER_ALLOW_PRIVATE_NETWORKS` exception and synthetic TLS trust belong
only to this fixture; neither is an application/deployment recommendation.
