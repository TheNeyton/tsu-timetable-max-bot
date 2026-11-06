from datetime import date as Date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Faculty(ApiModel):
    id: str
    name: str


class Group(ApiModel):
    id: str
    name: str
    is_subgroup: bool = Field(alias="isSubgroup")
    faculty_id: str | None = Field(default=None, alias="facultyId")
    faculty: Faculty | None = None


class Professor(ApiModel):
    id: str
    full_name: str = Field(alias="fullName")


class Building(ApiModel):
    id: str
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class Audience(ApiModel):
    id: str | None = None
    name: str
    short_name: str | None = Field(default=None, alias="shortName")
    building: Building | None = None


class EmptySlot(ApiModel):
    type: Literal["EMPTY"]
    starts: int
    ends: int
    lesson_number: int = Field(alias="lessonNumber")


class Lesson(ApiModel):
    type: Literal["LESSON"]
    id: str
    title: str
    lesson_type: str = Field(alias="lessonType")
    groups: list[Group]
    professor: Professor | None = None
    audience: Audience | None = None
    starts: int
    ends: int
    lesson_number: int = Field(alias="lessonNumber")


ScheduleSlot = Annotated[Lesson | EmptySlot, Field(discriminator="type")]


class ScheduleDay(ApiModel):
    date: Date
    lessons: list[ScheduleSlot]


class Schedule(ApiModel):
    grid: list[ScheduleDay]
    groups: list[Group] = Field(default_factory=list)
    professors: list[Professor] = Field(default_factory=list)
    audiences: list[Audience] = Field(default_factory=list)
    hash: str | None = None
