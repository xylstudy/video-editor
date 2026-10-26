import json
from urllib.parse import urlparse

from sqlmodel import Session, select

from database import engine
from db_models import ApiKey, ModelConfiguration, Provider
from secret_store import decrypt_secret


def _default_config(session: Session, user_id: int, purpose: str) -> ModelConfiguration | None:
    default_attr = (
        ModelConfiguration.is_default_vision
        if purpose == "vision"
        else ModelConfiguration.is_default_text
    )
    statement = select(ModelConfiguration).where(
        ModelConfiguration.user_id == user_id,
        ModelConfiguration.enabled == True,  # noqa: E712 - SQLModel expression
        default_attr == True,  # noqa: E712 - SQLModel expression
    )
    if purpose == "vision":
        statement = statement.where(ModelConfiguration.supports_vision == True)  # noqa: E712
    return session.exec(statement).first()


def get_user_model_env(user_id: int) -> dict[str, str]:
    """Build per-user worker environment without mutating the process or `.env`.

    New model configurations take precedence. Legacy API-key records remain a
    compatibility fallback for users who configured the old settings page.
    """
    env: dict[str, str] = {}
    with Session(engine) as session:
        vision = _default_config(session, user_id, "vision")
        text = _default_config(session, user_id, "text")
        prices = []
        for config in session.exec(select(ModelConfiguration).where(ModelConfiguration.user_id == user_id)).all():
            if config.input_price_per_million is None or config.output_price_per_million is None:
                continue
            prices.append({"model": config.model_id, "host": urlparse(config.endpoint_url).hostname,
                           "input": config.input_price_per_million, "output": config.output_price_per_million,
                           "cached_input": config.cached_input_price_per_million,
                           "currency": config.price_currency, "source": "configured", "config_id": config.id})
        env["VIDEOCLAW_MODEL_PRICES"] = json.dumps(prices)

        if vision:
            env.update(
                VISION_API_KEY=decrypt_secret(vision.api_key),
                VISION_BASE_URL=vision.endpoint_url,
                VISION_MODEL_ID=vision.model_id,
                VISION_CONFIGURED="1",
            )
        if text:
            env.update(
                TEXT_API_KEY=decrypt_secret(text.api_key),
                TEXT_BASE_URL=text.endpoint_url,
                TEXT_MODEL_ID=text.model_id,
                TEXT_CONFIGURED="1",
            )

        legacy = session.exec(select(ApiKey).where(ApiKey.user_id == user_id)).all()
        by_provider = {item.provider: item.key_value for item in legacy}
        if not vision and by_provider.get(Provider.ZHIPU):
            env["VISION_API_KEY"] = by_provider[Provider.ZHIPU]
            env["VISION_CONFIGURED"] = "1"
        if not text and by_provider.get(Provider.DEEPSEEK):
            env["TEXT_API_KEY"] = by_provider[Provider.DEEPSEEK]
            env["TEXT_CONFIGURED"] = "1"

    return {key: value for key, value in env.items() if value is not None}
