# Fly.io builds this image. Kept deliberately plain: the app is a single
# uvicorn process reading a SQLite file off a mounted volume.
FROM python:3.12-slim

WORKDIR /app

# Dependencies in their own layer, so editing application code does not
# reinstall the world on every deploy.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Must match fly.toml's internal_port. The app reads $PORT so the same image
# runs anywhere that injects one.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT}"]
