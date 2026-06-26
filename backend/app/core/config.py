from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # CHIP/


class Settings(BaseSettings):
    API_KEY_SECRET: str = "change-me"
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    TWSE_BASE_URL: str = "https://www.twse.com.tw"
    TWSE_OPENAPI_URL: str = "https://openapi.twse.com.tw"
    TAIFEX_BASE_URL: str = "https://www.taifex.com.tw"
    TDCC_BASE_URL: str = "https://www.tdcc.com.tw"
    SINOPAC_ADAPTER_URL: str = "http://127.0.0.1:8011"

    COLLECT_HOUR_CST: int = 16
    COLLECT_MINUTE_CST: int = 35
    REPORT_HOUR_CST: int = 18
    REPORT_MINUTE_CST: int = 0

    REQUEST_DELAY_MIN: float = 3.0
    REQUEST_DELAY_MAX: float = 6.0

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    REPORT_EMAIL_LIST: str = ""

    ENV: str = "development"
    DEBUG: bool = True

    @property
    def db_path(self) -> Path:
        p = BASE_DIR / "data" / "chip.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def logs_dir(self) -> Path:
        d = BASE_DIR / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def reports_dir(self) -> Path:
        d = BASE_DIR / "data" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
