# Dashboard + tooling in one image. The committed DuckDB file (data/hackathon.duckdb)
# holds every scenario and scored plan, so the image runs without the Gruber API key.
#   docker build -t logiwise .
#   docker run --rm -p 8501:8501 logiwise                 # dashboard on http://localhost:8501
#   docker run --rm logiwise make test                     # tests inside the container
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["python", "-m", "streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.headless=true"]
