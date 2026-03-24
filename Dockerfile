FROM python:3.12-slim

# Шрифт нужен для вывода кириллицы в PDF: базовых шрифтов PDF с ней нет.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY templates ./templates

ENV TAX_REPORTER_TEMPLATES_DIR=/app/templates \
    TAX_REPORTER_CLINICS_PATH=/app/templates/clinics.json \
    TAX_REPORTER_OUTPUT_DIR=/data/out \
    PYTHONUNBUFFERED=1

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/healthz').status_code==200 else 1)"

CMD ["uvicorn", "tax_reporter.api:app", "--host", "0.0.0.0", "--port", "8000"]
