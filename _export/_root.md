# _root

branch: `development`  commit: `85b108c`  files: 6

<!-- FILE: .dockerignore -->
````text
.env
.venv/
__pycache__/
*.py[cod]
.git/
.gitignore
.agents/
.DS_Store
Thumbs.db
tests/
````
<!-- END: .dockerignore -->

<!-- FILE: .gitignore -->
````text
# ─────────────────────────────────────────────
# Python
# ─────────────────────────────────────────────
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[cod]
*$py.class
*.pyo

# C extensions
*.so

# Distribution / packaging
build/
dist/
.eggs/
*.egg-info/
*.egg
MANIFEST

# PyInstaller
*.spec

# Unit test / coverage
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py,cover
.hypothesis/
.pytest_cache/
pytestdebug.log

# Type checkers
.mypy_cache/
.dmypy.json
dmypy.json
.pytype/
.pyre/

# ─────────────────────────────────────────────
# Virtual Environments
# ─────────────────────────────────────────────
.venv/
venv/
ENV/
env/
env.bak/
venv.bak/
.python-version

# ─────────────────────────────────────────────
# uv (Python package manager)
# ─────────────────────────────────────────────
# uv.lock is intentionally NOT ignored — commit it for reproducible installs.
# Ignore the uv cache dir if it ever ends up in the project:
.uv/

# ─────────────────────────────────────────────
# Environment & Secrets
# ─────────────────────────────────────────────
.env
.env.*
!.env.example
*.pem
*.key
secrets/

# ─────────────────────────────────────────────
# Node / JavaScript
# ─────────────────────────────────────────────
node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.pnpm-debug.log*
.npm/
.yarn/

# ─────────────────────────────────────────────
# Build Outputs
# ─────────────────────────────────────────────
dist/
build/
out/
target/
*.war
*.jar
*.class

# ─────────────────────────────────────────────
# Logs
# ─────────────────────────────────────────────
*.log
logs/
*.log.*

# ─────────────────────────────────────────────
# IDE & Editors
# ─────────────────────────────────────────────
# JetBrains (PyCharm, IntelliJ, etc.)
.idea/
*.iml
*.iws
*.ipr

# VS Code
.vscode/
*.code-workspace

# Sublime Text
*.sublime-project
*.sublime-workspace

# Vim / Neovim
*.swp
*.swo
*~

# ─────────────────────────────────────────────
# OS Generated
# ─────────────────────────────────────────────
# macOS
.DS_Store
.AppleDouble
.LSOverride
._*

# Windows
Thumbs.db
ehthumbs.db
Desktop.ini
$RECYCLE.BIN/

# Linux
*~

# ─────────────────────────────────────────────
# Unit Test Reports
# ─────────────────────────────────────────────
TEST*.xml
junit*.xml

# ─────────────────────────────────────────────
# Applications / Binaries
# ─────────────────────────────────────────────
*.app
*.exe

# ─────────────────────────────────────────────
# Large Media Files
# ─────────────────────────────────────────────
*.mp4
*.tiff
*.avi
*.flv
*.mov
*.wmv
*.mkv
*.webm
*.mp3
*.wav

.agents/
.adk/
*.adk/
app.voice_notes_agent
committed_notes.json
````
<!-- END: .gitignore -->

<!-- FILE: Dockerfile -->
````text
# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

# Set the working directory in the container
WORKDIR /app

# Copy the pyproject.toml and README.md for dependency installation
COPY pyproject.toml README.md ./

# Install dependencies using pip (you can also use uv)
RUN pip install --no-cache-dir .

# Copy the app directory contents into the container
COPY ./app /app/app

# Expose the port Cloud Run uses
EXPOSE 8080

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
````
<!-- END: Dockerfile -->

<!-- FILE: pyproject.toml -->
````toml
[project]
name = "voice-notes-logger"
version = "0.1.0"
description = "Agentic AI Voice Notes Logger - dynamic ADK Gemini Live dictation app for field sales reps"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "Apache-2.0" }

