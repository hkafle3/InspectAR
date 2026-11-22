"""Settings, read from .env in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
PHOTOS_DIR = DATA_DIR / "photos"
ENTRIES_FILE = DATA_DIR / "entries.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# mock = free, no AI (rule-based parsing of the note)
# ollama = free, runs a local model on this laptop (needs the Ollama app)
# anthropic = Claude API (needs ANTHROPIC_API_KEY, costs money)
AI_MODE = os.getenv("AI_MODE", "mock").strip().lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:3b").strip()

PROPERTY_ADDRESS = os.getenv("PROPERTY_ADDRESS") or "123 Example St, Brooklyn, NY"
INSPECTOR_NAME = os.getenv("INSPECTOR_NAME") or "Inspector"
