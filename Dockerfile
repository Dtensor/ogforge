# ogforge production image.
FROM python:3.11-slim

# DejaVu fonts: python:slim ships NO TrueType fonts, so Pillow would fall back to a
# tiny bitmap font and the OG images would look broken. imaging._load_font() looks for
# /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf — install it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080

# gunicorn process manager + uvicorn ASGI workers. 2 workers on a shared-cpu-1x.
CMD ["gunicorn", "app.main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "2", "-b", "0.0.0.0:8080", \
     "--timeout", "60", "--access-logfile", "-"]
