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
