from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass
class Settings:
    app_port: int = int(os.getenv("APP_PORT", "8787"))
    app_bind: str = os.getenv("APP_BIND", "0.0.0.0")
    app_auth_enabled: bool = os.getenv("APP_AUTH_ENABLED", "true").lower() == "true"
    app_username: str = os.getenv("APP_USERNAME", "admin")
    app_password: str = os.getenv("APP_PASSWORD", "change-me")
    app_session_secret: str = os.getenv("APP_SESSION_SECRET", secrets.token_urlsafe(32))

    mam_base_url: str = os.getenv("MAM_BASE_URL", "https://www.myanonamouse.net").rstrip("/")
    mam_cookie: str = os.getenv("MAM_COOKIE", "")
    mam_uid: str = os.getenv("MAM_UID", "")
    mam_session: str = os.getenv("MAM_SESSION", "")
    mam_timeout_seconds: int = int(os.getenv("MAM_TIMEOUT_SECONDS", "30"))

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


settings = Settings()
