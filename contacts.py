"""Contact interchange helpers kept separate from the HTTP orchestration."""

import csv
import io
import re


CONTACT_LIST_FIELDS = ("emails", "phones", "addresses")
VCARD_LINE_RE = re.compile(r"^(?P<name>[A-Z-]+)(?:;[^:]*)?:(?P<value>.*)$", re.IGNORECASE)


def clean_text(value, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def clean_list(value, *, limit: int = 12, item_limit: int = 500) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[\n,;]+", value)
    elif isinstance(value, list):
        values = value
    else:
        values = []
    result: list[str] = []
    for candidate in values:
        item = clean_text(candidate, item_limit)
        if item and item.casefold() not in {existing.casefold() for existing in result}:
            result.append(item)
        if len(result) >= limit:
            break
    return result


def normalize_contact(payload: dict) -> dict:
    given_name = clean_text(payload.get("given_name"), 200)
    family_name = clean_text(payload.get("family_name"), 200)
    display_name = clean_text(payload.get("display_name"), 300) or " ".join(
        part for part in (given_name, family_name) if part
    )
    if not display_name:
        raise ValueError("display name is required")
    birthday = clean_text(payload.get("birthday"), 10) or None
    if birthday and not re.fullmatch(r"\d{4}-\d{2}-\d{2}|--\d{2}-\d{2}", birthday):
        raise ValueError("birthday must be YYYY-MM-DD or --MM-DD")
    friend_code = re.sub(r"\s+", "", clean_text(payload.get("openchat_friend_code"), 32))
    if friend_code and not re.fullmatch(r"\d{8}", friend_code):
        raise ValueError("OpenChat friend code must be 8 digits")
    return {
        "display_name": display_name,
        "given_name": given_name,
        "family_name": family_name,
        "company": clean_text(payload.get("company"), 300),
        "job_title": clean_text(payload.get("job_title"), 300),
        "emails": clean_list(payload.get("emails")),
        "phones": clean_list(payload.get("phones")),
        "addresses": clean_list(payload.get("addresses"), limit=6, item_limit=1000),
        "notes": clean_text(payload.get("notes"), 20000),
        "birthday": birthday,
        "openchat_username": clean_text(payload.get("openchat_username"), 200).lstrip("@"),
        "openchat_friend_code": friend_code,
    }


def _unfold_vcard(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _vcard_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_vcards(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    cards: list[dict] = []
    current: dict[str, list[str]] | None = None
    for line in _unfold_vcard(text):
        upper = line.upper()
        if upper == "BEGIN:VCARD":
            current = {}
            continue
        if upper == "END:VCARD":
            if current is not None:
                names = (current.get("N") or [""])[0].split(";")
                family = _vcard_unescape(names[0]) if names else ""
                given = _vcard_unescape(names[1]) if len(names) > 1 else ""
                cards.append(normalize_contact({
                    "display_name": _vcard_unescape((current.get("FN") or [""])[0]),
                    "given_name": given,
                    "family_name": family,
                    "company": _vcard_unescape((current.get("ORG") or [""])[0].split(";")[0]),
                    "job_title": _vcard_unescape((current.get("TITLE") or [""])[0]),
                    "emails": [_vcard_unescape(value) for value in current.get("EMAIL", [])],
                    "phones": [_vcard_unescape(value) for value in current.get("TEL", [])],
                    "addresses": [
                        ", ".join(part for part in _vcard_unescape(value).split(";") if part)
                        for value in current.get("ADR", [])
                    ],
                    "notes": _vcard_unescape((current.get("NOTE") or [""])[0]),
                    "birthday": _vcard_unescape((current.get("BDAY") or [""])[0]),
                    "openchat_username": _vcard_unescape((current.get("X-OPENCHAT-USERNAME") or [""])[0]),
                    "openchat_friend_code": _vcard_unescape((current.get("X-OPENCHAT-FRIEND-CODE") or [""])[0]),
                }))
            current = None
            continue
        if current is None:
            continue
        match = VCARD_LINE_RE.match(line)
        if match:
            current.setdefault(match.group("name").upper(), []).append(match.group("value"))
    return cards


def parse_contact_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    contacts: list[dict] = []
    for row in reader:
        normalized_keys = {str(key or "").strip().lower().replace(" ", "_"): value for key, value in row.items()}
        contacts.append(normalize_contact({
            "display_name": normalized_keys.get("display_name") or normalized_keys.get("name"),
            "given_name": normalized_keys.get("given_name") or normalized_keys.get("first_name"),
            "family_name": normalized_keys.get("family_name") or normalized_keys.get("last_name"),
            "company": normalized_keys.get("company") or normalized_keys.get("organization"),
            "job_title": normalized_keys.get("job_title") or normalized_keys.get("title"),
            "emails": normalized_keys.get("emails") or normalized_keys.get("email"),
            "phones": normalized_keys.get("phones") or normalized_keys.get("phone"),
            "addresses": normalized_keys.get("addresses") or normalized_keys.get("address"),
            "notes": normalized_keys.get("notes"),
            "birthday": normalized_keys.get("birthday"),
            "openchat_username": normalized_keys.get("openchat_username"),
            "openchat_friend_code": normalized_keys.get("openchat_friend_code"),
        }))
    return contacts


def _vcard_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def export_vcards(rows: list[dict]) -> str:
    cards: list[str] = []
    for row in rows:
        lines = [
            "BEGIN:VCARD",
            "VERSION:4.0",
            f"FN:{_vcard_escape(row['display_name'])}",
            f"N:{_vcard_escape(row.get('family_name', ''))};{_vcard_escape(row.get('given_name', ''))};;;",
        ]
        if row.get("company"):
            lines.append(f"ORG:{_vcard_escape(row['company'])}")
        if row.get("job_title"):
            lines.append(f"TITLE:{_vcard_escape(row['job_title'])}")
        lines.extend(f"EMAIL:{_vcard_escape(value)}" for value in row.get("emails", []))
        lines.extend(f"TEL:{_vcard_escape(value)}" for value in row.get("phones", []))
        lines.extend(f"ADR:;;{_vcard_escape(value)};;;;" for value in row.get("addresses", []))
        if row.get("birthday"):
            lines.append(f"BDAY:{row['birthday']}")
        if row.get("notes"):
            lines.append(f"NOTE:{_vcard_escape(row['notes'])}")
        if row.get("openchat_username"):
            lines.append(f"X-OPENCHAT-USERNAME:{_vcard_escape(row['openchat_username'])}")
        if row.get("openchat_friend_code"):
            lines.append(f"X-OPENCHAT-FRIEND-CODE:{row['openchat_friend_code']}")
        lines.extend(("END:VCARD", ""))
        cards.append("\r\n".join(lines))
    return "".join(cards)
