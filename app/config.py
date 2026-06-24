import os
from pathlib import Path
from dotenv import load_dotenv, set_key

# Get workspace root directory
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Load current env variables
load_dotenv(ENV_PATH)

# Ensure data directory exists
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

class Config:
    @staticmethod
    def get_api_key() -> str:
        return os.getenv("GEMINI_API_KEY", "")

    @staticmethod
    def set_api_key(api_key: str):
        os.environ["GEMINI_API_KEY"] = api_key
        # Save to .env file for persistence
        set_key(str(ENV_PATH), "GEMINI_API_KEY", api_key)

    def get_vector_store_path() -> Path:
        return DATA_DIR / "vector_store.json"

    @staticmethod
    def get_settings():
        return {
            "api_key_configured": bool(os.getenv("GEMINI_API_KEY")),
            "chunk_size": int(os.getenv("RAG_CHUNK_SIZE", 600)),
            "chunk_overlap": int(os.getenv("RAG_CHUNK_OVERLAP", 100)),
            "temperature": float(os.getenv("RAG_TEMPERATURE", 0.3)),
            "chat_model": os.getenv("RAG_CHAT_MODEL", "gemini-1.5-flash"),
            "llm_provider": os.getenv("RAG_LLM_PROVIDER", "ollama"),
            "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "ollama_chat_model": os.getenv("OLLAMA_CHAT_MODEL", "llama3"),
            "ollama_embedding_model": os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        }

    @staticmethod
    def save_settings(settings: dict):
        # Update local environment
        for key, value in settings.items():
            if key == "api_key":
                if value:
                    Config.set_api_key(value)
            elif key == "chunk_size":
                os.environ["RAG_CHUNK_SIZE"] = str(value)
                set_key(str(ENV_PATH), "RAG_CHUNK_SIZE", str(value))
            elif key == "chunk_overlap":
                os.environ["RAG_CHUNK_OVERLAP"] = str(value)
                set_key(str(ENV_PATH), "RAG_CHUNK_OVERLAP", str(value))
            elif key == "temperature":
                os.environ["RAG_TEMPERATURE"] = str(value)
                set_key(str(ENV_PATH), "RAG_TEMPERATURE", str(value))
            elif key == "chat_model":
                os.environ["RAG_CHAT_MODEL"] = str(value)
                set_key(str(ENV_PATH), "RAG_CHAT_MODEL", str(value))
            elif key == "llm_provider":
                os.environ["RAG_LLM_PROVIDER"] = str(value)
                set_key(str(ENV_PATH), "RAG_LLM_PROVIDER", str(value))
            elif key == "ollama_base_url":
                os.environ["OLLAMA_BASE_URL"] = str(value)
                set_key(str(ENV_PATH), "OLLAMA_BASE_URL", str(value))
            elif key == "ollama_chat_model":
                os.environ["OLLAMA_CHAT_MODEL"] = str(value)
                set_key(str(ENV_PATH), "OLLAMA_CHAT_MODEL", str(value))
            elif key == "ollama_embedding_model":
                os.environ["OLLAMA_EMBEDDING_MODEL"] = str(value)
                set_key(str(ENV_PATH), "OLLAMA_EMBEDDING_MODEL", str(value))
