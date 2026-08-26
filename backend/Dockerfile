FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system pulseexchange && adduser --system --ingroup pulseexchange pulseexchange

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN python -m pip install --upgrade pip && python -m pip install .

USER pulseexchange

EXPOSE 8000

CMD ["uvicorn", "pulseexchange.main:app", "--host", "0.0.0.0", "--port", "8000"]

