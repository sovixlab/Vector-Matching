# 🔍 Vector Matching

Een Django applicatie voor intelligente vector matching met OpenAI embeddings en PostgreSQL pgvector.

## 🚀 Features

- **AI Embeddings**: OpenAI GPT embeddings voor intelligente tekstverwerking
- **Vector Database**: PostgreSQL met pgvector voor snelle vector matching
- **Modern UI**: TailwindCSS + DaisyUI voor een mooie interface
- **Production Ready**: Geoptimaliseerd voor deployment op Render
- **Health Monitoring**: Health check endpoint voor monitoring

## 🛠️ Tech Stack

- **Backend**: Django 4.2 LTS, Python 3.12
- **Database**: PostgreSQL 15 + pgvector
- **Frontend**: TailwindCSS + DaisyUI
- **AI**: OpenAI API
- **Deployment**: Render
- **Webserver**: Gunicorn + WhiteNoise

## 📋 Vereisten

- Python 3.12+
- Node.js 18+ (voor TailwindCSS)
- PostgreSQL 15+ met pgvector extensie
- OpenAI API key

## 🏃‍♂️ Lokale Installatie

### 1. Repository klonen

```bash
git clone <repository-url>
cd vector-matching
```

### 2. Python environment opzetten

```bash
# Virtual environment maken
python -m venv venv

# Activeren (Windows)
venv\Scripts\activate

# Activeren (macOS/Linux)
source venv/bin/activate

# Dependencies installeren
pip install -r requirements.txt
```

### 3. Node.js dependencies

```bash
npm install
```

### 4. Environment configuratie

```bash
# Kopieer env.example naar .env
cp env.example .env

# Bewerk .env met je eigen waarden
# - SECRET_KEY: Genereer een nieuwe Django secret key
# - DATABASE_URL: Je PostgreSQL connection string
# - OPENAI_API_KEY: Je OpenAI API key
```

### 5. Database setup

```bash
# Maak een PostgreSQL database aan
createdb vector_matching

# Voer migraties uit
python manage.py migrate
```

### 6. TailwindCSS builden

```bash
npm run build-css
```

### 7. Static files collecten

```bash
python manage.py collectstatic
```

### 8. Server starten

```bash
python manage.py runserver
```

De applicatie is nu beschikbaar op `http://localhost:8000`

## 🧪 Testing

```bash
# Django checks uitvoeren
python manage.py check

# Health check testen
curl http://localhost:8000/healthz
```

## 🚀 Render Deployment

### 1. Repository naar GitHub pushen

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### 2. Render service aanmaken

1. Ga naar [Render Dashboard](https://dashboard.render.com)
2. Klik "New +" → "Blueprint"
3. Verbind je GitHub repository
4. Render zal automatisch de `render.yaml` configuratie gebruiken

### 3. Environment variables instellen

In de Render dashboard, voeg toe:
- `OPENAI_API_KEY`: Je OpenAI API key
- `SECRET_KEY`: Genereer een nieuwe (of laat Render dit doen)
- `DEBUG`: `False`
- `ALLOWED_HOSTS`: Je Render URL
- `CSRF_TRUSTED_ORIGINS`: Je Render URL

### 4. Database

Render zal automatisch een PostgreSQL database met pgvector extensie aanmaken.

## 📁 Project Structuur

```
vector-matching/
├── vector_matching/          # Django project
│   ├── settings.py          # Configuratie
│   ├── urls.py              # URL routing
│   └── wsgi.py              # WSGI configuratie
├── vector_matching_app/     # Django app
│   ├── models.py            # Database modellen
│   ├── views.py             # Views
│   ├── urls.py              # App URLs
│   └── migrations/          # Database migraties
├── services/                # Services
│   └── openai_client.py     # OpenAI integratie
├── templates/               # HTML templates
│   ├── base.html            # Base template
│   └── index.html           # Homepage
├── static/                  # Static files
├── assets/                  # Source assets
│   └── tailwind.css         # TailwindCSS source
├── requirements.txt         # Python dependencies
├── package.json             # Node.js dependencies
├── tailwind.config.js       # TailwindCSS configuratie
├── render.yaml              # Render deployment config
└── README.md                # Deze file
```

## 🔧 Development

### TailwindCSS development

Voor development met hot reload:

```bash
npm run build-css-dev
```

### Nieuwe migraties

```bash
python manage.py makemigrations
python manage.py migrate
```

### Admin interface

```bash
python manage.py createsuperuser
```

Ga naar `/admin/` voor de Django admin interface.

## 📊 Health Check

De applicatie heeft een health check endpoint op `/healthz` dat de volgende informatie teruggeeft:

```json
{
  "status": "ok",
  "database": "ok",
  "openai": "ok",
  "debug": false
}
```

## 🤝 Contributing

1. Fork de repository
2. Maak een feature branch (`git checkout -b feature/amazing-feature`)
3. Commit je changes (`git commit -m 'Add amazing feature'`)
4. Push naar de branch (`git push origin feature/amazing-feature`)
5. Open een Pull Request

## 📄 License

Dit project is gelicenseerd onder de MIT License.

## 🆘 Support

Voor vragen of problemen, open een issue in de GitHub repository.
