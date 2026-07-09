# Deployment guide

Production/Dev setup for **odil-timel-mini-Label-Studio**: a Linux server running the
app under [gunicorn](https://gunicorn.org/) (WSGI), supervised by
[supervisor](http://supervisord.org/), reverse-proxied by
[nginx](https://nginx.org/), with automated SQLite backups via `cron`.

This guide assumes a Debian/Ubuntu-like server with `sudo` access. Adjust
paths/users for your distribution as needed.

## 1. System packages (be careful!)

check system packages 

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip sqlite3 nginx supervisor git
```

## 2. Go to /srv/webapps

## 3. Get the code

```bash
sudo -u timel git clone <repo-url>
cd timel-annotation-studio
```

## 4. Python environment (pip)

The project is developed with [`uv`](https://docs.astral.sh/uv/), but
deployment only needs plain `pip` and the pinned `requirements.txt`
(exported from `uv.lock`, includes `gunicorn`):

```bash
sudo python3 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install -r requirements.txt
```

To regenerate `requirements.txt` after a dependency change (from a dev
machine with `uv`):

```bash
uv export --no-dev --no-hashes --format requirements-txt > requirements.txt
echo "gunicorn==23.0.0  # production WSGI server (see DEPLOY.md)" >> requirements.txt
```

## 5. Environment variables to fill in

```bash
sudo cp .env.example .env
sudo chmod 600 .env
```

Edit `/opt/timel-annotation-studio/.env` and set at least:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. Must **not** be left at `dev-secret` — the app refuses to start otherwise. |
| `APP_PASSWORD` | The shared password annotators use to log in. Required. |
| `IMAGE_ENDPOINT` | IIIF server base URL, e.g. `https://iiif.chartes.psl.eu/images/ahloma_images/`. |
| `DB_PATH` | Absolute path recommended in production, e.g. `/opt/timel-annotation-studio/data/timel_reconcile.sqlite`. |
| `TAXO_PATH` / `CSV_TSV_PATH` / `FILENAME_MAP_PATH` | Verify these input data files were deployed under `data/` (they're not committed if large — copy them onto the server separately if so). |
| `IMAGES_ROOT` | Optional; only needed if some images must be served locally instead of via `IMAGE_ENDPOINT`. |

See the [Configuration](README.md#configuration) section of the README for
the full variable reference and defaults.

The SQLite database and its parent directory are created automatically on
first run (`init_db`); just make sure `data/` is writable by the `timel`
user:

```bash
sudo -u timel mkdir -p /opt/timel-annotation-studio/data
```

## 6. WSGI entry point

`app.py` exposes an application **factory** (`create_app()`), not a
module-level `app`. `wsgi.py` (already in the repo) wraps it for gunicorn:

```python
from app import create_app

app = create_app()
```

Sanity-check it manually before wiring up supervisor:

```bash
cd /timel-annotation-studio
sudo -u timel .venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
# Ctrl+C once you've confirmed http://127.0.0.1:8000/login responds
```

## 7. Supervisor

Create `/etc/supervisor/conf.d/timel-annotation-studio.conf`:

```ini
[program:timel-annotation-studio]
directory=/srv/webapps/timel-annotation-studio
command=/srv/webapps/timel-annotation-studio/.venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 wsgi:app
user=timel
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stdout_logfile=/var/log/timel-annotation-studio/app.out.log
stderr_logfile=/var/log/timel-annotation-studio/app.err.log
```

```bash
sudo mkdir -p /var/log/timel-annotation-studio
sudo chown timel:timel /var/log/timel-annotation-studio

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status timel-annotation-studio
```

Useful `supervisorctl` commands for day-to-day operations:

```bash
sudo supervisorctl restart timel-annotation-studio   # after a deploy/config change
sudo supervisorctl stop timel-annotation-studio
sudo supervisorctl tail -f timel-annotation-studio    # follow stdout log
```

## 8. Nginx reverse proxy

Create `/etc/nginx/sites-available/timel-annotation-studio`:

```nginx
server {
    listen 80;
    server_name timel.example.org;

    client_max_body_size 20m;  # export ZIP downloads

    location /static/ {
        alias /opt/timel-annotation-studio/static/;
    }
    location /assets/ {
        alias /opt/timel-annotation-studio/assets/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/timel-annotation-studio /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Put TLS in front of this (e.g. `certbot --nginx`) before exposing the app
publicly — `APP_PASSWORD` is a single shared secret sent over plain HTTP
otherwise.

## 9. Cron backup script

`scripts/backup_db.sh` rotates SQLite backups (keeps the 2 most recent,
see the README's [Automatic database backups](README.md#automatic-database-backups)
section). Install it in the `timel` user's crontab:

```bash
sudo crontab -u timel -e
```

Add (Friday 8pm, adjust as needed):

```cron
0 20 * * 5 /opt/timel-annotation-studio/scripts/backup_db.sh >> /var/log/timel-annotation-studio/backup.log 2>&1
```

`scripts/backup_db.sh` picks up `DB_PATH`/`BACKUP_DIR`/`MAX_BACKUPS` from
`.env`/`.dev.env` automatically; no extra environment setup needed for cron.

## 10. Post-deploy checklist

- [ ] `sudo supervisorctl status timel-annotation-studio` shows `RUNNING`
- [ ] `https://timel.example.org/login` loads and accepts `APP_PASSWORD`
- [ ] `/correction` and `/table` load with real data (taxonomy, input CSV present under `data/`)
- [ ] Images render (check both the IIIF endpoint and, if configured, the local `IMAGES_ROOT` fallback)
- [ ] Export ZIP downloads and contains all three files
- [ ] `sudo -u timel /opt/timel-annotation-studio/scripts/backup_db.sh` runs cleanly and creates a file under `data/backups/`
- [ ] Cron entry present: `sudo crontab -u timel -l`

## Updating a deployment

```bash
cd /opt/timel-annotation-studio
sudo -u timel git pull
sudo -u timel .venv/bin/pip install -r requirements.txt
sudo supervisorctl restart timel-annotation-studio
```
