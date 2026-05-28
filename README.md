# BookGrab

`BookGrab` is a small self-hosted web app for **manual** searching across configured sources and sending selected audiobook/e-book torrents to qBittorrent.

> _Built with AI assistance._

## What it does

- Serves a single FastAPI app (UI + backend API).
- Queries a configured private source JSON search endpoint through the backend.
- Shows normalized results in a simple web UI.
- Lets you click **Add** on one result.
- Downloads `.torrent` files server-side using configured source auth cookies/session values.
- Uploads torrents to qBittorrent Web API with category/savepath mapping.
- Writes basic add history to `/config/app.db`.

- Optional library presence checks (Plex and/or Audiobookshelf) for search results (disabled by default).

## What it does NOT do

- Not a Readarr/Sonarr replacement.
- No monitoring, upgrades, library management, metadata matching, import/rename, or Calibre integration.
- Optional completed-download hardlink importer for BookGrab-added torrents (disabled by default).

## Security warning

Do not expose this app directly to the internet unless it is protected by strong authentication and HTTPS through a trusted reverse proxy.

## Usage / Etiquette

BookGrab is intended for personal use only by users running their own instance with their own MAM account/session. It is not affiliated with MAM. It does not provide a hosted service, shared access, automation for mass downloading, ratio avoidance, or account sharing. Use it responsibly and follow MAM rules.

## Quick start

1. Copy env file:
   ```bash
   cp .env.example .env
   ```
2. Fill in `.env` values (especially source auth + qBittorrent auth).
3. Build + run:
   ```bash
   docker compose up -d --build
   ```
4. Open `http://localhost:8787`.

## File tree

```text
BookGrab/
  app/
    __init__.py
    config.py
    db.py
    main.py
    mam.py
    models.py
    qbittorrent.py
    templates/index.html
    static/app.js
    static/style.css
  tests/test_mam_normalize.py
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  .gitignore
  README.md
```

## Environment variables

See `.env.example` for full list.

Important:
- Fill source authentication variables in `.env` so backend source requests are authenticated.
  - MAM_COOKIE=mam_id=very-long-string
  - In MAM, create a new session consistent with your settings for hosting the app. Copy only the token value and set `MAM_COOKIE=mam_id=<token>` (or put the bare token in `MAM_UID`). Never share this value.
- Fill `QBIT_*` values to match your qBittorrent instance.
- Set `PUID`/`PGID` to match the host user/group that owns your bind-mounted `config` directory (defaults are `1000:1000`).

- Optional library-presence checks for audiobooks:
  - Enable Plex with `PLEX_ENABLED=true` and `PLEX_*` settings
  - Enable Audiobookshelf with `AUDIOBOOKSHELF_ENABLED=true` and `AUDIOBOOKSHELF_*` settings
  - You can enable both at once; results are marked `In library` if any provider matches based on `LIBRARY_PRESENCE_REQUIRE_NARRATOR`
  - `LIBRARY_PRESENCE_REQUIRE_NARRATOR=true` (default): require title + author + narrator overlap; missing narrator on either side does not match
  - `LIBRARY_PRESENCE_REQUIRE_NARRATOR=false`: require title + author only (narrator ignored)
- `PUID`/`PGID` are applied at container startup, so changing them in `.env` works even without rebuilding an existing image.

## Source auth notes

- The app supports a raw cookie string for authenticated source requests.
- If raw cookie auth is empty, it can construct cookies from separate ID/session fields.
- Secrets stay server-side and are never returned to frontend responses.


## Source API compatibility

The search client is implemented to match the documented JSON style from your provided API screenshots:
- endpoint: `/tor/js/loadSearchJSONbasic.php`
- payload shape uses `tor.text`, `tor.srchIn` (array of fields), `tor.searchType`, `tor.sortType`, `tor.startNumber`, and `tor.main_cat`
- response parsing expects `data` as a list and supports people fields that may arrive as JSON-encoded id:name objects

## qBittorrent setup

Suggested categories:
- `audiobooks`
- `ebooks`

Optionally set save paths with:
- `QBIT_SAVE_PATH_AUDIOBOOKS`
- `QBIT_SAVE_PATH_EBOOKS`

