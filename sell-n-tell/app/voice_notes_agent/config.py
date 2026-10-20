import os

API_BASE = os.getenv("VOICE_NOTES_API_BASE", "http://localhost:8000")

# Inactivity / Silence Nudge configuration
VOICE_NOTES_SILENCE_TIMEOUT_SECONDS = float(
    os.getenv("VOICE_NOTES_SILENCE_TIMEOUT_SECONDS", "15")
)
VOICE_NOTES_MAX_SILENCE_PROMPTS = int(
    os.getenv("VOICE_NOTES_MAX_SILENCE_PROMPTS", "3")
)
