import os
import secrets


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8456"))
DATA_DIR = os.getenv("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.getenv("DB_PATH") or os.path.join(DATA_DIR, "fastmetric.db")
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
OFFLINE_AFTER_SECONDS = int(os.getenv("OFFLINE_AFTER_SECONDS", "900"))
BELL_SOUND = os.getenv("BELL_SOUND", "true").lower() == "true"

TOKEN_ENV = os.getenv("TOKEN")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")