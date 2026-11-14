"""Model-service settings, all environment overridable."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODEL_", extra="ignore")

    app_name: str = "model-service"
    capabilities: str = "llm,embedding,rerank,asr,image,tts,video,system_one"

    def capability_list(self) -> list[str]:
        return [item.strip() for item in self.capabilities.split(",") if item.strip()]
