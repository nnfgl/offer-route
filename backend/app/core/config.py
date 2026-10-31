from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OFFER_", env_file=ROOT / ".env", extra="ignore")
    environment: Literal["development", "production", "test"] = "development"
    database_path: Path = ROOT / "data" / "offer.db"
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cookie_secure: bool = False
    session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    auth_rate_limit: int = Field(default=10, ge=1)
    auth_rate_window_seconds: int = Field(default=60, ge=1)
    voice_api_key: SecretStr = SecretStr("")
    voice_webrtc_url: str = ""
    voice_model: str = "qwen3.8-omni-flash-realtime"
    voice_name: str = "Tina"
    voice_review_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    voice_review_model: str = "qwen-plus"
    voice_max_minutes: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="after")
    def validate_production(self):
        if not self.database_path.is_absolute():
            self.database_path = ROOT / self.database_path
        if self.environment == "production":
            if not self.cookie_secure:
                raise ValueError("Production requires OFFER_COOKIE_SECURE=true")
            if not self.allowed_origins or any(
                not origin.startswith("https://") for origin in self.allowed_origins
            ):
                raise ValueError("Production requires explicit HTTPS origins")
        return self
