from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ALLOWED_MEDIA = {"audiobook", "ebook"}
ALLOWED_SORT = {"seedersDesc", "addedDesc", "sizeAsc", "sizeDesc"}
ALLOWED_SEARCH_IN = {"title", "author", "narrator", "series"}


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    media_type: Literal["audiobook", "ebook"] = "audiobook"
    search_in: list[str] = Field(default_factory=lambda: ["title", "author", "narrator", "series"])
    sort: str = "seedersDesc"

    @field_validator("search_in")
    @classmethod
    def validate_search_in(cls, value: list[str]) -> list[str]:
        values = list(dict.fromkeys(v for v in value if v in ALLOWED_SEARCH_IN))
        if not values:
            raise ValueError("search_in must include at least one valid field")
        return values

    @field_validator("sort")
    @classmethod
    def validate_sort(cls, value: str) -> str:
        if value not in ALLOWED_SORT:
            raise ValueError("invalid sort")
        return value


class AddRequest(BaseModel):
    id: int
    media_type: Literal["audiobook", "ebook"] = "audiobook"


class NormalizedResult(BaseModel):
    id: int
    title: str
    author: str = ""
    narrator: str = ""
    series: str = ""
    filetypes: str = ""
    size: str = ""
    seeders: int = 0
    leechers: int = 0
    free: bool = False
    vip: bool = False
    my_snatched: bool = False
    added: str = ""
    catname: str = ""
