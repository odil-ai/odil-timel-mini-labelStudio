# O.D.I.L. Timel mini Label Studio

Web Application for reconciling and correcting annotations from GAHOM/AHLOMA (EHESS), based on the TIMEL thesaurus, as part of the O.D.I.L. project.

## Description

The tool lets annotators review automatic reconciliations between "orphan labels" (terms not covered by a reference vocabulary) and entries in the **TIMEL** taxonomy (`TM-XXXXX` identifiers). For each entry, an annotator can:

- confirm or correct the suggested TIMEL identifier (via a taxonomy search)
- exclude irrelevant images associated with the entry
- validate the decision to mark it as processed
- export a CSV snapshot of every decision, the action log, and a per-image validated-annotations JSON

## Requirements

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (recommended package manager)

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd timel-annotation-studio

# Create the virtual environment and install dependencies
uv sync
```

## Configuration

Copy the example file and fill in the values:

```bash
cp .env.example .env
```

Two files are recognized, both ignored by git (`.gitignore`) since they hold secrets:

- **`.env`**: base/reference configuration (shared / deployment).
- **`.dev.env`** *(optional)*: local developer override: if present, its values take precedence over `.env` for the same keys.

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | `dev-secret` (must be changed in prod) |
| `APP_PASSWORD` | Single shared password gating access to the app | _(empty : required)_ |
| `IMAGES_ROOT` | Root path to local images (optional fallback when `IMAGE_ENDPOINT`/the filename mapping doesn't cover an image) | _(empty : fallback disabled)_ |
| `TAXO_PATH` | Path to the taxonomy JSON file | `data/timel-taxonomy_enriched.json` |
| `DB_PATH` | Path to the SQLite decisions database | `data/timel_reconcile.sqlite` |
| `CSV_TSV_PATH` | Path to the input data file | `data/reconcile_timel_prepared.csv` |
| `FILENAME_MAP_PATH` | Path to the old/new image filename mapping TSV | `data/mapping_old_new_img_filename.tsv` |
| `IMAGE_ENDPOINT` | Base URL of the IIIF server serving images (new filename + `/full/full/0/default.jpg`) | `https://iiif.chartes.psl.eu/images/ahloma_images/` |
| `EXPORT_SNAPSHOT` | Filename for the decisions CSV export | `export_snapshot.csv` |
| `EXPORT_LOG` | Filename for the action log CSV export | `export_log.csv` |

A variable that is present but left empty (e.g. `DB_PATH=`) falls back to its default instead of resolving to an empty string.

## Troubleshooting: "connection refused" / the app won't start

If the browser shows a connection error ("can't reach this site", connection refused) instead of the login page, it's almost always because the Flask server crashed on startup. `app.py` checks at launch that `SECRET_KEY` and `APP_PASSWORD` are set and raises a `RuntimeError` otherwise — check the terminal running `uv run python app.py`, the error message appears there.

Common causes:

- **The `.env`/`.dev.env` files are missing or were reset.** They're intentionally excluded from git (`.gitignore`) since they hold secrets: a fresh `git clone`, an accidental `cp .env.example .env` overwriting yours, or a working-directory cleanup silently removes them.
- **`SECRET_KEY` is still `dev-secret`** (the default in `config.py`) or empty.
- **`APP_PASSWORD` is empty.**

How to avoid it:

1. Check that `.env` (and/or `.dev.env`) exists at the project root and contains real values for `SECRET_KEY` and `APP_PASSWORD` (not the placeholders from `.env.example`).
2. Keep a backup copy of your `.env`/`.dev.env` files outside the repo (secrets manager, local vault, etc.) since they aren't versioned and no other copy exists if you lose them.
3. After any `git clone` or environment reset, only re-run `cp .env.example .env` **if the file doesn't already exist**, then fill in the real values before starting the app.

## Running the app

```bash
# Development mode
uv run python app.py
```

```bash
# Via the Flask CLI
uv run flask --app app run --debug
```

The app is available at: `http://127.0.0.1:5000`

For a production setup (systemd/supervisor + nginx + cron backups), see [DEPLOY.md](DEPLOY.md).

## Resetting the decisions database

To start over (deletes **all** decisions and the action log, irreversible):

