from datetime import datetime
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from db_models import (
    ApiFormat,
    EndpointMode,
    ModelConfiguration,
    ModelConfigurationCreate,
    ModelConfigurationRead,
    ModelConfigurationUpdate,
    ModelConnectionTest,
    ModelPurpose,
    User,
)
from secret_store import decrypt_secret, encrypt_secret

router = APIRouter(prefix="/api/models", tags=["models"])


def build_chat_url(endpoint_url: str, endpoint_mode: EndpointMode) -> str:
    endpoint = endpoint_url.strip().rstrip("/")
    if endpoint_mode == EndpointMode.FULL_URL:
        return endpoint
    return f"{endpoint}/chat/completions"


def _validate_endpoint(endpoint_url: str):
    parsed = urlparse(endpoint_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请求地址必须是有效的 http:// 或 https:// URL",
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="请求地址中不能包含用户名或密码",
        )


def _clean_text(value: str, label: str, max_length: int = 200) -> str:
    value = value.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label}不能为空",
        )
    if len(value) > max_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label}过长",
        )
    return value


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return "未设置"
    if len(api_key) <= 8:
        return "••••••••"
    return f"{api_key[:3]}••••{api_key[-4:]}"


def _validate_price_pair(input_price, output_price):
    if (input_price is None) != (output_price is None):
        raise HTTPException(status_code=422, detail="费用估算需要同时填写输入价格和输出价格，或同时留空")


def _to_read(config: ModelConfiguration) -> ModelConfigurationRead:
    raw_api_key = decrypt_secret(config.api_key)
    return ModelConfigurationRead(
        id=config.id,
        provider=config.provider,
        display_name=config.display_name,
        model_id=config.model_id,
        endpoint_url=config.endpoint_url,
        endpoint_mode=config.endpoint_mode,
        api_format=config.api_format,
        has_api_key=bool(raw_api_key),
        masked_api_key=_mask_api_key(raw_api_key),
        supports_vision=config.supports_vision,
        enabled=config.enabled,
        is_default_vision=config.is_default_vision,
        is_default_text=config.is_default_text,
        input_price_per_million=config.input_price_per_million,
        output_price_per_million=config.output_price_per_million,
        cached_input_price_per_million=config.cached_input_price_per_million,
        price_currency=config.price_currency,
        last_test_status=config.last_test_status,
        last_test_message=config.last_test_message,
        last_tested_at=config.last_tested_at,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _user_configs(session: Session, user_id: int) -> list[ModelConfiguration]:
    return list(
        session.exec(
            select(ModelConfiguration)
            .where(ModelConfiguration.user_id == user_id)
            .order_by(ModelConfiguration.created_at)
        ).all()
    )


def _clear_default(session: Session, user_id: int, purpose: ModelPurpose):
    attr = "is_default_vision" if purpose == ModelPurpose.VISION else "is_default_text"
    for item in _user_configs(session, user_id):
        if getattr(item, attr):
            setattr(item, attr, False)
            session.add(item)


def _promote_defaults(session: Session, user_id: int):
    configs = _user_configs(session, user_id)
    enabled = [item for item in configs if item.enabled]
    if enabled and not any(item.is_default_text for item in enabled):
        enabled[0].is_default_text = True
        session.add(enabled[0])
    vision = [item for item in enabled if item.supports_vision]
    if vision and not any(item.is_default_vision for item in vision):
        vision[0].is_default_vision = True
        session.add(vision[0])


def _owned_config(session: Session, user_id: int, config_id: int) -> ModelConfiguration:
    config = session.get(ModelConfiguration, config_id)
    if not config or config.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="模型配置不存在")
    return config


