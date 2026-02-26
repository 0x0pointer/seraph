# Project 73 — Deployment Guide

## Local Development

### Prerequisites
- Python 3.11+ (Python 3.13 supported)
- Node.js 20+
- The llm-guard library (install via pip or from source)

### Backend

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment config
cp ../.env.example .env
# Edit .env — set a strong SECRET_KEY at minimum

# Seed the database (creates admin user + guardrail configs)
python seed.py

# Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API available at: `http://localhost:8000`
Interactive Swagger docs: `http://localhost:8000/docs`

---

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend available at: `http://localhost:3000`

---

### Default Credentials (seed.py)

- Username: `admin`
- Password: `admin`

**Change the admin password immediately after first login** via Dashboard → Settings → Change Password.

---

### Chatbot (Optional)

```bash
cd chatbot
pip install flask python-dotenv openai requests

# Create chatbot/.env
cat > .env << EOF
OPENAI_API_KEY=sk-...
TALIX_API_URL=http://localhost:8000
TALIX_CONNECTION_KEY=<your connection API key from dashboard>
OPENAI_MODEL=gpt-4o-mini
PORT=3001
EOF

python server.py
```

Chatbot available at: `http://localhost:3001`

---

## Environment Variables

Create `backend/.env`:

```env
# Required — generate with: openssl rand -hex 32
SECRET_KEY=your-random-64-char-hex-string

# Database (default: SQLite)
DATABASE_URL=sqlite+aiosqlite:///./project73.db

# CORS — list of allowed frontend origins
CORS_ORIGINS=["http://localhost:3000"]

# Cloudflare Turnstile (use test keys in development)
TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

# Frontend URL (used in password-reset email links)
FRONTEND_URL=http://localhost:3000

# JWT settings
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# SMTP — leave smtp_host blank to disable email sending
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@project73.ai
SMTP_TLS=true
```

---

## Production (Raspberry Pi + Cloudflare Tunnel)

### 1. Install dependencies

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nodejs npm nginx git
```

### 2. Clone and configure

```bash
git clone https://github.com/JorgeCarvalhoPT/Project-73.git project73
cd project73

# Create backend/.env with production values
nano backend/.env
```

### 3. Install backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install --ignore-requires-python llm-guard==0.3.16
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" aiosqlite \
    pydantic-settings "python-jose[cryptography]" "passlib[bcrypt]" \
    "bcrypt==4.0.1" python-multipart httpx
python seed.py
```

### 4. Build frontend

```bash
cd ../frontend
npm install --legacy-peer-deps
npm run build
```

### 5. Systemd services

`/etc/systemd/system/project73-backend.service`:
```ini
[Unit]
Description=Project 73 Backend
After=network.target

[Service]
User=kuna
WorkingDirectory=/home/kuna/project73/backend
EnvironmentFile=/home/kuna/project73/backend/.env
ExecStart=/home/kuna/project73/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/project73-frontend.service`:
```ini
[Unit]
Description=Project 73 Frontend
After=network.target

[Service]
User=kuna
WorkingDirectory=/home/kuna/project73/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/node node_modules/.bin/next start --port 3000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now project73-backend project73-frontend
```

### 6. Nginx

`/etc/nginx/sites-available/project73`:
```nginx
server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/project73 /etc/nginx/sites-enabled/project73
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl restart nginx
```

### 7. Cloudflare Tunnel

```bash
# Install
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create project73

# Config at /etc/cloudflared/config.yml
sudo mkdir -p /etc/cloudflared
sudo tee /etc/cloudflared/config.yml << EOF
tunnel: <TUNNEL-ID>
credentials-file: /etc/cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: project73.ai
    service: http://localhost:80
  - hostname: www.project73.ai
    service: http://localhost:80
  - service: http_status:404
EOF

# Route DNS
cloudflared tunnel route dns project73 project73.ai
cloudflared tunnel route dns project73 www.project73.ai

# Start as service
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

---

## Security Checklist

- [ ] Generate a strong `SECRET_KEY` (`openssl rand -hex 32`)
- [ ] Change the default `admin` password immediately after seeding
- [ ] Set `CORS_ORIGINS` to your production domain only
- [ ] Configure Cloudflare SSL/TLS → **Full** mode
- [ ] Enable **Always Use HTTPS** in Cloudflare
- [ ] Enable **Bot Fight Mode** in Cloudflare Security settings
- [ ] Never commit `.env` files to git (`.gitignore` covers this)
- [ ] Set up SMTP for password reset emails
