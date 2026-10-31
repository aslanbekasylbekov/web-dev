from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class CriminalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = Field(description="Real name, null if unknown")
    nickname: str
    reward: int
    last_latitude: float | None
    last_longitude: float | None
    last_location_note: str | None
    difficulty: int = Field(ge=1, le=10)
    armed: bool
    has_crew: bool
    escape_master: bool


class HuntOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    criminal_id: int
    success: bool
    notes: str
    created_at: datetime


class CriminalDetailOut(CriminalOut):
    hunts_count: int
    captured: bool = Field(description="True if at least one hunt was successful")
    hunts: list[HuntOut]


def _clean_notes(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("notes must not be empty")
    return value


class HuntCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "criminal_id": 3,
                "success": False,
                "notes": "Target escaped through an asteroid field.",
            }
        },
    )

    criminal_id: int = Field(gt=0)
    success: StrictBool
    notes: str = Field(max_length=2000)

    _notes = field_validator("notes")(_clean_notes)


class HuntUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"success": True, "notes": "Caught him on the second try."}},
    )

    success: StrictBool | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def notes_not_empty(cls, value: str | None) -> str | None:
        return None if value is None else _clean_notes(value)
