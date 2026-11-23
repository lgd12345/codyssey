from datetime import date as Date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class DataPoint(Input):
    date: Date
    value: int = Field(ge=0, le=100)
    memo: str = Field(default='', max_length=1000)


class Profile(Input):
    name: str = Field(default='나의', max_length=30)
    region: str = Field(default='서울', min_length=1, max_length=80)
    heat: Literal['낮음', '보통', '높음'] = '보통'
    cold: Literal['낮음', '보통', '높음'] = '보통'
    styles: list[str] = Field(default_factory=lambda: ['미니멀'], max_length=8)
    theme: Literal['ivory', 'noir'] = 'ivory'
    closet_theme: Literal['walnut', 'starry', 'tropical', 'rose'] = 'walnut'


class Garment(Input):
    name: str = Field(min_length=1, max_length=80)
    category: Literal['상의', '하의', '아우터', '원피스', '신발', '가방', '액세서리']
    color: str = Field(default='#7b6554', pattern=r'^#[0-9a-fA-F]{6}$')
    season: str = Field(default='사계절', max_length=30)
    memo: str = Field(default='', max_length=300)


class Chat(Input):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    saved_outfit_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    date: Date | None = None
    occasion: str = Field(default='일상', max_length=100)
    time: str | None = Field(default=None, pattern=r'^([01][0-9]|2[0-3]):[0-5][0-9]$')
    place: str = Field(default='', max_length=80)
    temperature: float | None = Field(default=None, ge=-60, le=60, allow_inf_nan=False)
    season_override_ids: list[str] = Field(default_factory=list, max_length=10)


class FrontClosure(Input):
    item_id: str
    mode: Literal['open', 'partly_open', 'closed']


class Recommendation(Input):
    answer: str = Field(min_length=1, max_length=2000)
    outfit_ids: list[str] = Field(default_factory=list, max_length=10)
    required_conditions: list[str] = Field(default_factory=list, max_length=20, exclude=True)
    front_closures: list[FrontClosure] = Field(default_factory=list, max_length=2, exclude=True)


class DressCodeCheck(Input):
    verdict: Literal['not_required', 'satisfied', 'unverified']


class SaveOutfit(Input):
    title: str = Field(default='나의 코디', min_length=1, max_length=80)
    date: Date | None = None
    item_ids: list[str] = Field(default_factory=list, max_length=10)
    conversation_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    message_index: int | None = Field(default=None, ge=0, le=99)


WearFit = Literal[
    'wrist_length_sleeves', 'short_sleeves', 'sleeveless',
    'dress_shoes', 'sneakers', 'closed_toe_heels', 'necktie',
]


class Vision(Garment):
    is_clothing: bool
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    wear_fit: WearFit | None = None


class WearReview(Input):
    outlines: list[list[tuple[int, int]]] = Field(default_factory=list, max_length=8)
    openings: list[list[tuple[int, int]]] = Field(default_factory=list, max_length=8)
    hide_base: list[list[tuple[int, int]]] = Field(default_factory=list, max_length=8)
    use_auto_mask: bool = True
