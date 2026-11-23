"""Server configuration. Secret values are never returned by the API."""
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
RUNTIME = ROOT / '.local'
RUNTIME.mkdir(exist_ok=True)
PRODUCTION = os.getenv('APP_ENV', 'local') == 'production'
AI_PROVIDER = os.getenv('AI_PROVIDER', 'openai-compatible')
if AI_PROVIDER == 'morrono':
    # Keep the new provider key separate; never send the old provider's key here.
    morrono = dotenv_values(ROOT / 'secrets/morrono-api.env')
    AI_KEY = os.getenv('MORRONO_API_KEY') or morrono.get('MORRONO_API_KEY') or ''
    AI_BASE = (os.getenv('MORRONO_API_BASE_URL') or morrono.get('MORRONO_API_BASE_URL') or 'https://new-api.morrono.com/v1').rstrip('/')
    AI_MODEL = os.getenv('MORRONO_MODEL') or morrono.get('MORRONO_MODEL') or 'gpt-6.1-terra'
    if AI_BASE != 'https://new-api.morrono.com/v1':
        raise RuntimeError('Morrono requires its verified HTTPS endpoint')
elif AI_PROVIDER == 'openai-compatible':
    AI_KEY = os.getenv('OPENAI_API_KEY', '')
    AI_BASE = os.getenv('OPENAI_BASE_URL', 'https://copa.codyssey.kr/v1').rstrip('/')
    AI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-5-mini')
    if AI_BASE not in {'https://copa.codyssey.kr/v1', 'https://api.openai.com/v1'}:
        raise RuntimeError('Existing provider credentials require their approved HTTPS endpoint')
else:
    raise RuntimeError('Invalid AI provider')
IMAGE_ANALYSIS_ENABLED = os.getenv('IMAGE_ANALYSIS_ENABLED', 'false').lower() == 'true'
GARMENT_IMAGE_MODEL = os.getenv('GARMENT_IMAGE_MODEL') or (morrono.get('MORRONO_IMAGE_MODEL') if AI_PROVIDER == 'morrono' else '') or ''
GARMENT_IMAGE_ENABLED = os.getenv('GARMENT_IMAGE_ENABLED','false').lower() == 'true'
GARMENT_IMAGE_DAILY_LIMIT = int(os.getenv('GARMENT_IMAGE_DAILY_LIMIT', '10')) or None
FIREBASE_CREDENTIAL = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '')
STORAGE = os.getenv('STORAGE_BACKEND', 'local')
if STORAGE not in {'local', 'firestore'}:
    raise RuntimeError('Invalid storage backend')
if PRODUCTION and STORAGE != 'firestore':
    raise RuntimeError('Production requires Firestore; local storage is for local preview only')
LOGIN_REQUIRED = os.getenv('CLOSET_LOGIN_REQUIRED', 'false').lower() == 'true'
BACKGROUND_MUSIC_PATH = Path(os.getenv('BACKGROUND_MUSIC_PATH') or ROOT / 'backend/assets/flower-waiting.mp3')
ORIGINS = set(filter(None, os.getenv('ALLOWED_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000').split(',')))
AI_DAILY_LIMIT = int(os.getenv('AI_DAILY_LIMIT', '100'))
CONVERSATION_RETENTION_DAYS = int(os.getenv('CONVERSATION_RETENTION_DAYS', '5'))
if CONVERSATION_RETENTION_DAYS < 1:
    raise ValueError('CONVERSATION_RETENTION_DAYS must be positive')
