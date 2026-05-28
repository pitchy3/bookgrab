from __future__ import annotations

import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LibraryBook:
    title: str
    authors: str
    narrators: str


@dataclass(frozen=True)
class LibraryMatch:
    provider: str
    title: str
    author: str
    narrator: str


class LibraryPresenceProvider(Protocol):
    name: str

    def enabled(self) -> bool: ...
    async def refresh_index(self) -> list[LibraryBook]: ...
    def find_match(self, title: str, authors: str, narrators: str) -> LibraryMatch | None: ...


def _normalize_text(value: str) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"^(a|an|the)\s+", "", text)


def _split_people(value: str) -> set[str]:
    parts = re.split(r"[,;/]|\band\b|\bwith\b|\&", value or "", flags=re.IGNORECASE)
    return {p for p in (_normalize_text(x) for x in parts) if p}




def _extract_people(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        people: list[str] = []
        for item in value:
            if isinstance(item, str):
                person = item.strip()
            elif isinstance(item, dict):
                person = str(item.get("name", "")).strip()
            else:
                person = ""
            if person:
                people.append(person)
        return ", ".join(people)
    return ""

def _is_strict_match(title: str, authors: str, narrators: str, book: LibraryBook) -> bool:
    title_ok = _normalize_text(title) == _normalize_text(book.title)
    left_authors, right_authors = _split_people(authors), _split_people(book.authors)
    if not (title_ok and bool(left_authors & right_authors)):
        return False
    if not settings.library_presence_require_narrator:
        return True
    left_narrators, right_narrators = _split_people(narrators), _split_people(book.narrators)
    if not left_narrators or not right_narrators:
        return False
    return bool(left_narrators & right_narrators)


class PlexProvider:
    name = "Plex"

    def __init__(self) -> None:
        self._index: list[LibraryBook] = []

    def enabled(self) -> bool:
        return settings.plex_enabled and bool(settings.plex_base_url and settings.plex_token)

    async def refresh_index(self) -> list[LibraryBook]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            section_id = settings.plex_library_section_id or await self._resolve_section_id(client)
            if not section_id:
                return []
            books = await self._fetch_album_books(client, section_id)
            if not books:
                books = await self._fetch_track_fallback_books(client, section_id)
            self._index = books
            return books

    async def _fetch_album_books(self, client: httpx.AsyncClient, section_id: str) -> list[LibraryBook]:
        resp = await client.get(f"{settings.plex_base_url}/library/sections/{section_id}/albums", params={"X-Plex-Token": settings.plex_token})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        books: list[LibraryBook] = []
        for node in root.iter():
            if node.tag not in {"Directory", "Metadata"}:
                continue
            if node.attrib.get("type") == "artist":
                continue
            title = node.attrib.get("title", "")
            if not _normalize_text(title):
                continue
            author = node.attrib.get("parentTitle", "") or node.attrib.get("grandparentTitle", "")
            role_tags = [c.attrib.get("tag", "") for c in node.findall("Role") if c.attrib.get("tag")]
            narr = ", ".join([r for r in role_tags if "narrat" in r.lower()])
            books.append(LibraryBook(title=title, authors=author or "", narrators=narr))
        return books

    async def _fetch_track_fallback_books(self, client: httpx.AsyncClient, section_id: str) -> list[LibraryBook]:
        resp = await client.get(f"{settings.plex_base_url}/library/sections/{section_id}/all", params={"X-Plex-Token": settings.plex_token})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        books: list[LibraryBook] = []
        for node in root.findall(".//Track"):
            title = node.attrib.get("parentTitle") or node.attrib.get("title") or ""
            if not _normalize_text(title):
                continue
            author = node.attrib.get("grandparentTitle", "")
            role_tags = [c.attrib.get("tag", "") for c in node.findall("Role") if c.attrib.get("tag")]
            narr = ", ".join([r for r in role_tags if "narrat" in r.lower()])
            books.append(LibraryBook(title=title, authors=author or "", narrators=narr))
        return books

    def find_match(self, title: str, authors: str, narrators: str) -> LibraryMatch | None:
        for b in self._index:
            if _is_strict_match(title, authors, narrators, b):
                return LibraryMatch(provider=self.name, title=b.title, author=b.authors, narrator=b.narrators)
        return None

    async def _resolve_section_id(self, client: httpx.AsyncClient) -> str | None:
        resp = await client.get(f"{settings.plex_base_url}/library/sections", params={"X-Plex-Token": settings.plex_token})
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        wanted = settings.plex_library_name.strip().lower()
        for node in root.findall(".//Directory"):
            if node.attrib.get("title", "").strip().lower() == wanted:
                return node.attrib.get("key")
        return None


class AudiobookshelfProvider:
    name = "Audiobookshelf"

    def __init__(self) -> None:
        self._index: list[LibraryBook] = []

    def enabled(self) -> bool:
        return settings.audiobookshelf_enabled and bool(settings.audiobookshelf_base_url and settings.audiobookshelf_token and settings.audiobookshelf_library_id)

    async def refresh_index(self) -> list[LibraryBook]:
        headers = {"Authorization": f"Bearer {settings.audiobookshelf_token}"}
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            resp = await client.get(f"{settings.audiobookshelf_base_url}/api/libraries/{settings.audiobookshelf_library_id}/items", params={"limit": 0})
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("results") or payload.get("items") or []
            books: list[LibraryBook] = []
            for item in items:
                md = ((item or {}).get("media") or {}).get("metadata") or {}
                title = md.get("title", "")
                if not _normalize_text(title):
                    continue
                author = _extract_people(md.get("authorName")) or _extract_people(md.get("authors"))
                narrator = _extract_people(md.get("narratorName")) or _extract_people(md.get("narrators"))
                books.append(LibraryBook(title=title, authors=author or "", narrators=narrator or ""))
            self._index = books
            return books

    def find_match(self, title: str, authors: str, narrators: str) -> LibraryMatch | None:
        for b in self._index:
            if _is_strict_match(title, authors, narrators, b):
                return LibraryMatch(provider=self.name, title=b.title, author=b.authors, narrator=b.narrators)
        return None


class LibraryPresenceService:
    def __init__(self, providers: list[LibraryPresenceProvider] | None = None) -> None:
        self.providers = providers or [PlexProvider(), AudiobookshelfProvider()]
        self._provider_cache: dict[str, tuple[float, list[LibraryBook]]] = {}
        self._lock = asyncio.Lock()

    async def annotate(self, row: dict) -> tuple[bool, list[dict[str, str]]]:
        matches: list[dict[str, str]] = []
        for provider in self.providers:
            if not provider.enabled():
                continue
            try:
                await self._ensure_provider_index(provider)
                match = provider.find_match(row.get("title", ""), row.get("author", ""), row.get("narrator", ""))
                if match:
                    matches.append({"provider": match.provider, "title": match.title, "author": match.author, "narrator": match.narrator})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Library provider %s unavailable: %s", provider.name, exc)
        return bool(matches), matches

    async def _ensure_provider_index(self, provider: LibraryPresenceProvider) -> None:
        ttl = settings.library_presence_cache_ttl_seconds
        now = time.time()
        cached = self._provider_cache.get(provider.name)
        if cached and (now - cached[0]) < ttl:
            return
        async with self._lock:
            cached = self._provider_cache.get(provider.name)
            if cached and (now - cached[0]) < ttl:
                return
            try:
                data = await provider.refresh_index()
            except Exception:
                if cached:
                    logger.warning("Library provider %s refresh failed; using stale index", provider.name)
                    return
                raise
            self._provider_cache[provider.name] = (time.time(), data)


library_presence_service = LibraryPresenceService()