## API routes

- `GET /` UI
- `POST /login`
- `POST /logout`
- `GET /api/health`
- `POST /api/search`
- `POST /api/add`

## Troubleshooting

- **Source auth expired**: refresh source auth cookie/session values and restart container.
- **qBittorrent login failed**: verify `QBIT_BASE_URL`, username/password, and Web UI API availability.
- **No results**: confirm query, media type, and active source authentication.
- **Torrent already exists**: qBittorrent may reject duplicates; this is expected.
- **Category/save path issues**: verify categories exist in qBittorrent and save path is writable.

## Troubleshooting: sqlite3.OperationalError: unable to open database file

If you see SQLite startup errors, the container user cannot write to `/config` (where `DATABASE_PATH` defaults to `/config/app.db`).

On the host:

```bash
cd /path/to/bookgrab
mkdir -p config
sudo chown -R 1000:1000 config
chmod -R u+rwX,g+rwX config
docker compose down
docker compose up -d --build
docker compose logs -f
```

On some NAS systems (including TerraMaster), bind-mounted folders may be created as `root` or another system user. The `config` folder must be writable by the container user (`1000:1000` in this image).

If you see a Compose warning like `The "iP" variable is not set`, check your local `.env` for `$iP` references and replace them with `${IP}` (uppercase), then define `IP=...` in `.env`.

## Local checks

```bash
python -m compileall app
pytest
docker build -t BookGrab:local .
```

## Assumptions

- Configured source search endpoint accepts JSON payload as implemented.
- Source response includes expected `data` list and download-hash field.
- qBittorrent Web API v2 endpoints are reachable from container.


## Optional completed-download importer

Set `IMPORT_ENABLED=true` to enable a background polling importer that watches BookGrab-added torrents and hardlinks supported completed files into configured library paths.

- Mode currently supports `hardlink` only.
- Import is idempotent and does not move/delete/pause/remove torrents.
- Source files remain in the qBittorrent download location for continued seeding.

### Docker Compose example (BookGrab + qBittorrent)

```yaml
services:
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:latest
    container_name: qbittorrent
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Los_Angeles
      - WEBUI_PORT=8080
    volumes:
      - /Volume2/Media:/downloads
    ports:
      - 8080:8080
    restart: unless-stopped
  bookgrab:
    image: ghcr.io/pitchy3/bookgrab:latest
    container_name: bookgrab
    env_file:
      - .env
    depends_on:
      - qbittorrent
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/Los_Angeles
      # qBittorrent connection
      - QBIT_BASE_URL=http://192.168.0.99:8080
      - QBIT_USERNAME=username
      - QBIT_PASSWORD=password
      # Optional categories
      - QBIT_CATEGORY_AUDIOBOOKS=audiobooks
      - QBIT_CATEGORY_EBOOKS=ebooks
      # MUST match qBittorrent's internal save path
      - QBIT_SAVE_PATH_AUDIOBOOKS=/downloads/torrents
      - QBIT_SAVE_PATH_EBOOKS=/downloads/torrents
      # Import settings
      - IMPORT_ENABLED=true
      - IMPORT_MODE=hardlink
      - IMPORT_AUDIOBOOK_LIBRARY_PATH=/downloads/Audiobooks/BookGrab
      - IMPORT_EBOOK_LIBRARY_PATH=/downloads/ebooks/BookGrab
    volumes:
      - ./config:/config
      - /Volume2/Media:/downloads
    ports:
      - 127.0.0.1:8787:8787
    restart: unless-stopped
```

To access BookGrab from another device on your LAN, intentionally change this to `8787:8787` or place it behind a trusted reverse proxy with HTTPS and strong authentication. Do not expose it directly to the internet.

Important limitations:
- Hardlinks require source and destination to be on the same filesystem.
- BookGrab must see the same download path qBittorrent reports.
- If qBittorrent reports `/downloads/book/file.m4b`, BookGrab must also see `/downloads/book/file.m4b`.
- If qBittorrent and BookGrab containers use different internal paths, align mounts so paths match.
