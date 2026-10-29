from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    Secret_Key: str
    Algorithm: str = "HS256"
    Access_Token_Expire_Minutes: int = 60 * 24 # 1 day
    Database_URL: str = "postgresql+asyncpg://postgres:redblox009@localhost/sallon_db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()