"""Configuração da aplicação (variáveis de ambiente, ver .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "DocOps"
    environment: str = "production"

    database_url: str = "postgresql+psycopg://docops:docops@db:5432/docops"
    redis_url: str = "redis://redis:6379/0"

    secret_key: str = "troque-esta-chave"
    session_hours: int = 12
    cookie_secure: bool = True

    # Primeiro administrador (criado só se o banco não tiver usuários)
    admin_email: str = "admin@docops.local"
    admin_password: str = ""

    # Segurança de login
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    login_rate_limit_per_ip: int = 60
    login_rate_window_seconds: int = 300
    min_password_length: int = 12

    # Coleta AWS: credenciais do servidor (instance profile no EC2 ou variáveis AWS_* on-premises)
    aws_region: str = "us-east-1"
    collector_workers: int = 6
    collector_inner_workers: int = 4
    collector_cost_explorer: bool = True
    collection_timeout_minutes: int = 120

    timezone: str = "America/Sao_Paulo"
    max_upload_mb: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
