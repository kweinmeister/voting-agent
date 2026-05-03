FROM python:3.11-slim

WORKDIR /app

RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-editable

COPY app/ ./app/
COPY frontend/ ./frontend/

ENV PYTHONUNBUFFERED=1

CMD [".venv/bin/uvicorn", "frontend.main:app", "--host", "0.0.0.0", "--port", "8080"]
