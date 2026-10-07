"""Explicit report windows in the invoking scene's timezone."""

from datetime import datetime
from zoneinfo import ZoneInfo


def resolve(now: float, timezone: str, *, hours: int | None = None,
            start_at: str | None = None, end_at: str | None = None) -> tuple[float, float]:
    if start_at is None and end_at is None:
        return now - (24 if hours is None else hours) * 3600, now
    if hours is not None or start_at is None or end_at is None:
        raise ValueError("使用 hours 或同时填写 start_at、end_at，不能混用。")
    zone = ZoneInfo(timezone)
    def timestamp(value: str) -> float:
        moment = datetime.fromisoformat(value)
        return (moment.replace(tzinfo=zone) if moment.tzinfo is None else moment).timestamp()
    after, before = timestamp(start_at), timestamp(end_at)
    if not after < before <= now or before - after > 72 * 3600:
        raise ValueError("时间范围须为过去的时间，开始早于结束，跨度不超过 72 小时。")
    return after, before
