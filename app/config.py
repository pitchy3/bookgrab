from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass
class Settings:
    app_auth_enabled: bool = os.getenv("APP_AUTH_ENABLED", "true").lower() == "true"
    app_username: str = os.getenv("APP_USERNAME", "admin")
    app_password: str = os.getenv("APP_PASSWORD", "change-me")
    app_session_secret: str = os.getenv("APP_SESSION_SECRET", secrets.token_urlsafe(32))

    mam_base_url: str = os.getenv("MAM_BASE_URL", "https://www.myanonamouse.net").rstrip("/")
    mam_cookie: str = os.getenv("MAM_COOKIE", "")
    mam_uid: str = os.getenv("MAM_UID", "")
    mam_session: str = os.getenv("MAM_SESSION", "")
    mam_timeout_seconds: int = int(os.getenv("MAM_TIMEOUT_SECONDS", "30"))
    mam_hash_lookup_enabled: bool = os.getenv("MAM_HASH_LOOKUP_ENABLED", "false").lower() == "true"
    mam_hash_lookup_delay_seconds: float = max(float(os.getenv("MAM_HASH_LOOKUP_DELAY_SECONDS", "10")), 0.0)
    mam_hash_lookup_max_per_run: int = max(int(os.getenv("MAM_HASH_LOOKUP_MAX_PER_RUN", "100")), 0)
    mam_hash_lookup_cache_ttl_days: int = max(int(os.getenv("MAM_HASH_LOOKUP_CACHE_TTL_DAYS", "30")), 1)
    mam_hash_lookup_retry_error_ttl_hours: int = max(int(os.getenv("MAM_HASH_LOOKUP_RETRY_ERROR_TTL_HOURS", "24")), 1)
    mam_hash_lookup_no_match_ttl_days: int = max(int(os.getenv("MAM_HASH_LOOKUP_NO_MATCH_TTL_DAYS", "30")), 1)
    mam_hash_lookup_cron_enabled: bool = os.getenv("MAM_HASH_LOOKUP_CRON_ENABLED", "false").lower() == "true"
    mam_hash_lookup_cron: str = os.getenv("MAM_HASH_LOOKUP_CRON", "")
    mam_hash_lookup_cron_timezone: str = os.getenv("MAM_HASH_LOOKUP_CRON_TIMEZONE", os.getenv("TZ", "UTC"))

    qbit_base_url: str = os.getenv("QBIT_BASE_URL", "http://qbittorrent:8080").rstrip("/")
    qbit_username: str = os.getenv("QBIT_USERNAME", "admin")
    qbit_password: str = os.getenv("QBIT_PASSWORD", "")
    qbit_category_audiobooks: str = os.getenv("QBIT_CATEGORY_AUDIOBOOKS", "audiobooks")
    qbit_category_ebooks: str = os.getenv("QBIT_CATEGORY_EBOOKS", "ebooks")
    qbit_save_path_audiobooks: str = os.getenv("QBIT_SAVE_PATH_AUDIOBOOKS", "")
    qbit_save_path_ebooks: str = os.getenv("QBIT_SAVE_PATH_EBOOKS", "")

    default_media_type: str = os.getenv("DEFAULT_MEDIA_TYPE", "audiobook")
    default_sort: str = os.getenv("DEFAULT_SORT", "seedersDesc")
    default_search_type: str = os.getenv("DEFAULT_SEARCH_TYPE", "active")
    search_cache_ttl_seconds: int = max(int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "1800")), 1)
    search_cache_max_entries: int = max(int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "200")), 1)

    plex_enabled: bool = os.getenv("PLEX_ENABLED", "false").lower() == "true"
    plex_base_url: str = os.getenv("PLEX_BASE_URL", "http://plex:32400").rstrip("/")
    plex_token: str = os.getenv("PLEX_TOKEN", "")
    plex_library_section_id: str = os.getenv("PLEX_LIBRARY_SECTION_ID", "")
    plex_library_name: str = os.getenv("PLEX_LIBRARY_NAME", "Audiobooks")
    audiobookshelf_enabled: bool = os.getenv("AUDIOBOOKSHELF_ENABLED", "false").lower() == "true"
    audiobookshelf_base_url: str = os.getenv("AUDIOBOOKSHELF_BASE_URL", "").rstrip("/")
    audiobookshelf_token: str = os.getenv("AUDIOBOOKSHELF_TOKEN", "")
    audiobookshelf_library_id: str = os.getenv("AUDIOBOOKSHELF_LIBRARY_ID", "")

    library_presence_cache_ttl_seconds: int = max(int(os.getenv("LIBRARY_PRESENCE_CACHE_TTL_SECONDS", "600")), 1)
    library_presence_require_narrator: bool = os.getenv("LIBRARY_PRESENCE_REQUIRE_NARRATOR", "true").lower() == "true"

    config_dir: str = os.getenv("CONFIG_DIR", "/config")
    database_path: str = os.getenv("DATABASE_PATH", "/config/app.db")


    import_enabled: bool = os.getenv("IMPORT_ENABLED", "false").lower() == "true"
    import_interval_seconds: int = max(int(os.getenv("IMPORT_INTERVAL_SECONDS", "300")), 30)
    import_mode: str = os.getenv("IMPORT_MODE", "hardlink").lower()
    import_conflict_policy: str = os.getenv("IMPORT_CONFLICT_POLICY", "skip").lower()
    import_audiobook_library_path: str = os.getenv("IMPORT_AUDIOBOOK_LIBRARY_PATH", "")
    import_ebook_library_path: str = os.getenv("IMPORT_EBOOK_LIBRARY_PATH", "")
    import_audiobook_extensions: str = os.getenv("IMPORT_AUDIOBOOK_EXTENSIONS", ".m4b,.mp3,.m4a,.flac,.ogg,.opus,.aac")
    import_ebook_extensions: str = os.getenv("IMPORT_EBOOK_EXTENSIONS", ".epub,.pdf,.mobi,.azw3,.cbz,.cbr")
    import_min_completion_ratio_legacy_present: bool = "IMPORT_MIN_COMPLETION_RATIO" in os.environ
    import_require_seeding_or_complete: bool = os.getenv("IMPORT_REQUIRE_SEEDING_OR_COMPLETE", "true").lower() == "true"
    import_dry_run: bool = os.getenv("IMPORT_DRY_RUN", "false").lower() == "true"
    import_allowed_download_roots: str = os.getenv("IMPORT_ALLOWED_DOWNLOAD_ROOTS", "/downloads")


settings = Settings()
