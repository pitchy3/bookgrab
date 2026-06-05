from app import library_presence
from app.library_presence import LibraryBook, _extract_people, _is_strict_match, _normalize_text, _split_people


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


def test_extract_people_supports_strings_lists_and_objects():
    assert _extract_people('Ray Porter') == 'Ray Porter'
    assert _extract_people(['Ray Porter', 'Other Narrator']) == 'Ray Porter, Other Narrator'
    assert _extract_people([{'name': 'Andy Weir'}]) == 'Andy Weir'


def test_audiobookshelf_refresh_supports_multiple_people_shapes(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_base_url', 'http://abs.local')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_library_id', 'lib1')

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {'results': [
                {'media': {'metadata': {'title': 'Project Hail Mary', 'authorName': 'Andy Weir', 'narratorName': 'Ray Porter'}}},
                {'media': {'metadata': {'title': 'Book Two', 'authors': [{'name': 'Andy Weir'}], 'narrators': ['Ray Porter']}}},
            ]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.AudiobookshelfProvider()
    books = asyncio.run(provider.refresh_index())

    assert books[0] == LibraryBook(title='Project Hail Mary', authors='Andy Weir', narrators='Ray Porter')
    assert books[1] == LibraryBook(title='Book Two', authors='Andy Weir', narrators='Ray Porter')


def test_audiobookshelf_refresh_fetches_paginated_items(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_base_url', 'http://abs.local')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_library_id', 'lib1')

    requests: list[dict] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            params = kwargs['params']
            requests.append(params)
            if params['page'] == 0:
                return _Resp({
                    'results': [
                        {'media': {'metadata': {'title': 'Book One', 'authorName': 'Author A', 'narratorName': 'Narrator A'}}},
                        {'media': {'metadata': {'title': 'Book Two', 'authorName': 'Author B', 'narratorName': 'Narrator B'}}},
                    ],
                    'total': 3,
                    'page': 0,
                })
            return _Resp({
                'items': [
                    {'media': {'metadata': {'title': 'Book Three', 'authors': [{'name': 'Author C'}], 'narrators': ['Narrator C']}}},
                ],
                'total': 3,
                'page': 1,
            })

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.AudiobookshelfProvider()
    books = asyncio.run(provider.refresh_index())

    assert requests == [{'limit': 100, 'page': 0}, {'limit': 100, 'page': 1}]
    assert books == [
        LibraryBook(title='Book One', authors='Author A', narrators='Narrator A'),
        LibraryBook(title='Book Two', authors='Author B', narrators='Narrator B'),
        LibraryBook(title='Book Three', authors='Author C', narrators='Narrator C'),
    ]


def test_audiobookshelf_refresh_uses_positive_limit(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_base_url', 'http://abs.local')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'audiobookshelf_library_id', 'lib1')

    requests: list[dict] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            params = kwargs['params']
            requests.append(params)
            if params['limit'] == 0:
                return _Resp({'results': []})
            return _Resp({'results': [
                {'media': {'metadata': {'title': 'Positive Limit Book', 'authorName': 'Author', 'narratorName': 'Narrator'}}},
            ]})

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.AudiobookshelfProvider()
    books = asyncio.run(provider.refresh_index())

    assert requests == [{'limit': 100, 'page': 0}]
    assert books == [LibraryBook(title='Positive Limit Book', authors='Author', narrators='Narrator')]


def test_audiobookshelf_strict_match_with_narrator_required(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', True)
    provider = library_presence.AudiobookshelfProvider()
    provider._index = [LibraryBook(title='Book', authors='Jane', narrators='John')]

    match = provider.find_match('Book', 'Jane', 'John')

    assert match is not None
    assert match.provider == 'Audiobookshelf'


def test_plex_track_uses_parent_title_for_book_title(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'plex_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'plex_base_url', 'http://plex.local')
    monkeypatch.setattr(library_presence.settings, 'plex_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'plex_library_section_id', '1')

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *args, **kwargs):
            if url.endswith("/albums"):
                return _Resp("<MediaContainer></MediaContainer>")
            return _Resp('<MediaContainer><Track title="Chapter 01" parentTitle="Actual Book" grandparentTitle="Author Name" /></MediaContainer>')

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.PlexProvider()
    books = asyncio.run(provider.refresh_index())

    assert books
    assert books[0].title == 'Actual Book'
    assert books[0].authors == 'Author Name'


def test_plex_albums_skip_artist_and_index_album_author(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'plex_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'plex_base_url', 'http://plex.local')
    monkeypatch.setattr(library_presence.settings, 'plex_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'plex_library_section_id', '1')

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *args, **kwargs):
            if url.endswith("/albums"):
                return _Resp('<MediaContainer><Directory type="artist" title="Stephen King"/><Directory type="album" title="Carrie" parentTitle="Stephen King" /></MediaContainer>')
            return _Resp("<MediaContainer></MediaContainer>")

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.PlexProvider()
    books = asyncio.run(provider.refresh_index())

    assert books == [LibraryBook(title='Carrie', authors='Stephen King', narrators='')]


def test_plex_albums_index_metadata_album_nodes(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'plex_enabled', True)
    monkeypatch.setattr(library_presence.settings, 'plex_base_url', 'http://plex.local')
    monkeypatch.setattr(library_presence.settings, 'plex_token', 'token')
    monkeypatch.setattr(library_presence.settings, 'plex_library_section_id', '1')

    requests: list[str] = []

    class _Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *args, **kwargs):
            requests.append(url)
            if url.endswith("/albums"):
                return _Resp('<MediaContainer><Metadata type="album" title="Carrie" parentTitle="Stephen King"><Role tag="Narrator: Sissy Spacek" /></Metadata></MediaContainer>')
            return _Resp('<MediaContainer><Track title="Chapter 01" parentTitle="Fallback Book" grandparentTitle="Fallback Author" /></MediaContainer>')

    monkeypatch.setattr(library_presence.httpx, 'AsyncClient', lambda *args, **kwargs: _Client())

    provider = library_presence.PlexProvider()
    books = asyncio.run(provider.refresh_index())

    assert books == [LibraryBook(title='Carrie', authors='Stephen King', narrators='Narrator: Sissy Spacek')]
    assert requests == ['http://plex.local/library/sections/1/albums']


def test_plex_album_matches_when_narrator_not_required(monkeypatch):
    monkeypatch.setattr(library_presence.settings, 'library_presence_require_narrator', False)
    provider = library_presence.PlexProvider()
    provider._index = [LibraryBook(title='Carrie', authors='Stephen King', narrators='')]

    match = provider.find_match('Carrie', 'Stephen King', '')

    assert match is not None
    assert match.provider == 'Plex'
