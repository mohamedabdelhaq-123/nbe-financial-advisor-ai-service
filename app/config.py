from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    use_mock_llm: bool = False

    # Required only when use_mock_llm is False; safe to omit in mock mode
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = "__mock__"   # placeholder — unused in mock mode
    model_name: str = "gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# Instantiated once at import time — raises ValidationError immediately if vars are missing
settings = Settings()

if not settings.use_mock_llm and settings.openai_api_key == "__mock__":
    raise RuntimeError(
        "OPENAI_API_KEY must be set when USE_MOCK_LLM is false. "
        "Set USE_MOCK_LLM=1 in .env to run fully offline."
    )
