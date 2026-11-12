"""Record extraction as a text Gemini call with a fixed JSON schema (AIML-2929).

Standalone: the live agent does not use it yet. ``extract()`` takes the
rep's dictation, the planned topics (with short descriptions where known) and
the account's vertical, and returns one record whose shape the schema fixes.
"""

from app.extraction.campaigns import Registry, load_registry
from app.extraction.catalog import Field, fields_for, load_catalog
from app.extraction.dispositions import load_dispositions
from app.extraction.extract import (
    DISCUSSED,
    NOT_DISCUSSED,
    UNCONFIRMED,
    ExtractResult,
    build_prompt,
    extract,
    postprocess,
    sentences,
    record_model,
)

__all__ = [
    "DISCUSSED", "NOT_DISCUSSED", "UNCONFIRMED", "ExtractResult", "Field", "Registry",
    "build_prompt", "extract", "fields_for", "load_catalog", "load_dispositions", "load_registry", "postprocess",
    "record_model", "sentences",
]
