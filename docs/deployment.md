# Talix Shield — Deployment Guide

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- The llm-guard library available at `../llmguard/llm-guard`

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp ../.env.example .env
# Edit .env and set a strong SECRET_KEY

# Seed the database (creates admin user + sample configs)
python seed.py

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000
Interactive docs at http://localhost:8000/docs

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The frontend will be available at http://localhost:3000

### Default Credentials
- Username: `admin`
- Password: `admin`

**Change the admin password immediately in production!**

---

## Docker Compose (Recommended)

### Quick Start

```bash
# Copy environment file
cp .env.example .env

# Edit .env with a secure SECRET_KEY
nano .env

# Build and start all services
docker-compose up --build

# The app is now running at:
# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### Stopping Services

```bash
docker-compose down

# To also remove volumes (database data):
docker-compose down -v
```

---

## Production Deployment

### Security Checklist

1. **Change the SECRET_KEY** — use a cryptographically random 64-char string:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

2. **Change default admin password** in seed.py or via the settings page.

3. **Set CORS_ORIGINS** to your production domain:
   ```
   CORS_ORIGINS=["https://your-domain.com"]
   ```

4. **Use HTTPS** — put the services behind an nginx reverse proxy with TLS.

5. **Use PostgreSQL** for production instead of SQLite:
   ```
   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/talix_shield
   ```
   Add `asyncpg` to requirements.txt.

### Nginx Configuration

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL configuration
    ssl_certificate /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;

    # Frontend
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Backend API
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key (required) | changeme... |
| `ALGORITHM` | JWT algorithm | HS256 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token TTL | 60 |
| `DATABASE_URL` | SQLAlchemy connection URL | sqlite+aiosqlite:///./talix_shield.db |
| `CORS_ORIGINS` | Allowed CORS origins (JSON array) | ["http://localhost:3000"] |
| `DEBUG` | Enable debug logging | false |
| `NEXT_PUBLIC_API_URL` | Frontend API base URL | /api |
