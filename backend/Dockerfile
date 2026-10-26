FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/data/hf REPOPILOT_DATA_DIR=/data
WORKDIR /app

# CPU-only PyTorch first (much smaller than the default GPU build), then everything else.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home app && mkdir -p /data && chown -R app:app /data /app
USER app

EXPOSE 8000
# Apply migrations, then start the production server (long timeout: analysis runs inside the request).
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 900"]
