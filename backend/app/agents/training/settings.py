from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
LOCAL_ROOT = ROOT / ".local-training"


class TrainingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OFFER_TRAINING_",
        env_file=ROOT / ".env.training-local",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )
    database_backend: Literal["sqlite", "mysql"] = "mysql"
    mysql_host: str = "127.0.0.1"
    mysql_port: int = Field(default=3306, ge=1, le=65535)
    mysql_user: str = "root"
    mysql_password: SecretStr | None = None
    mysql_database: str = "offer_route_training_c_local"
    sqlite_path: Path = LOCAL_ROOT / "training.sqlite3"
    chroma_path: Path = LOCAL_ROOT / "chroma"
    chroma_collection: str = "python_backend_training_c_local_v1"
    sql_timeout_seconds: float = Field(default=3, ge=0.05, le=10)
    sql_max_rows: int = Field(default=200, ge=1, le=1000)
    sql_max_steps: int = Field(default=200000, ge=1000, le=2000000)

    @field_validator("mysql_database")
    @classmethod
    def isolated_database_only(cls, value: str) -> str:
        if value != "offer_route_training_c_local":
            raise ValueError("Only the isolated Task C local database is allowed")
        return value

    @field_validator("mysql_host")
    @classmethod
    def local_mysql_only(cls, value: str) -> str:
        if value not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("This local experiment only connects to a loopback MySQL server")
        return value
