FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NOTES_DATABASE=/app/data/notes.db

WORKDIR /app

RUN addgroup --system notes && adduser --system --ingroup notes notes

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates ./templates
COPY static ./static

RUN mkdir -p /app/data && chown -R notes:notes /app
USER notes

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "app:app"]

