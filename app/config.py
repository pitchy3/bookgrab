from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

MAM_HASH_LOOKUP_SCOPES = {"mam_only", "category", "bookgrab", "all"}


def parse_csv(value: str, *, lowercase: bool = False) -> list[str]:
    values = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        values.append(item.lower() if lowercase else item)
    return values


def parse_mam_hash_lookup_scope(value: str) -> str:
    scope = value.strip().lower()
    if scope not in MAM_HASH_LOOKUP_SCOPES:
        allowed = ", ".join(sorted(MAM_HASH_LOOKUP_SCOPES))
        raise RuntimeError(f"MAM_HASH_LOOKUP_SCOPE must be one of: {allowed}")
    return scope


@dataclass(init=False)
class Settings:
    app_auth_enabled: bool
    app_username: str
    app_password: str
    app_session_secret: str
    mam_base_url: str
    mam_cookie: str
    mam_uid: str
    mam_session: str
    mam_timeout_seconds: int
    mam_hash_lookup_enabled: bool
    mam_hash_lookup_delay_seconds: float
    mam_hash_lookup_max_per_run: int
    mam_hash_lookup_cache_ttl_days: int
    mam_hash_lookup_retry_error_ttl_hours: int
    mam_hash_lookup_no_match_ttl_days: int
    mam_hash_lookup_cron_enabled: bool
    mam_hash_lookup_cron: str
    mam_hash_lookup_cron_timezone: str
    mam_hash_lookup_scope: str
    mam_tracker_hosts: list[str]
    mam_hash_lookup_include_categories: list[str]
    qbit_base_url: str
    qbit_username: str
    qbit_password: str
    qbit_category_audiobooks: str
    qbit_category_ebooks: str
    qbit_save_path_audiobooks: str
    qbit_save_path_ebooks: str
    default_media_type: str
    default_sort: str
    default_search_type: str
    search_cache_ttl_seconds: int
    search_cache_max_entries: int
    plex_enabled: bool
    plex_base_url: str
    plex_token: str
    plex_library_section_id: str
    plex_library_name: str
    audiobookshelf_enabled: bool
    audiobookshelf_base_url: str
    audiobookshelf_token: str
    audiobookshelf_library_id: str
    library_presence_cache_ttl_seconds: int
    library_presence_require_narrator: bool
    config_dir: str
    database_path: str
    import_enabled: bool
    import_interval_seconds: int
    import_mode: str
    import_conflict_policy: str
    import_audiobook_library_path: str
    import_ebook_library_path: str
    import_audiobook_extensions: str
    import_ebook_extensions: str
    import_min_completion_ratio_legacy_present: bool
    import_require_seeding_or_complete: bool
    import_dry_run: bool
    import_allowed_download_roots: str

    def __init__(self) -> None:
        self.app_auth_enabled = os.getenv("APP_AUTH_ENABLED", "true").lower() == "true"
        self.app_username = os.getenv("APP_USERNAME", "admin")
        self.app_password = os.getenv("APP_PASSWORD", "change-me")
        self.app_session_secret = os.getenv("APP_SESSION_SECRET", secrets.token_urlsafe(32))

        self.mam_base_url = os.getenv("MAM_BASE_URL", "https://www.myanonamouse.net").rstrip("/")
        self.mam_cookie = os.getenv("MAM_COOKIE", "")
        self.mam_uid = os.getenv("MAM_UID", "")
        self.mam_session = os.getenv("MAM_SESSION", "")
        self.mam_timeout_seconds = int(os.getenv("MAM_TIMEOUT_SECONDS", "30"))
        self.mam_hash_lookup_enabled = os.getenv("MAM_HASH_LOOKUP_ENABLED", "false").lower() == "true"
        self.mam_hash_lookup_delay_seconds = max(float(os.getenv("MAM_HASH_LOOKUP_DELAY_SECONDS", "10")), 0.0)
        self.mam_hash_lookup_max_per_run = max(int(os.getenv("MAM_HASH_LOOKUP_MAX_PER_RUN", "100")), 0)
        self.mam_hash_lookup_cache_ttl_days = max(int(os.getenv("MAM_HASH_LOOKUP_CACHE_TTL_DAYS", "30")), 1)
        self.mam_hash_lookup_retry_error_ttl_hours = max(int(os.getenv("MAM_HASH_LOOKUP_RETRY_ERROR_TTL_HOURS", "24")), 1)
        self.mam_hash_lookup_no_match_ttl_days = max(int(os.getenv("MAM_HASH_LOOKUP_NO_MATCH_TTL_DAYS", "30")), 1)
        self.mam_hash_lookup_cron_enabled = os.getenv("MAM_HASH_LOOKUP_CRON_ENABLED", "false").lower() == "true"
        self.mam_hash_lookup_cron = os.getenv("MAM_HASH_LOOKUP_CRON", "")
        self.mam_hash_lookup_cron_timezone = os.getenv("MAM_HASH_LOOKUP_CRON_TIMEZONE", os.getenv("TZ", "UTC"))
        self.mam_hash_lookup_scope = parse_mam_hash_lookup_scope(os.getenv("MAM_HASH_LOOKUP_SCOPE", "mam_only"))
        self.mam_tracker_hosts = parse_csv(os.getenv("MAM_TRACKER_HOSTS", "myanonamouse.net,www.myanonamouse.net"), lowercase=True)

        self.qbit_base_url = os.getenv("QBIT_BASE_URL", "http://qbittorrent:8080").rstrip("/")
        self.qbit_username = os.getenv("QBIT_USERNAME", "admin")
        self.qbit_password = os.getenv("QBIT_PASSWORD", "")
        self.qbit_category_audiobooks = os.getenv("QBIT_CATEGORY_AUDIOBOOKS", "audiobooks")
        self.qbit_category_ebooks = os.getenv("QBIT_CATEGORY_EBOOKS", "ebooks")
        self.qbit_save_path_audiobooks = os.getenv("QBIT_SAVE_PATH_AUDIOBOOKS", "")
        self.qbit_save_path_ebooks = os.getenv("QBIT_SAVE_PATH_EBOOKS", "")
        if "MAM_HASH_LOOKUP_INCLUDE_CATEGORIES" in os.environ:
            self.mam_hash_lookup_include_categories = parse_csv(os.getenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", ""))
        else:
            self.mam_hash_lookup_include_categories = parse_csv(
                f"{self.qbit_category_audiobooks},{self.qbit_category_ebooks}"
            )

        self.default_media_type = os.getenv("DEFAULT_MEDIA_TYPE", "audiobook")
        self.default_sort = os.getenv("DEFAULT_SORT", "seedersDesc")
        self.default_search_type = os.getenv("DEFAULT_SEARCH_TYPE", "active")
        self.search_cache_ttl_seconds = max(int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "1800")), 1)
        self.search_cache_max_entries = max(int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "200")), 1)

        self.plex_enabled = os.getenv("PLEX_ENABLED", "false").lower() == "true"
        self.plex_base_url = os.getenv("PLEX_BASE_URL", "http://plex:32400").rstrip("/")
        self.plex_token = os.getenv("PLEX_TOKEN", "")
        self.plex_library_section_id = os.getenv("PLEX_LIBRARY_SECTION_ID", "")
        self.plex_library_name = os.getenv("PLEX_LIBRARY_NAME", "Audiobooks")
        self.audiobookshelf_enabled = os.getenv("AUDIOBOOKSHELF_ENABLED", "false").lower() == "true"
        self.audiobookshelf_base_url = os.getenv("AUDIOBOOKSHELF_BASE_URL", "").rstrip("/")
        self.audiobookshelf_token = os.getenv("AUDIOBOOKSHELF_TOKEN", "")
        self.audiobookshelf_library_id = os.getenv("AUDIOBOOKSHELF_LIBRARY_ID", "")

        self.library_presence_cache_ttl_seconds = max(int(os.getenv("LIBRARY_PRESENCE_CACHE_TTL_SECONDS", "600")), 1)
        self.library_presence_require_narrator = os.getenv("LIBRARY_PRESENCE_REQUIRE_NARRATOR", "true").lower() == "true"

        self.config_dir = os.getenv("CONFIG_DIR", "/config")
        self.database_path = os.getenv("DATABASE_PATH", "/config/app.db")

        self.import_enabled = os.getenv("IMPORT_ENABLED", "false").lower() == "true"
        self.import_interval_seconds = max(int(os.getenv("IMPORT_INTERVAL_SECONDS", "300")), 30)
        self.import_mode = os.getenv("IMPORT_MODE", "hardlink").lower()
        self.import_conflict_policy = os.getenv("IMPORT_CONFLICT_POLICY", "skip").lower()
        self.import_audiobook_library_path = os.getenv("IMPORT_AUDIOBOOK_LIBRARY_PATH", "")
        self.import_ebook_library_path = os.getenv("IMPORT_EBOOK_LIBRARY_PATH", "")
        self.import_audiobook_extensions = os.getenv("IMPORT_AUDIOBOOK_EXTENSIONS", ".m4b,.mp3,.m4a,.flac,.ogg,.opus,.aac")
        self.import_ebook_extensions = os.getenv("IMPORT_EBOOK_EXTENSIONS", ".epub,.pdf,.mobi,.azw3,.cbz,.cbr")
        self.import_min_completion_ratio_legacy_present = "IMPORT_MIN_COMPLETION_RATIO" in os.environ
        self.import_require_seeding_or_complete = os.getenv("IMPORT_REQUIRE_SEEDING_OR_COMPLETE", "true").lower() == "true"
        self.import_dry_run = os.getenv("IMPORT_DRY_RUN", "false").lower() == "true"
        self.import_allowed_download_roots = os.getenv("IMPORT_ALLOWED_DOWNLOAD_ROOTS", "/downloads")


settings = Settings()
