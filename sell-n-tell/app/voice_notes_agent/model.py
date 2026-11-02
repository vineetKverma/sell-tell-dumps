"""The agent's default model, in one place.

The agent reads it (when VOICE_NOTES_AGENT_MODEL is not set), and the eval
harness reads this file directly, without importing the agent, so a run
records the model the app really uses. No imports here: the harness loads the
file on its own.
"""

DEFAULT_AGENT_MODEL = "gemini-3.8-live"
