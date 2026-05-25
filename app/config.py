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


settings = Settings()
