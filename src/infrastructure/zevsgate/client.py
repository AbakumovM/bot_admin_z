import logging
from typing import Any, NewType

import httpx

from src.config import Config

logger = logging.getLogger(__name__)

ZevsgateClient = NewType("ZevsgateClient", httpx.AsyncClient)


def create_zevsgate_client(config: Config) -> ZevsgateClient:
    client = httpx.AsyncClient(
        base_url=config.zevsgate_base_url.rstrip("/"),
        headers={"X-Internal-Api-Key": config.zevsgate_internal_api_key},
        timeout=15,
    )
    return ZevsgateClient(client)


async def check_no_active_payment(client: ZevsgateClient, remnawave_id: int) -> bool | None:
    """Критерий: нет активной оплаченной подписки прямо сейчас.

    Пользователь адресуется по числовому id панели (Remnawave 3.x — uuid у
    пользователя больше нет), а не по telegram_id — у веб-пользователей
    ZEVSgate (регистрация по email) telegram_id нет.

    Возвращает True, если подтверждено отсутствие, False, если у
    пользователя есть активная подписка, None, если проверку не удалось
    выполнить (сетевая ошибка, неожиданный статус) — вызывающий код должен
    трактовать None как "неизвестно", никогда как False, чтобы падение
    бэкенда ZEVSgate не подавляло критерий молча.
    """
    try:
        response = await client.get(
            f"/api/internal/users/by-remnawave-id/{remnawave_id}/payment-status"
        )
    except httpx.HTTPError as e:
        logger.warning("Antifraud: payment-status check failed for %s: %s", remnawave_id, e)
        return None
    if response.status_code != 200:
        logger.warning(
            "Antifraud: payment-status check for %s returned %d",
            remnawave_id,
            response.status_code,
        )
        return None
    try:
        payload: dict[str, Any] = response.json()
        has_active_subscription = payload["has_active_subscription"]
    except (ValueError, KeyError) as e:
        logger.warning(
            "Antifraud: payment-status response for %s is malformed: %s", remnawave_id, e
        )
        return None
    return not bool(has_active_subscription)


async def block_user(client: ZevsgateClient, remnawave_id: int, reason: str) -> bool:
    """Блокировка «везде»: бэкенд ZEVSgate отключает пользователя в панели и
    ставит users.is_blocked (повторная оплата невозможна). Идемпотентно —
    повторный вызов для уже заблокированного тоже отвечает 200.
    """
    try:
        response = await client.post(
            f"/api/internal/users/by-remnawave-id/{remnawave_id}/block", json={"reason": reason}
        )
    except httpx.HTTPError as e:
        logger.error("Antifraud: block request failed for %s: %s", remnawave_id, e)
        return False
    if response.status_code != 200:
        logger.error(
            "Antifraud: block request for %s returned %d", remnawave_id, response.status_code
        )
        return False
    return True
