from pydantic_settings import BaseSettings
from pydantic import ConfigDict
import logging

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    SPORTS_API_BASE_URL: str
    SPORTS_USER_TOKEN: str
    SPORTS_SECRET_TOKEN: str
    
    # MQTT WebSocket settings for live scores (uses same credentials as HTTP API)
    SPORTS_MQTT_HOST: str = "mq.thesports.com"
    SPORTS_MQTT_PORT: int = 443

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"  # Ignore extra fields from .env that are not defined in the model
    )

settings = Settings()

# Log configuration on startup for debugging (only log first time)
if not hasattr(Settings, '_logged'):
    logger.info(f"✅ Sports API Config loaded:")
    logger.info(f"   Base URL: {settings.SPORTS_API_BASE_URL}")
    logger.info(f"   User Token: {settings.SPORTS_USER_TOKEN}")
    logger.info(f"   Secret Token: {settings.SPORTS_SECRET_TOKEN[:10]}... (length: {len(settings.SPORTS_SECRET_TOKEN)})")
    print(f"✅ [Config] Sports API Base URL: {settings.SPORTS_API_BASE_URL}")
    print(f"✅ [Config] Sports API User Token: {settings.SPORTS_USER_TOKEN}")
    print(f"✅ [Config] Sports API Secret Token: {settings.SPORTS_SECRET_TOKEN[:10]}... (length: {len(settings.SPORTS_SECRET_TOKEN)})")
    Settings._logged = True
