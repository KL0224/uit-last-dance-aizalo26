FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.8 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY src ./src
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
ENTRYPOINT ["/app/.venv/bin/python", "-m", "datamate"]
CMD ["--help"]
