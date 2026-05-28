from app import library_presence
from app.library_presence import LibraryBook, _is_strict_match, _normalize_text, _split_people


def test_normalization_and_split():
    assert _normalize_text('The, Book!') == 'book'
    assert _split_people('A, B & C') == {'a', 'b', 'c'}


def test_require_narrator_true_full_match(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', True)
    b = LibraryBook(title='The Book', authors='Jane Doe', narrators='John Smith')
    assert _is_strict_match('the book', 'JANE DOE', 'john smith', b)


def test_require_narrator_true_different_narrator_no_match(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', True)
    b = LibraryBook(title='The Book', authors='Jane Doe', narrators='John Smith')
    assert not _is_strict_match('the book', 'JANE DOE', 'Mary Jones', b)


def test_require_narrator_true_missing_narrator_no_match(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', True)
    b = LibraryBook(title='The Book', authors='Jane Doe', narrators='')
    assert not _is_strict_match('the book', 'JANE DOE', 'John Smith', b)


def test_require_narrator_false_ignores_different_or_missing_narrator(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', False)
    b = LibraryBook(title='The Book', authors='Jane Doe', narrators='John Smith')
    assert _is_strict_match('the book', 'JANE DOE', 'Different Person', b)
    assert _is_strict_match('the book', 'JANE DOE', '', b)
    b_missing = LibraryBook(title='The Book', authors='Jane Doe', narrators='')
    assert _is_strict_match('the book', 'JANE DOE', '', b_missing)

import asyncio


def test_plex_track_uses_parent_title_for_book_title(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'plex_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'plex_base_url', 'http://plex.local')
    monkeypatch.setattr(library_presence.settings, 'plex_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'plex_library_section_id', '1')

    class _Resp:
        text = '<MediaContainer><Track title="Chapter 01" parentTitle="Actual Book" grandparentTitle="Author Name" /></MediaContainer>'

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.PlexProvider()
    books = asyncio.run(provider.refresh_index())

    assert books
    assert books[0].title == 'Actual Book'
