from dataclasses import dataclass


@dataclass(frozen=True)
class RegisteredUser:
    max_user_id: int
    faculty_id: str
    faculty_name: str
    group_id: str
    group_name: str
