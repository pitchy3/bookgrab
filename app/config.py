from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

MAM_HASH_LOOKUP_SCOPES = {"mam_only", "category", "bookgrab", "all"}


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() == "true"


def _env_int_min(name: str, default: str, minimum: int) -> int:
    return max(int(os.getenv(name, default)), minimum)


def parse_csv_list(value: str, *, lowercase: bool = False) -> list[str]:
    items = []
    for part in value.split(","):
        item = part.strip()
        if not item:
            continue
        items.append(item.lower() if lowercase else item)
    return items


def parse_mam_hash_lookup_scope(value: str) -> str:
    scope = value.strip().lower()
    if scope not in MAM_HASH_LOOKUP_SCOPES:
        allowed = ", ".join(sorted(MAM_HASH_LOOKUP_SCOPES))
        raise RuntimeError(f"MAM_HASH_LOOKUP_SCOPE must be one of: {allowed}; got '{value}'")
    return scope


@dataclass
class Settings:
    app_auth_enabled: bool = field(default_factory=lambda: _env_bool("APP_AUTH_ENABLED", "true"))
    app_username: str = field(default_factory=lambda: os.getenv("APP_USERNAME", "admin"))
    app_password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", "change-me"))
    app_session_secret: str = field(default_factory=lambda: os.getenv("APP_SESSION_SECRET", secrets.token_urlsafe(32)))

    mam_base_url: str = field(default_factory=lambda: os.getenv("MAM_BASE_URL", "https://www.myanonamouse.net").rstrip("/"))
    mam_cookie: str = field(default_factory=lambda: os.getenv("MAM_COOKIE", ""))
    mam_uid: str = field(default_factory=lambda: os.getenv("MAM_UID", ""))
    mam_session: str = field(default_factory=lambda: os.getenv("MAM_SESSION", ""))
    mam_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("MAM_TIMEOUT_SECONDS", "30")))
    mam_dynamic_seedbox_enabled: bool = field(default_factory=lambda: _env_bool("MAM_DYNAMIC_SEEDBOX_ENABLED", "false"))
    mam_dynamic_seedbox_url: str = field(default_factory=lambda: os.getenv("MAM_DYNAMIC_SEEDBOX_URL", "https://t.myanonamouse.net/json/dynamicSeedbox.php"))
    mam_dynamic_seedbox_min_interval_seconds: int = field(default_factory=lambda: _env_int_min("MAM_DYNAMIC_SEEDBOX_MIN_INTERVAL_SECONDS", "3600", 1))
    mam_dynamic_seedbox_run_on_startup: bool = field(default_factory=lambda: _env_bool("MAM_DYNAMIC_SEEDBOX_RUN_ON_STARTUP", "true"))
    mam_dynamic_seedbox_run_before_search: bool = field(default_factory=lambda: _env_bool("MAM_DYNAMIC_SEEDBOX_RUN_BEFORE_SEARCH", "true"))
    mam_dynamic_seedbox_state_path: str = field(default_factory=lambda: os.getenv("MAM_DYNAMIC_SEEDBOX_STATE_PATH", "/config/mam_dynamic_seedbox.json"))
    mam_cookie_file: str = field(default_factory=lambda: os.getenv("MAM_COOKIE_FILE", ""))
    mam_cookie_store_path: str = field(default_factory=lambda: os.getenv("MAM_COOKIE_STORE_PATH", "/config/mam_cookie"))
    mam_hash_lookup_enabled: bool = field(default_factory=lambda: _env_bool("MAM_HASH_LOOKUP_ENABLED", "false"))
    mam_hash_lookup_max_per_run: int = field(default_factory=lambda: _env_int_min("MAM_HASH_LOOKUP_MAX_PER_RUN", "100", 0))
    mam_hash_lookup_cache_ttl_days: int = field(default_factory=lambda: _env_int_min("MAM_HASH_LOOKUP_CACHE_TTL_DAYS", "30", 1))
    mam_hash_lookup_retry_error_ttl_hours: int = field(default_factory=lambda: _env_int_min("MAM_HASH_LOOKUP_RETRY_ERROR_TTL_HOURS", "24", 1))
    mam_hash_lookup_no_match_ttl_days: int = field(default_factory=lambda: _env_int_min("MAM_HASH_LOOKUP_NO_MATCH_TTL_DAYS", "30", 1))
    mam_hash_lookup_cron_enabled: bool = field(default_factory=lambda: _env_bool("MAM_HASH_LOOKUP_CRON_ENABLED", "false"))
    mam_hash_lookup_cron: str = field(default_factory=lambda: os.getenv("MAM_HASH_LOOKUP_CRON", ""))
    mam_hash_lookup_cron_timezone: str = field(default_factory=lambda: os.getenv("MAM_HASH_LOOKUP_CRON_TIMEZONE", os.getenv("TZ", "UTC")))

    qbit_base_url: str = field(default_factory=lambda: os.getenv("QBIT_BASE_URL", "http://qbittorrent:8080").rstrip("/"))
    qbit_username: str = field(default_factory=lambda: os.getenv("QBIT_USERNAME", "admin"))
    qbit_password: str = field(default_factory=lambda: os.getenv("QBIT_PASSWORD", ""))
    qbit_category_audiobooks: str = field(default_factory=lambda: os.getenv("QBIT_CATEGORY_AUDIOBOOKS", "audiobooks"))
    qbit_category_ebooks: str = field(default_factory=lambda: os.getenv("QBIT_CATEGORY_EBOOKS", "ebooks"))
    qbit_save_path_audiobooks: str = field(default_factory=lambda: os.getenv("QBIT_SAVE_PATH_AUDIOBOOKS", ""))
    qbit_save_path_ebooks: str = field(default_factory=lambda: os.getenv("QBIT_SAVE_PATH_EBOOKS", ""))

    mam_hash_lookup_scope: str = field(init=False)
    mam_tracker_hosts: list[str] = field(init=False)
    mam_hash_lookup_include_categories: list[str] = field(init=False)

    default_media_type: str = field(default_factory=lambda: os.getenv("DEFAULT_MEDIA_TYPE", "audiobook"))
    default_sort: str = field(default_factory=lambda: os.getenv("DEFAULT_SORT", "seedersDesc"))
    default_search_type: str = field(default_factory=lambda: os.getenv("DEFAULT_SEARCH_TYPE", "active"))
    search_cache_ttl_seconds: int = field(default_factory=lambda: _env_int_min("SEARCH_CACHE_TTL_SECONDS", "1800", 1))
    search_cache_max_entries: int = field(default_factory=lambda: _env_int_min("SEARCH_CACHE_MAX_ENTRIES", "200", 1))

    plex_enabled: bool = field(default_factory=lambda: _env_bool("PLEX_ENABLED", "false"))
    plex_base_url: str = field(default_factory=lambda: os.getenv("PLEX_BASE_URL", "http://plex:32400").rstrip("/"))
    plex_token: str = field(default_factory=lambda: os.getenv("PLEX_TOKEN", ""))
    plex_library_section_id: str = field(default_factory=lambda: os.getenv("PLEX_LIBRARY_SECTION_ID", ""))
    plex_library_name: str = field(default_factory=lambda: os.getenv("PLEX_LIBRARY_NAME", "Audiobooks"))
    audiobookshelf_enabled: bool = field(default_factory=lambda: _env_bool("AUDIOBOOKSHELF_ENABLED", "false"))
    audiobookshelf_base_url: str = field(default_factory=lambda: os.getenv("AUDIOBOOKSHELF_BASE_URL", "").rstrip("/"))
    audiobookshelf_token: str = field(default_factory=lambda: os.getenv("AUDIOBOOKSHELF_TOKEN", ""))
    audiobookshelf_library_id: str = field(default_factory=lambda: os.getenv("AUDIOBOOKSHELF_LIBRARY_ID", ""))

    library_presence_cache_ttl_seconds: int = field(default_factory=lambda: _env_int_min("LIBRARY_PRESENCE_CACHE_TTL_SECONDS", "600", 1))
    library_presence_require_narrator: bool = field(default_factory=lambda: _env_bool("LIBRARY_PRESENCE_REQUIRE_NARRATOR", "true"))

    config_dir: str = field(default_factory=lambda: os.getenv("CONFIG_DIR", "/config"))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "/config/app.db"))

    import_enabled: bool = field(default_factory=lambda: _env_bool("IMPORT_ENABLED", "false"))
    import_interval_seconds: int = field(default_factory=lambda: _env_int_min("IMPORT_INTERVAL_SECONDS", "300", 30))
    import_mode: str = field(default_factory=lambda: os.getenv("IMPORT_MODE", "hardlink").lower())
    import_conflict_policy: str = field(default_factory=lambda: os.getenv("IMPORT_CONFLICT_POLICY", "skip").lower())
    import_audiobook_library_path: str = field(default_factory=lambda: os.getenv("IMPORT_AUDIOBOOK_LIBRARY_PATH", ""))
    import_ebook_library_path: str = field(default_factory=lambda: os.getenv("IMPORT_EBOOK_LIBRARY_PATH", ""))
    import_audiobook_extensions: str = field(default_factory=lambda: os.getenv("IMPORT_AUDIOBOOK_EXTENSIONS", ".m4b,.mp3,.m4a,.flac,.ogg,.opus,.aac"))
    import_ebook_extensions: str = field(default_factory=lambda: os.getenv("IMPORT_EBOOK_EXTENSIONS", ".epub,.pdf,.mobi,.azw3,.cbz,.cbr"))
    import_min_completion_ratio_legacy_present: bool = field(default_factory=lambda: "IMPORT_MIN_COMPLETION_RATIO" in os.environ)
    import_require_seeding_or_complete: bool = field(default_factory=lambda: _env_bool("IMPORT_REQUIRE_SEEDING_OR_COMPLETE", "true"))
    import_dry_run: bool = field(default_factory=lambda: _env_bool("IMPORT_DRY_RUN", "false"))
    import_allowed_download_roots: str = field(default_factory=lambda: os.getenv("IMPORT_ALLOWED_DOWNLOAD_ROOTS", "/downloads"))

    def __post_init__(self) -> None:
        self.mam_hash_lookup_scope = parse_mam_hash_lookup_scope(os.getenv("MAM_HASH_LOOKUP_SCOPE", "mam_only"))
        self.mam_tracker_hosts = parse_csv_list(
            os.getenv("MAM_TRACKER_HOSTS", "myanonamouse.net,www.myanonamouse.net,t.myanonamouse.net"),
            lowercase=True,
        )
        if "MAM_HASH_LOOKUP_INCLUDE_CATEGORIES" in os.environ:
            category_value = os.getenv("MAM_HASH_LOOKUP_INCLUDE_CATEGORIES", "")
        else:
            category_value = ",".join([self.qbit_category_audiobooks, self.qbit_category_ebooks])
        self.mam_hash_lookup_include_categories = parse_csv_list(category_value, lowercase=True)


settings = Settings()
