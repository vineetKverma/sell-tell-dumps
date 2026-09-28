"""Pure-text helpers for golden dataset curation (AIML-2898).

No pandas here on purpose: these carry the decisions most worth unit-testing
(registry repair, topic splitting, masking), and the regular test run does not
install the ``dataset`` dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VERTICALS = ("MH", "HS", "HL", "IS", "TR", "IN")

# The Campaign Topics sheet -- the original in SharePoint, not just our copy --
# had a whole-sheet Replace All applied that wrote vertical names over
# abbreviations everywhere, not only in Industry__c:
#   "Hospitality"  -> "HS - HOSPITALITYitality"
#   "Installation" -> "IN - INDUSTRIALallation"
#   "Comfort"      -> "CoMH - MULTIFAMILYort"
#   "government"   -> "IS - PUBLIC SECTORernment"   (once, in one description)
# These tokens belong only in Industry__c, so in Name and Description they are
# put back. Matching is case-insensitive afterwards, because the replace was
# ("Comfort" had a lowercase "mf"). The original case is lost; "gov" is
# lowercase because its only occurrence is mid-sentence. HL - HEALTHCARE and
# TR - TRADES never occur outside Industry__c (checked against the full sheet).
REGISTRY_DAMAGE = {
    "HS - HOSPITALITY": "Hosp",
    "IN - INDUSTRIAL": "Inst",
    "MH - MULTIFAMILY": "MF",
    "IS - PUBLIC SECTOR": "gov",
}
VERTICAL_TOKENS = (
    "MH - MULTIFAMILY",
    "HS - HOSPITALITY",
    "HL - HEALTHCARE",
    "IS - PUBLIC SECTOR",
    "TR - TRADES",
    "IN - INDUSTRIAL",
)
SKIP_TOPICS = {"do not use"}

# Keyword proxies for the sampling strata -- deliberately loose. They only find
# candidates; every sampled record is labelled and reviewed by hand.
STRATA = {
    "no contact": (
        r"\b(?:not (?:there|in|available)|no one|nobody|unavailable|office (?:was )?closed"
        r"|left (?:a )?(?:flyer|card|catalog|info|voicemail|vm)|no answer)\b"
    ),
    "order placed": r"\b(?:placed (?:an? )?order|ordered|order placed|po #?\d)",
    "quote": r"\bquot(?:e|ed|es|ing)\b",
    "count with unit": (
        r"\b\d+\s?(?:units?|keys|rooms|beds|trucks|vans|sites|jobs|doors|apts?"
        r"|apartments|buildings|properties|turns)\b"
    ),
    "competitor / price": (
        r"\b(?:competitor|cheaper|price[sd]?|pricing|amazon|lowe'?s|home depot"
        r"|grainger|ferguson)\b"
    ),
    "service issue": (
        r"\b(?:backorder(?:ed)?|back order|mispick|damaged|missing|eta"
        r"|late delivery|wrong item)\b"
    ),
    "next step": (
        r"\b(?:follow(?:ing)? up|f/?u|next (?:week|visit|month)"
        r"|will (?:send|call|email)|call back)\b"
    ),
}
SHORT_NOTE_CHARS = 40
HEALTHCARE_PERSON = r"\b(?:patient|resident|mr\.|mrs\.|ms\.)\b"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\b\d{3}[-.\s)]\s?\d{3}[-.\s]\d{4}\b")
_LONG_NUMBER = re.compile(r"\b\d{6,}\b")
_URL = re.compile(r"https?://\S+")
_GUIDE_LABEL = re.compile(r"\b(?:seller|user) guid(?:e|ance)\s*:\s*", re.IGNORECASE)
MOJIBAKE_MARKERS = (chr(0xE2) + chr(0x20AC), chr(0xC3))  # a-hat + euro, A-tilde


def repair_registry_text(text: object) -> str:
    """Undo the Replace All damage in a registry Name or Description."""
    if not isinstance(text, str):
        return ""
    for token, original in REGISTRY_DAMAGE.items():
        text = text.replace(token, original)
    return text


def damage_count(texts: list[object]) -> dict[str, int]:
    """How many of ``texts`` contain each vertical token (should be 0 after repair)."""
    return {
        token: sum(isinstance(t, str) and token in t for t in texts)
        for token in VERTICAL_TOKENS
    }


def title_key(title: str) -> str:
    return " ".join(title.lower().split())


def make_splitter(registry_titles: list[str]):
    """Split a pre-call topics cell on commas, keeping registry titles that
    themselves contain commas ("... $100 off $1,000") in one piece."""
    comma_titles = sorted({t for t in registry_titles if "," in t}, key=len, reverse=True)

    def split(cell: object) -> list[str]:
        if not isinstance(cell, str):
            return []
        found: list[str] = []
        rest = cell
        for title in comma_titles:
            i = rest.lower().find(title.lower())
            if i >= 0:
                found.append(rest[i : i + len(title)].strip())
                rest = rest[:i] + "," + rest[i + len(title) :]
        found += [t.strip() for t in rest.split(",") if t.strip()]
        return found

    return split


@dataclass(frozen=True)
class RegistryTopic:
    title: str
    description: str
    industry: str


class TopicIndex:
    """Look up a pre-call topic title in the (repaired) registry.

    Some titles are listed more than once with different verticals and
    descriptions; the row tagged with the visit's own vertical wins.
    """

    def __init__(self, rows: list[RegistryTopic]) -> None:
        self._by_key: dict[str, list[RegistryTopic]] = {}
        for row in rows:
            if title_key(row.title) in SKIP_TOPICS:
                continue
            self._by_key.setdefault(title_key(row.title), []).append(row)

    @property
    def titles(self) -> list[str]:
        return [rows[0].title for rows in self._by_key.values()]

    def lookup(self, title: str, vertical: str | None) -> RegistryTopic | None:
        rows = self._by_key.get(title_key(title))
        if not rows:
            return None
        if vertical:
            for row in rows:
                if f"{vertical} - " in (row.industry or ""):
                    return row
        return rows[0]


def clean_note(text: object) -> str:
    """Strip carriage returns and undo Windows-1252 mojibake where possible."""
    if not isinstance(text, str):
        return ""
    text = text.replace("_x000D_", "").replace("\r\n", "\n").replace("\r", "\n")
    if any(m in text for m in MOJIBAKE_MARKERS):
        try:
            text = text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text.strip()


def mask_pii(text: str) -> str:
    """Mask what a pattern can find. Names cannot be found this way -- the
    reviewer removes those."""
    text = _EMAIL.sub("[EMAIL]", text)
    text = _PHONE.sub("[PHONE]", text)
    return _LONG_NUMBER.sub("[NUMBER]", text)


def short_description(text: str, limit: int = 300) -> str:
    """A campaign description cut down to what an agent prompt can carry:
    links and guide labels removed, whitespace collapsed, cut at a sentence."""
    text = _GUIDE_LABEL.sub("", _URL.sub("", text or ""))
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else cut.rstrip() + "..."


def strata_for(note: str) -> list[str]:
    lowered = note.lower()
    hits = [name for name, rx in STRATA.items() if re.search(rx, lowered)]
    if len(note.strip()) < SHORT_NOTE_CHARS:
        hits.append("short")
    return hits
