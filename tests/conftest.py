import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough")
os.environ.setdefault("OIDC_CLIENT_ID", "test-client")
os.environ.setdefault("OIDC_CLIENT_SECRET", "test-secret")
os.environ.setdefault("OIDC_ISSUER", "https://auth.example.test/application/o/openshare/")
os.environ.setdefault("PUBLIC_URL", "https://share.example.test")
os.environ.setdefault("SHARE_API_KEY", "test-share-key")
os.environ.setdefault("STORAGE_ROOT", "/tmp/openshare-pytest-storage")
os.environ.setdefault("DATABASE_FILE", "/tmp/openshare-pytest.db")
