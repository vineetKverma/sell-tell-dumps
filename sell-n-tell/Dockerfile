# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

# Set the working directory in the container
WORKDIR /app

# Install dependencies from the lockfile, so the image runs exactly the
# versions that were tested (uv.lock), not whatever pyproject's ranges resolve
# to on the day of the build. --frozen fails the build if uv.lock is out of
# date with pyproject.toml instead of silently re-resolving.
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"

# Copy the app directory contents into the container
COPY ./app /app/app

# Expose the port Cloud Run uses
EXPOSE 8080

# Run uvicorn server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