```bash
uv run flask --app app reset-db
```

A confirmation prompt is shown before deleting; use `--yes` to automate it (e.g. in a script):

```bash
uv run flask --app app reset-db --yes
```

If the app is already running (including `--debug`), restart it after a `reset-db`: its in-memory cache still holds the old decisions until a write invalidates it.

## Automatic database backups

`scripts/backup_db.sh` backs up `data/timel_reconcile.sqlite` (via `sqlite3 .backup`, safe even while the app is running) into `data/backups/`, with the date/time in the filename. It keeps only the **2 most recent backups**: on every run, the oldest one is deleted if needed.

```bash
./scripts/backup_db.sh
```

Overridable variables (environment, `.dev.env` or `.env`): `DB_PATH`, `BACKUP_DIR` (default `data/backups`), `MAX_BACKUPS` (default `2`).

To automate it weekly via cron (e.g. Friday at 8pm, around deployment time):

```cron
0 20 * * 5 /path/to/timel-annotation-studio/scripts/backup_db.sh >> /var/log/timel_backup.log 2>&1
```

## Usage

1. Go to [http://127.0.0.1:5000](http://127.0.0.1:5000): the login page appears
2. Enter the password configured in `APP_PASSWORD`
3. Navigate the views:
   - **Correction** (`/correction`): row-by-row review, with filters by taxonomy branch, confidence level and status
   - **Table** (`/table`): tabular view with full-text search and filters
4. To export decisions: the **Export** button in the interface then downloads a `.zip` containing:
   - `export_snapshot.csv`: every decision (one row per orphan label)
   - `export_log.csv`: chronological action log (`set_final`, `validate`, `set_exclusions`)
   - `validated_annotations.json`: validated annotations aggregated **per image** (`sha`, `gahom_filename`, `odil_filename`, `validated_annotations` with `timel_id`/`timel_label`, `free_labels` for free-text validations, plus `total_images`/`total_validated_annotations` totals)

## Development

Code style and linting are handled by [ruff](https://docs.astral.sh/ruff/) (installed as a dev dependency):

```bash
uv run ruff check .     # lint
uv run ruff format .    # format
```

Configuration lives in `[tool.ruff]` in `pyproject.toml`.

## Project structure

```
timel-annotation-studio/
├── app.py                          # Flask application (routes)
├── wsgi.py                         # Production WSGI entry point (gunicorn), see DEPLOY.md
├── config.py                       # Configuration from environment variables
├── .env.example                    # Configuration template (copy to .env)
├── .env                            # Actual configuration (not versioned)
├── .dev.env                        # Optional local dev override (not versioned)
├── pyproject.toml                  # Project metadata + ruff configuration
├── requirements.txt                # Pinned deps for pip-based deployment, see DEPLOY.md
├── DEPLOY.md                       # Production deployment guide (gunicorn/nginx/supervisor/cron)
├── services/
│   ├── db.py                       # SQLite layer (decisions, action log)
│   └── data.py                     # Data loading, taxonomy search
├── templates/
│   ├── base.html                   # Base template
│   ├── login.html                  # Login page
│   ├── correction.html             # Correction view (row by row)
│   └── table.html                  # Table view
├── static/
│   ├── app.js                      # Frontend logic (theme, UI)
│   └── app.css                     # Styles
├── assets/                         # Institutional logos (ENC-PSL, EHESS, Biblissima, ODIL)
├── scripts/
│   └── backup_db.sh                # Rotating SQLite backup (cron)
└── data/
    ├── reconcile_timel_prepared.csv        # Input data (TSV)
    ├── timel-taxonomy_enriched.json        # TIMEL taxonomy
    ├── mapping_old_new_img_filename.tsv    # Old (gahom) / new (ODIL/IIIF) image filename mapping
    ├── timel_reconcile.sqlite              # Decisions database (generated at startup)
    └── backups/                            # Timestamped backups (generated, not versioned)
```

## License

Released under the [MIT License](LICENSE).

## Citation

See [CITATION.cff](CITATION.cff) for citation metadata.

## Credits

Developed by the **École Nationale des Chartes – PSL**.

- EHESS / Ahloma
- Biblissima+
