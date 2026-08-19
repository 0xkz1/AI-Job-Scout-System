"""The one place this repository learns who it is writing as.

Every generated document carries a real person's phone number, email and home
city, and this repository is public. Those three lived as literals in
cv_generator, cover_letter_generator, email_outreach and app — ten lines across
six tracked files — so the address and phone of the person the tool writes for
were readable by anyone who opened it, and any fork carried them onward.

They are not secrets in the sense a key is: a CV exists to hand them to a
stranger. They are personal data, and the difference that matters is consent.
The recipient of an application gets them because they were sent. A public
repository publishes them to everyone, permanently, including scrapers.

So the values come from the environment, which .gitignore already keeps out of
git, and the defaults committed here are placeholders. A checkout with no .env
generates a CV that says CANDIDATE_EMAIL rather than a stranger's address — the
document is obviously unfinished instead of quietly wrong, which is the safer
way to fail.

Note: this stops the values LEAVING in future commits. It does not remove them
from the history already pushed. Doing that means rewriting published history
(git filter-repo) and force-pushing, which is a separate decision.

Set in .env — see .env.example:

    CV_NAME, CV_NAME_JA, CV_LOCATION, CV_EMAIL,
    CV_PHONE, CV_PHONE_INTL,
    CV_PORTFOLIO, CV_GITHUB, CV_LINKEDIN
"""
import os

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def _get(key: str, placeholder: str) -> str:
    """The env value, or a visible placeholder — never a real person's details.

    Empty is treated as unset: a key present in .env with nothing after the =
    means someone cleared it, and inheriting a blank into a CV header produces
    "Edinburgh, Scotland, UK |  | " rather than anything a reader can act on.
    """
    return (os.environ.get(key) or "").strip() or placeholder


CONTACT = {
    "name":         _get("CV_NAME", "CANDIDATE_NAME"),
    "name_ja":      _get("CV_NAME_JA", "CANDIDATE_NAME_JA"),
    "location":     _get("CV_LOCATION", "CANDIDATE_LOCATION"),
    "email":        _get("CV_EMAIL", "CANDIDATE_EMAIL"),
    # UK national form, for a CV answering a UK posting.
    "phone":        _get("CV_PHONE", "CANDIDATE_PHONE"),
    # International form. The Japanese CV uses this one: a reader dialling it
    # is not in the UK.
    "phone_intl":   _get("CV_PHONE_INTL", "CANDIDATE_PHONE_INTL"),
    "portfolio":    _get("CV_PORTFOLIO", "https://example.com/"),
    "github":       _get("CV_GITHUB", "https://github.com/CANDIDATE"),
    "linkedin":     _get("CV_LINKEDIN", "https://www.linkedin.com/in/CANDIDATE"),
}


def header_line(lang: str = "en") -> str:
    """The "City | email | phone" line that opens every CV."""
    phone = CONTACT["phone_intl"] if lang == "ja" else CONTACT["phone"]
    return f"{CONTACT['location']} | {CONTACT['email']} | {phone}"


def links_line() -> str:
    """The portfolio/GitHub/LinkedIn line under the header."""
    return (f"Portfolio Website: {CONTACT['portfolio']} | "
            f"GitHub: {CONTACT['github']} | "
            f"LinkedIn: {CONTACT['linkedin']}")