dependencies = [
    "google-adk>=1.32.0",
    "fastapi>=0.115.0",
    "python-dotenv>=1.0.0",
    "uvicorn[standard]>=0.32.0",
    "httpx>=0.27.0",
    "google-cloud-bigquery>=3.42.2",
    "google-cloud-storage>=3.13.1",
    "google-cloud-bigquery-storage>=2.41.0",
    "pyarrow>=25.0.1",
]

# A dependency group rather than an optional-dependencies extra: `uv run` and
# `uv sync` install the `dev` group by default, so `uv run pytest tests/ -q`
# works with no flags. As an extra it needed `--extra dev`, and the bare command
# failed with "program not found".
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 80
target-version = "py310"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle
    "F",   # pyflakes
    "I",   # isort
    "C",   # flake8-comprehension
    "PL",  # Pylint rules
    "B",   # flake8-bugbear
    "UP",  # pyupgrade
    "RUF", # ruff specific rules
]
ignore = [
    "E501",    # line length (long prompts, URLs)
    "PLR0913", # too many arguments
    "C901",    # too complex
    "PLR0915", # too many statements
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.hatch.build.targets.wheel]
packages = ["app"]
````
<!-- END: pyproject.toml -->

<!-- FILE: README.md -->
````markdown
# Agentic AI Voice Notes Logger

A dynamic, agentic voice-dictation app for field sales reps, built on **Google
ADK** + the **Gemini Live API** (bidirectional audio streaming) and **FastAPI**.

A rep speaks unstructured notes about a customer visit. The app detects when
they stop talking (VAD), extracts a single structured CRM record via one Gemini
function call, reads back a spoken confirmation, and commits to the CRM on
verbal approval.

```text
[User speaks notes] -> [VAD silence stop-trigger] -> [single Mega-Payload tool call]
   -> [spoken confirmation] -> ["Save" / "Change …"] -> [commit to CRM] -> [end]
```

## How the spec maps to the code

| Spec step | Implementation |
|-----------|----------------|
| **1. Dynamic session init & open voice capture** | `before_agent_callback` in `app/voice_notes_agent/agent.py` fetches the campaign-specific schema/instructions from `GET /api/v1/config/agent-schema` and injects them into the system prompt. No trigger words required. |
| **2. VAD stop-trigger (silence)** | Audio streams continuously and the model's automatic VAD (`RealtimeInputConfig.automatic_activity_detection.silence_duration_ms` in `app/main.py`) finalizes each spoken turn after the silence threshold. The browser shows a live silence countdown and gates the mic while the agent speaks, then re-opens it for the rep's response. **Note:** the spec asks for 2.5–3.0s, but the Live API caps `silence_duration_ms` at **2000ms**, so the value is clamped to that maximum. |
| **3. Single-function extraction (temp 0.1 / top_p 0.8)** | `generate_content_config` on the agent enforces determinism; the prompt forces a single `stage_visit_notes` "Mega-Payload" tool call before any freeform text. The payload carries an overall `event_type` plus a `topics` list — one entry per discussion topic, **each with its own `disposition_code` and `executive_summary`**. |
| **4. Implicit confirmation + generative playback** | The `stage_visit_notes` tool POSTs to `/api/v1/notes/stage`, which builds the confirmation string; the native-audio model speaks it back (AUDIO modality). |
| **5. Branching (save vs. correction)** | "Save" → `commit_visit_notes` → `POST /api/v1/notes/commit`. A correction → re-call `stage_visit_notes` with the updated payload and re-confirm. |

The ADK tools call the REST API over HTTP (true to the spec); the REST API is
backed by an in-memory mock config DB + CRM store in
`app/voice_notes_agent/mock_db.py`.

## API spec endpoints

