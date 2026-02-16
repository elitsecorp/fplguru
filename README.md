FPL Guru - safety-critical aviation decision-support (prototype)

This workspace contains a minimal Django project scaffold for FPL Guru.

How to run (Windows PowerShell):
1. Create a virtual environment: python -m venv .venv; .\.venv\Scripts\Activate.ps1
2. Install deps: pip install -r requirements.txt
3. Run migrations: python manage.py migrate
4. Create superuser (optional): python manage.py createsuperuser
5. Run server: python manage.py runserver

Notes:
- Thresholds are in `config/thresholds.yaml` and loaded by services.analyzer
- Business logic lives in `services/analyzer.py` and `app` views; templates contain no business logic
- All algorithms are deterministic and thresholds are explicit
