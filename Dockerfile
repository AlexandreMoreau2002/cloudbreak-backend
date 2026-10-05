FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Migrations appliquées à chaque démarrage : si elles échouent, le conteneur ne démarre pas
# (l'ancienne version reste servie pendant la mise à jour Swarm). `exec` garde uvicorn en PID 1.
CMD ["sh", "-c", "PYTHONPATH=. alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=10.0.1.0/24"]
