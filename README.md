# SignifyAI - Smart Contract Creator

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2%2B-green)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

AI-powered legal contract generation platform built with Django. Create professional contracts using Google Gemini and OpenAI with multi-jurisdiction compliance.

## Features

- **AI Contract Generation** - Natural language to professional contracts (Service Agreement, NDA, Lease, Employment, Developer Agreements)
- **Multi-Jurisdiction** - Bangladesh, USA, UK, India with country-specific legal clauses
- **OCR Processing** - Extract text from PDFs and images with Gemini Vision API
- **Legal Validation** - AI-powered compliance checking and legal references
- **RESTful API** - Full API access for integration
- **Web Interface** - User-friendly Django templates

## Tech Stack

- **Backend**: Django 4.2+, Python 3.8+
- **AI/ML**: Google Gemini 2.5 Flash, OpenAI GPT-4o-mini
- **Document**: PyMuPDF, Pillow, pdf2image
- **Database**: SQLite (PostgreSQL/MySQL ready)

## Quick Start

**Prerequisites:** Python 3.8+, Poppler ([Windows](https://github.com/oschwartz10612/poppler-windows/releases) | Linux: `apt install poppler-utils` | Mac: `brew install poppler`)

```bash
# Clone and setup
git clone <repository-url>
cd smart_contract_creator
python -m venv venv
venv\Scripts\activate  # Windows | source venv/bin/activate (Linux/Mac)

# Install dependencies
pip install -r requirements.txt

# Configure .env file
SECRET_KEY=your-secret-key
GEMINI_API_KEY=your-gemini-key
OPENAI_API_KEY=your-openai-key

# Run migrations and start
python manage.py migrate
python manage.py runserver
```

**Access:** http://localhost:8000

## API Endpoints

### Contracts
- `POST /generate/` - Generate contract from natural language
- `GET /sections/<contract_type>/` - Get available sections

### OCR
- `POST /ocr/process/` - Extract text from PDF/image
- `POST /ocr/translate/` - Translate extracted text

### REST API
- `GET /api/contract-types/` - List all contract types
- `POST /api/generate/` - API contract generation

## API Example

```python
import requests

# Generate contract
response = requests.post("http://localhost:8000/api/generate/", json={
    "contract_type": "service_agreement",
    "user_prompt": "Web development for $10,000, 3 months",
    "party1_name": "ABC Corp",
    "party2_name": "XYZ Client",
    "jurisdiction": "usa"
})
print(response.json()["contract_content"])
```

## Project Structure

```
smart_contract_creator/
├── config/          # Django settings, URLs
├── apps/
│   ├── contracts/   # Contract generation
│   ├── ocr/        # OCR processing
│   └── api/        # REST API
├── core/
│   └── services/   # AI services (Gemini, OpenAI)
├── templates/      # Web UI
└── requirements.txt
```

## Development

```bash
python manage.py test                    # Run tests
python manage.py createsuperuser         # Create admin
python manage.py makemigrations          # Create migrations
```

## Production Deployment

```bash
# Environment
DEBUG=False
SECRET_KEY=<strong-key>

# Database (PostgreSQL)
pip install psycopg2-binary

# WSGI Server
pip install gunicorn
gunicorn config.wsgi:application
```

## License

MIT License

## Contributors

Contributions welcome! Fork, create a feature branch, and submit a pull request.

---

**Built with Django + AI** | Version 1.0.0 | January 2026
