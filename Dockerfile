FROM python:3.13-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/francocorreasosa/umbrel-tempsensing"
LABEL org.opencontainers.image.description="Local Xiaomi Bluetooth temperature and humidity history"
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 1000 --create-home tempsensing
COPY sensors.py .
COPY tempsensing ./tempsensing
USER 1000:1000
EXPOSE 8080
CMD ["gunicorn", "tempsensing.web:create_app()", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--access-logfile", "-"]
