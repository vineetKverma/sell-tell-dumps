"""Record extraction as a text Gemini call with a fixed JSON schema (AIML-2929).

Standalone: the live agent does not use it yet. ``extract()`` takes the
rep's dictation, the planned topics (with short descriptions where known) and
the account's vertical, and returns one record whose shape the schema fixes.
"""

from app.extraction.campaigns import Registry, load_registry
from app.extraction.catalog import Field, fields_for, load_catalog
from app.extraction.extract import (
    DISCUSSED,
    NOT_DISCUSSED,
    UNCONFIRMED,
    ExtractResult,
    build_prompt,
    evidence_ok,
    extract,
    postprocess,
    quote_in,
    record_model,
)

__all__ = [
    "DISCUSSED", "NOT_DISCUSSED", "UNCONFIRMED", "ExtractResult", "Field", "Registry",
    "build_prompt", "evidence_ok", "extract", "fields_for", "load_catalog", "load_registry", "postprocess",
    "quote_in", "record_model",
]
