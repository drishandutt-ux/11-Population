#!/bin/bash
# 11 Minds Army — dev startup script
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "========================================="
echo "  11 Minds Army — Starting dev servers"
echo "========================================="

# 1. Start infrastructure
echo ""
echo "▶ Starting PostgreSQL + Redis..."
docker compose -f "$ROOT/docker-compose.yml" up -d
echo "  Waiting for services..."
sleep 3

# 2. Backend
echo ""
echo "▶ Setting up Python backend..."
cd "$BACKEND"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created .env from .env.example — EDIT IT to add your ANTHROPIC_API_KEY"
fi

if [ ! -d venv ]; then
  python3 -m venv venv
  echo "  Created virtualenv"
fi
source venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "▶ Starting FastAPI backend on http://localhost:8000 ..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 3. Frontend
echo ""
echo "▶ Setting up Next.js frontend..."
cd "$FRONTEND"
if [ ! -d node_modules ]; then
  npm install
fi
echo ""
echo "▶ Starting Next.js frontend on http://localhost:3000 ..."
npm run dev &
FRONTEND_PID=$!

echo ""
echo "========================================="
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  API Docs: http://localhost:8000/docs"
echo "========================================="
echo ""
echo "Press Ctrl+C to stop all services"

trap "kill $BACKEND_PID $FRONTEND_PID; docker compose -f '$ROOT/docker-compose.yml' stop" INT
wait
