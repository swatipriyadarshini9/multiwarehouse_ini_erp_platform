from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://inventory:inventory@localhost:5432/inventory"
    odoo_url: str = "http://localhost:8069"
    odoo_db: str = "inventory"
    odoo_user: str = "admin"
    odoo_password: str = "admin"
    z_service_level: float = 1.65
    forecast_lookback_days: int = 14


settings = Settings()