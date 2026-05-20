"""Environment variable management via pydantic-settings — single source of truth for the whole pipeline."""

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # required API keys
    anthropic_api_key: str = Field(default="", description="Anthropic API key (not required when mock_claude=true)")
    google_api_key: str = Field(default="", description="Gemini Imagen 3 (thumbnails, Phase 2)")

    # optional keys
    tavily_api_key: str = Field(default="", description="Tavily web search helper")

    # X (Twitter)
    twitter_bearer_token: str = Field(default="")
    twitter_api_key: str = Field(default="")
    twitter_api_secret: str = Field(default="")
    twitter_access_token: str = Field(default="")
    twitter_access_secret: str = Field(default="")

    # Threads
    threads_access_token: str = Field(default="")
    threads_user_id: str = Field(default="")

    # Substack
    substack_email: str = Field(default="")
    substack_password: str = Field(default="")
    substack_publication_url: str = Field(default="")

    # WhatsApp Business Cloud API
    whatsapp_token: str = Field(default="")
    whatsapp_phone_number_id: str = Field(default="")
    whatsapp_group_id: str = Field(default="")

    # GitHub archive repo
    github_archive_repo_url: str = Field(default="git@github.com:PythonToGo/ai-newsletter.git")
    github_archive_branch: str = Field(default="main")
    github_archive_token: str = Field(
        default="",
        validation_alias=AliasChoices("ARCHIVE_GITHUB_TOKEN", "GITHUB_ARCHIVE_TOKEN"),
    )

    # Email (Gmail SMTP)
    gmail_address: str = Field(default="")
    gmail_app_password: str = Field(default="")
    email_recipients: str = Field(default="", description="Comma-separated list of recipient addresses")

    # behaviour settings
    content_topic: str = Field(default="AI/ML")
    pipeline_mode: str = Field(
        default="news",
        description="Content pipeline mode: 'news' | 'new_paper' | 'classic_paper'",
    )
    items_per_report: int = Field(default=6, ge=1, le=20)
    items_per_weekly: int = Field(default=12, ge=1, le=30)
    items_per_new_paper: int = Field(default=5, ge=1, le=10, description="Top papers to analyze per new_paper run")
    items_per_classic: int = Field(default=1, ge=1, le=3, description="Classic papers per run (usually 1)")
    quality_min_score: float = Field(default=0.8, ge=0.0, le=1.0)
    dedup_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    default_language: str = Field(default="ko")
    analysis_mode: str = Field(
        default="light",
        description="LLM analysis profile: 'light' for lower token usage, 'detail' for richer output",
    )
    anthropic_main_model: str = Field(default="claude-sonnet-4-6")
    anthropic_quality_model: str = Field(default="claude-haiku-4-5-20251001")
    enable_multilingual: bool = Field(default=False)
    dry_run: bool = Field(default=False)
    mock_claude: bool = Field(default=False, description="Run the full pipeline with mock responses instead of calling the API")
    log_level: str = Field(default="INFO")

    @field_validator("pipeline_mode")
    @classmethod
    def validate_pipeline_mode(cls, v: str) -> str:
        valid = {"news", "new_paper", "classic_paper"}
        if v not in valid:
            raise ValueError(f"pipeline_mode must be one of {valid}, got '{v}'")
        return v

    @field_validator("default_language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        if v not in ("ko", "en"):
            raise ValueError(f"default_language must be 'ko' or 'en', got '{v}'")
        return v

    @field_validator("analysis_mode")
    @classmethod
    def validate_analysis_mode(cls, v: str) -> str:
        normalized = v.lower()
        if normalized not in ("light", "detail"):
            raise ValueError(
                f"analysis_mode must be 'light' or 'detail', got '{v}'"
            )
        return normalized

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}, got '{v}'")
        return upper

    # convenience properties
    @property
    def twitter_configured(self) -> bool:
        return all([
            self.twitter_bearer_token,
            self.twitter_api_key,
            self.twitter_api_secret,
            self.twitter_access_token,
            self.twitter_access_secret,
        ])

    @property
    def threads_configured(self) -> bool:
        return all([self.threads_access_token, self.threads_user_id])

    @property
    def substack_configured(self) -> bool:
        return all([self.substack_email, self.substack_password, self.substack_publication_url])

    @property
    def whatsapp_configured(self) -> bool:
        return all([self.whatsapp_token, self.whatsapp_phone_number_id, self.whatsapp_group_id])

    @property
    def email_configured(self) -> bool:
        return bool(self.gmail_address and self.gmail_app_password and self.email_recipients)

    @property
    def effective_items_per_report(self) -> int:
        """Return the correct item count for the current pipeline_mode."""
        if self.pipeline_mode == "classic_paper":
            return self.items_per_classic
        if self.pipeline_mode == "new_paper":
            return self.items_per_new_paper
        return self.items_per_report


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance. Clear lru_cache and re-call in tests."""
    return Settings()
