FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CITATION_DB_PATH=/data/citations.db

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Persist the SQLite database outside the image.
VOLUME ["/data"]
EXPOSE 8501

# Initialize/migrate the DB, then launch the dashboard.
CMD ["sh", "-c", "python -m citation_tracker.cli init && \
    streamlit run app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true"]
