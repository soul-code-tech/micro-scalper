import aiohttp, datetime as dt, pytz
from typing import List

HIGH_IMPACT_EVENTS = (
    "FOMC", "NFP", "CPI", "GDP", "PCE", "ECB", "BOE", "Fed Chair", "Powell"
)

async def is_news_time(minutes_before_after: int = 5) -> bool:
    return False
    now = dt.datetime.utcnow().replace(tzinfo=pytz.UTC)
    url = "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            r.raise_for_status()
            events = await r.json()
    for ev in events:
        if ev.get("impact") != "High":
            continue
        if not any(k in ev.get("title", "") for k in HIGH_IMPACT_EVENTS):
            continue
        event_time = dt.datetime.fromisoformat(ev["date"]).replace(tzinfo=pytz.UTC)
        delta = abs((now - event_time).total_seconds()) / 60
        if delta <= minutes_before_after:
            return True
    return False
