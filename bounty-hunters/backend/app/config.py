import os

class Settings:
    app_name: str = os.getenv("APP_NAME", "Space Bounty Hunters API")
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: str = os.getenv("DB_PORT", "5432")
    db_name: str = os.getenv("DB_NAME", "bounty")
    db_user: str = os.getenv("DB_USER", "bounty_user")
    db_password: str = os.getenv("DB_PASSWORD", "change_me")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

settings = Settings()