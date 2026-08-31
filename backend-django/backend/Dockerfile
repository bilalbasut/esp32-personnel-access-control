FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/firmware_files

EXPOSE 3000

# Runs migrations then starts the app. Django's runserver is fine for a LAN
# panel like this; swap CMD for gunicorn if you want a production WSGI server.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:3000"]