@router.get("", response_model=list[ModelConfigurationRead])
def list_models(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return [_to_read(item) for item in _user_configs(session, current_user.id)]


@router.post("", response_model=ModelConfigurationRead, status_code=status.HTTP_201_CREATED)
def create_model(
    model_in: ModelConfigurationCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _validate_endpoint(model_in.endpoint_url)
    _validate_price_pair(model_in.input_price_per_million, model_in.output_price_per_million)
    if model_in.use_for_vision and not model_in.supports_vision:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="视觉分析默认模型必须开启图片输入能力",
        )

    config = ModelConfiguration(
        user_id=current_user.id,
        provider=_clean_text(model_in.provider, "服务商", 50).lower(),
        display_name=_clean_text(model_in.display_name, "展示名称"),
        model_id=_clean_text(model_in.model_id, "模型 ID"),
        endpoint_url=model_in.endpoint_url.strip().rstrip("/"),
        endpoint_mode=model_in.endpoint_mode,
        api_format=model_in.api_format,
        api_key=encrypt_secret(model_in.api_key),
        supports_vision=model_in.supports_vision,
        enabled=model_in.enabled,
        input_price_per_million=model_in.input_price_per_million,
        output_price_per_million=model_in.output_price_per_million,
        cached_input_price_per_million=model_in.cached_input_price_per_million,
        price_currency=model_in.price_currency,
    )
    session.add(config)
    session.flush()

    existing = _user_configs(session, current_user.id)
    config.is_default_text = config.enabled and (
        model_in.use_for_text
        or not any(
            item.enabled and item.is_default_text
            for item in existing
            if item.id != config.id
        )
    )
    config.is_default_vision = config.enabled and config.supports_vision and (
        model_in.use_for_vision
        or not any(
            item.enabled and item.supports_vision and item.is_default_vision
            for item in existing if item.id != config.id
        )
    )
    if config.is_default_text:
        _clear_default(session, current_user.id, ModelPurpose.TEXT)
        config.is_default_text = True
    if config.is_default_vision:
        _clear_default(session, current_user.id, ModelPurpose.VISION)
        config.is_default_vision = True
    session.add(config)
    session.commit()
    session.refresh(config)
    return _to_read(config)


@router.put("/{config_id}", response_model=ModelConfigurationRead)
def update_model(
    config_id: int,
    model_in: ModelConfigurationUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    config = _owned_config(session, current_user.id, config_id)
    changes = model_in.model_dump(exclude_unset=True)
    _validate_price_pair(changes.get("input_price_per_million", config.input_price_per_million),
                         changes.get("output_price_per_million", config.output_price_per_million))
    if "endpoint_url" in changes:
        _validate_endpoint(changes["endpoint_url"])
        changes["endpoint_url"] = changes["endpoint_url"].strip().rstrip("/")
    for key, label, max_length in (
        ("provider", "服务商", 50),
        ("display_name", "展示名称", 200),
        ("model_id", "模型 ID", 200),
    ):
        if key in changes and changes[key] is not None:
            changes[key] = _clean_text(changes[key], label, max_length)
    if "provider" in changes:
        changes["provider"] = changes["provider"].lower()
    if not changes.get("api_key"):
        changes.pop("api_key", None)
    elif "api_key" in changes:
        changes["api_key"] = encrypt_secret(changes["api_key"])
    for key, value in changes.items():
        setattr(config, key, value)
    if not config.enabled:
        config.is_default_text = False
        config.is_default_vision = False
    if not config.supports_vision:
        config.is_default_vision = False
    config.updated_at = datetime.utcnow()
    session.add(config)
    session.flush()
    _promote_defaults(session, current_user.id)
    session.commit()
    session.refresh(config)
    return _to_read(config)


@router.post("/{config_id}/default/{purpose}", response_model=ModelConfigurationRead)
def set_default_model(
    config_id: int,
    purpose: ModelPurpose,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    config = _owned_config(session, current_user.id, config_id)
    if not config.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先启用该模型")
    if purpose == ModelPurpose.VISION and not config.supports_vision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该模型未声明图片输入能力，不能用于视觉分析",
        )
    _clear_default(session, current_user.id, purpose)
    if purpose == ModelPurpose.VISION:
        config.is_default_vision = True
    else:
        config.is_default_text = True
    config.updated_at = datetime.utcnow()
    session.add(config)
    session.commit()
    session.refresh(config)
    return _to_read(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(
    config_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    config = _owned_config(session, current_user.id, config_id)
    session.delete(config)
    session.flush()
    _promote_defaults(session, current_user.id)
    session.commit()
    return None


@router.post("/test")
async def test_model_connection(
    test_in: ModelConnectionTest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _validate_endpoint(test_in.endpoint_url)
    model_id = _clean_text(test_in.model_id, "模型 ID")
    api_key = (test_in.api_key or "").strip()
    stored = None
    if test_in.model_config_id is not None:
        stored = _owned_config(session, current_user.id, test_in.model_config_id)
        if not api_key:
            api_key = decrypt_secret(stored.api_key)

    chat_url = build_chat_url(test_in.endpoint_url, test_in.endpoint_mode)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    tested_at = datetime.utcnow()
    try:
        # Local development environments may export a stale HTTP(S)_PROXY
        # (for example 127.0.0.1:9). Model endpoints must not silently route
        # through an unavailable proxy and look like a bad API-key error.
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(chat_url, headers=headers, json=body)
        if response.is_success:
            result = {"success": True, "message": "连接成功，模型已返回响应"}
        else:
            message = f"连接失败（HTTP {response.status_code}）"
            try:
                detail = response.json().get("error", {}).get("message")
                if detail:
                    message = f"{message}：{str(detail)[:240]}"
            except (ValueError, AttributeError):
                pass
            result = {"success": False, "message": message}
    except httpx.TimeoutException:
        result = {"success": False, "message": "连接超时，请检查请求地址或网络"}
    except httpx.RequestError as exc:
        result = {"success": False, "message": f"无法连接模型服务：{str(exc)[:240]}"}

    if stored:
        stored.last_test_status = "success" if result["success"] else "failed"
        stored.last_test_message = result["message"]
        stored.last_tested_at = tested_at
        stored.updated_at = tested_at
        session.add(stored)
        session.commit()
    return {**result, "tested_at": tested_at.isoformat()}
