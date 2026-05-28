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
