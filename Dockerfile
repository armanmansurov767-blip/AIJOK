FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DOCAGENT_DATA_DIR=/data DOCAGENT_HOST=0.0.0.0
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN useradd --create-home docagent && mkdir -p /data && chown docagent /data
USER docagent
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "app", "serve"]
