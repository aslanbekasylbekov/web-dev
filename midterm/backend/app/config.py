import os

from sqlalchemy.engine import URL


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set")
    return value


class Settings:

    def __init__(self) -> None:
        self.app_name = os.getenv("APP_NAME", "SubTrack API")
        self.database_url = URL.create(
            drivername="postgresql+psycopg2",
            username=_required("POSTGRES_USER"),
            password=_required("POSTGRES_PASSWORD"),
            host=os.getenv("POSTGRES_HOST", "db"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=_required("POSTGRES_DB"),
        )


settings = Settings()
