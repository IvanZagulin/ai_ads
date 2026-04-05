#!/bin/bash
set -e

echo "=== Deploying AI Ads Manager ==="

cd ~/ai_ads_manager

# Pull latest images
docker compose pull postgres redis

# Build and start services
docker compose up -d --build backend celery_worker

# Wait for DB to be ready
echo "Waiting for database..."
sleep 5

# Run database migrations
docker compose run --rm backend python -c "
from app.database import engine
from app.models.models import Base
Base.metadata.create_all(engine)
print('Database migrations done')
"

# Build frontend if not already uploaded
if [ -f ~/ai_ads_manager/frontend/dist/index.html ]; then
  echo "Frontend already built locally"
fi

echo "=== Deploy complete ==="
echo "Check: docker compose ps"
echo "Backend: http://localhost:8000/api/health"
