import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    bot_token: str
    webhook_base_url: str | None
    webhook_secret: str
    port: int

    @property
    def use_webhook(self) -> bool:
        return bool(self.webhook_base_url)

    @property
    def webhook_path(self) -> str:
        # В путь идёт секрет, а не токен, чтобы токен не светился в URL и логах
        return f"/webhook/{self.webhook_secret}"

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url}{self.webhook_path}"


def _load_dotenv(path: str = ".env") -> None:
    """Простейшая загрузка .env для локального запуска (без внешних зависимостей)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> Config:
    _load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Переменная окружения BOT_TOKEN не задана")

    base_url = (
        os.getenv("WEBHOOK_BASE_URL", "").strip()
        or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        or None
    )
    if base_url:
        base_url = base_url.rstrip("/")

    # Telegram допускает в secret_token только A-Z, a-z, 0-9, _ и -
    secret = os.getenv("WEBHOOK_SECRET", "").strip() or secrets.token_urlsafe(32)

    port = int(os.getenv("PORT", "8080"))

    return Config(
        bot_token=token,
        webhook_base_url=base_url,
        webhook_secret=secret,
        port=port,
    )
