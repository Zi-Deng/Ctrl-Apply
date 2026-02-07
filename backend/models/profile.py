from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class Address(BaseModel):
    street: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = Field("", alias="zip")
    country: str = "United States"

    model_config = {"populate_by_name": True}


class PersonalInfo(BaseModel):
    first_name: str
    last_name: str
    email: str  # EmailStr requires email-validator; keep simple for Phase 1
    phone: str = ""
    address: Address = Address()
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""


class Education(BaseModel):
    degree: str
    field: str
    institution: str
    gpa: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class Experience(BaseModel):
    title: str
    company: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    description: str = ""


class Project(BaseModel):
    name: str
    description: str = ""
    url: str = ""
    technologies: list[str] = []


class Skills(BaseModel):
    technical: list[str] = []
    frameworks: list[str] = []
    tools: list[str] = []


class Publication(BaseModel):
    title: str
    venue: str = ""
    year: str = ""
    url: str = ""


class Language(BaseModel):
    language: str
    proficiency: str = ""


class Demographics(BaseModel):
    gender: str = ""
    ethnicity: str = ""
    veteran_status: str = ""
    disability_status: str = ""


class WorkAuthorization(BaseModel):
    us_authorized: bool = True
    requires_sponsorship: bool = False
    visa_status: str = ""


class Preferences(BaseModel):
    willing_to_relocate: bool = True
    remote_preference: str = ""
    start_date: str = ""


class CommonAnswers(BaseModel):
    hear_about_us: str = "Online job board"
    cover_letter_template: str = ""
    extra: dict[str, str] = {}


class UserProfile(BaseModel):
    personal_info: PersonalInfo
    education: list[Education] = []
    experience: list[Experience] = []
    projects: list[Project] = []
    skills: Skills = Skills()
    publications: list[Publication] = []
    languages: list[Language] = []
    certifications: list[str] = []
    demographics: Demographics = Demographics()
    work_authorization: WorkAuthorization = WorkAuthorization()
    preferences: Preferences = Preferences()
    common_answers: CommonAnswers = CommonAnswers()

    def get_field(self, dotted_path: str) -> str | None:
        """Resolve a dotted path like 'personal_info.email' to its value."""
        parts = dotted_path.split(".")
        obj: object = self
        for part in parts:
            if isinstance(obj, list):
                try:
                    obj = obj[int(part)]
                except (IndexError, ValueError):
                    return None
            elif isinstance(obj, dict):
                obj = obj.get(part)
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None
            if obj is None:
                return None
        return str(obj) if obj is not None else None