- `GET  /api/v1/config/agent-schema?campaign_type=...` — dynamic agent config
- `POST /api/v1/notes/stage` — stage extracted `StagedVisitPayload`
- `POST /api/v1/notes/commit` — commit a staged payload to the CRM
- `GET  /api/v1/notes/committed` — (debug) inspect committed records

Try a different `campaign_type` (`standard_sales`, `enterprise_field`,
`renewals`) to see different allowed event types and disposition registries
injected dynamically.

## Run it locally

```bash
uv sync                       # or: pip install -e .
# Configure app/.env (GCP project/location for Vertex AI, or an API key).
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000, pick a campaign, press the mic, and dictate. The
mic auto-stops on a pause; review the staged record, then say **"Save"** (or
**"Change the event type to a phone call"**).

> A **native-audio** Gemini Live model (`gemini-live-2.5-flash-native-audio`) is
> required for spoken confirmation playback. With a half-cascade model the app
> falls back to text replies.

## Cloud Deployment

The service is fully packaged via `Dockerfile` to deploy seamlessly to Google Cloud Run. 

```bash
gcloud run deploy sell-n-tell \
  --source . \
  --region us-east1 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=your-project,GOOGLE_CLOUD_LOCATION=us-east1,VOICE_NOTES_API_BASE=http://localhost:8080,VOICE_NOTES_AGENT_MODEL=gemini-live-2.5-flash-native-audio"
```
*(See `DEPLOYMENT.md` for a deeper architectural breakdown of Cloud Run vs Vertex AI Agent Engine.)*

## Project layout

```text
app/
  main.py                       FastAPI: REST spec + WebSocket bridge + static
  .env                          Model / GCP / VAD / API-base config
  voice_notes_agent/
    agent.py                    Dynamic agent (config injection + instruction provider)
    tools.py                    stage_visit_notes / commit_visit_notes (HTTP -> REST)
    mock_db.py                  Mock config registry + CRM store
  static/                       Frontend (UI + audio worklets + client VAD + Service Worker)
Dockerfile                      Cloud Run container definition
```
````
<!-- END: README.md -->

<!-- FILE: requirements.txt -->
````text
aiosqlite==0.22.1
annotated-doc==0.0.4
annotated-types==0.7.0
anyio==4.14.2
attrs==26.1.0
Authlib==1.7.2
certifi==2026.6.17
cffi==2.1.0
charset-normalizer==3.4.9
click==8.4.2
colorama==0.4.6
cryptography==49.0.0
distro==1.9.0
fastapi==0.139.2
google-adk==2.5.0
google-auth==2.55.2
google-genai==2.12.1
graphviz==0.21
h11==0.16.0
httpcore==1.0.9
httptools==0.8.0
httpx==0.28.1
idna==3.18
joserfc==1.7.3
jsonschema==4.26.0
jsonschema-specifications==2025.9.1
opentelemetry-api==1.42.1
opentelemetry-sdk==1.42.1
opentelemetry-semantic-conventions==0.63b1
packaging==26.2
pyasn1==0.6.4
pyasn1_modules==0.4.2
pycparser==3.0
pydantic==2.13.4
pydantic_core==2.46.4
python-dotenv==1.2.2
python-multipart==0.0.32
PyYAML==6.0.3
referencing==0.37.0
requests==2.34.2
rpds-py==2026.6.3
sniffio==1.3.1
starlette==1.3.1
tenacity==9.1.4
typing-inspection==0.4.2
typing_extensions==4.16.0
tzdata==2026.3
tzlocal==5.4.4
urllib3==2.7.0
uvicorn==0.51.0
-e git+https://praptiyadav@bitbucket.org/fm_ebiz/sell-n-tell.git@b7aa8d6d1d89188d923ad94b2b9004e7fe9d238d#egg=voice_notes_logger
watchdog==6.0.0
watchfiles==1.2.0
websockets==15.0.1
````
<!-- END: requirements.txt -->

