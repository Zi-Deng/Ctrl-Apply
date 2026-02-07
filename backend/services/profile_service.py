from __future__ import annotations

import logging
from pathlib import Path

import yaml

from backend.config import settings
from backend.models.profile import UserProfile

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(self) -> None:
        self._profile: UserProfile | None = None

    def load(self, path: Path | None = None) -> UserProfile:
        """Load user profile from YAML file."""
        path = path or settings.profile_path
        if not path.exists():
            raise FileNotFoundError(
                f"Profile not found at {path}. "
                f"Copy data/profile.template.yaml to data/profile.yaml and fill it out."
            )
        with open(path) as f:
            data = yaml.safe_load(f)
        self._profile = UserProfile.model_validate(data)
        logger.info("Loaded profile for %s %s",
                     self._profile.personal_info.first_name,
                     self._profile.personal_info.last_name)
        return self._profile

    @property
    def profile(self) -> UserProfile:
        if self._profile is None:
            return self.load()
        return self._profile

    def reload(self) -> UserProfile:
        """Force reload from disk."""
        self._profile = None
        return self.load()

    def to_prompt_context(self) -> str:
        """Serialize profile to a text block suitable for LLM prompts."""
        p = self.profile
        lines = [
            "=== USER PROFILE ===",
            f"Name: {p.personal_info.first_name} {p.personal_info.last_name}",
            f"Email: {p.personal_info.email}",
            f"Phone: {p.personal_info.phone}",
        ]
        addr = p.personal_info.address
        if addr.city:
            lines.append(
                f"Address: {addr.street}, {addr.city}, {addr.state} {addr.zip_code}, {addr.country}"
            )
        if p.personal_info.linkedin_url:
            lines.append(f"LinkedIn: {p.personal_info.linkedin_url}")
        if p.personal_info.github_url:
            lines.append(f"GitHub: {p.personal_info.github_url}")
        if p.personal_info.portfolio_url:
            lines.append(f"Portfolio: {p.personal_info.portfolio_url}")

        if p.education:
            lines.append("\n--- Education ---")
            for edu in p.education:
                line = f"- {edu.degree} in {edu.field}, {edu.institution}"
                if edu.gpa:
                    line += f" (GPA: {edu.gpa})"
                if edu.start_date or edu.end_date:
                    line += f" [{edu.start_date} - {edu.end_date}]"
                lines.append(line)
                if edu.description:
                    lines.append(f"  {edu.description}")

        if p.experience:
            lines.append("\n--- Experience ---")
            for exp in p.experience:
                line = f"- {exp.title} at {exp.company}"
                if exp.location:
                    line += f", {exp.location}"
                if exp.start_date or exp.end_date:
                    line += f" [{exp.start_date} - {exp.end_date}]"
                lines.append(line)
                if exp.description:
                    lines.append(f"  {exp.description}")

        if p.projects:
            lines.append("\n--- Projects ---")
            for proj in p.projects:
                line = f"- {proj.name}"
                if proj.technologies:
                    line += f" ({', '.join(proj.technologies)})"
                lines.append(line)
                if proj.description:
                    lines.append(f"  {proj.description}")

        if p.skills.technical or p.skills.frameworks or p.skills.tools:
            lines.append("\n--- Skills ---")
            if p.skills.technical:
                lines.append(f"Technical: {', '.join(p.skills.technical)}")
            if p.skills.frameworks:
                lines.append(f"Frameworks: {', '.join(p.skills.frameworks)}")
            if p.skills.tools:
                lines.append(f"Tools: {', '.join(p.skills.tools)}")

        if p.work_authorization:
            wa = p.work_authorization
            lines.append("\n--- Work Authorization ---")
            lines.append(f"US Authorized: {wa.us_authorized}")
            lines.append(f"Requires Sponsorship: {wa.requires_sponsorship}")
            if wa.visa_status:
                lines.append(f"Visa Status: {wa.visa_status}")

        if p.common_answers.hear_about_us:
            lines.append(f"\nHow did you hear about us: {p.common_answers.hear_about_us}")

        return "\n".join(lines)


profile_service = ProfileService()
