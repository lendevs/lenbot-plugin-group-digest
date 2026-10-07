"""Independent hourly notes, reused only for complete matching windows."""

from dataclasses import asdict
import hashlib
import json
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError

from . import daily

HOUR = 3600


class TopicNote(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str
    summary: str
    people: list[str]
    evidence: list[int]


class QuoteNote(BaseModel):
    model_config = ConfigDict(strict=True)
    index: int
    why: str = ""


class Note(BaseModel):
    model_config = ConfigDict(strict=True)
    topics: list[TopicNote]
    quotes: list[QuoteNote]


async def extract(ctx, scene: str, lines: list[daily.Line], *, role: str, budget: int) -> list[dict]:
    zone = ZoneInfo(ctx.timezone(scene))
    system = (daily.PROMPTS / "daily_chunk.md").read_text(encoding="utf-8")
    by_index = {line.index: line.message_id for line in lines}
    result = []
    for part in daily.batches(lines, zone, budget):
        raw = await ctx.generate(scene, json.dumps({"群聊记录": part}, ensure_ascii=False), role=role, system=system)
        try:
            note = Note.model_validate(daily.parse(raw))
        except ValidationError as error:
            raise ValueError(f"增量整理格式错误：{error}；原文：{raw[:300]}") from error
        result.append({
            "topics": [{"title": topic.title, "summary": topic.summary, "people": topic.people,
                        "messages": [by_index[index] for index in topic.evidence if index in by_index]}
                       for topic in note.topics],
            "quotes": [{"message": by_index[quote.index], "why": quote.why}
                       for quote in note.quotes if quote.index in by_index],
        })
    return result


def remap(notes: list[dict], lines: list[daily.Line]) -> list[dict]:
    """Stored message IDs become this report's citation numbers."""
    indices = {line.message_id: line.index for line in lines}
    quotes = {line.message_id: f"{line.name}：{line.text}" for line in lines}
    return [{
        "topics": [{"title": topic["title"], "summary": topic["summary"], "people": topic["people"],
                    "evidence": [indices[message] for message in topic["messages"] if message in indices]}
                   for topic in note["topics"]],
        "quotes": [{"index": indices[quote["message"]], "why": quote["why"],
                    "原话": quotes[quote["message"]]}
                   for quote in note["quotes"] if quote["message"] in indices],
    } for note in notes]


class Cache:
    def __init__(self, ctx):
        self.ctx = ctx

    def key(self, scene: str) -> str:
        return f"hourly-notes:{scene}"

    async def load(self, scene: str) -> dict:
        return await self.ctx.get_kv(self.key(scene), {})

    async def save(self, scene: str, records: dict) -> None:
        oldest = self.ctx.now() - self.ctx.config["cache_days"] * 86400
        await self.ctx.set_kv(self.key(scene), {key: item for key, item in records.items()
                                              if int(key) + HOUR > oldest})

    async def bucket(self, scene: str, start: int, lines: list[daily.Line], records: dict) -> list[dict]:
        payload = {"messages": [asdict(line) | {"index": 0} for line in lines],
                   "role": self.ctx.config["model_role"], "budget": self.ctx.config["batch_chars"],
                   "timezone": self.ctx.timezone(scene)}
        fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        saved = records.get(str(start))
        if saved is not None and saved["fingerprint"] == fingerprint:
            return saved["notes"]
        notes = await extract(self.ctx, scene, lines, role=self.ctx.config["model_role"],
                              budget=self.ctx.config["batch_chars"])
        records[str(start)] = {"fingerprint": fingerprint, "notes": notes}
        await self.save(scene, records)
        return notes

    async def prepare(self, scene: str) -> None:
        """Build missing completed hours; this never sends a report."""
        before = int(self.ctx.now() // HOUR) * HOUR
        after = before - self.ctx.config["cache_days"] * 86400
        records = await self.load(scene)
        for start in range(after, before, HOUR):
            lines = daily.read_window(self.ctx, scene, start, start + HOUR)
            if lines:
                await self.bucket(scene, start, lines, records)
        await self.save(scene, records)

    async def report_notes(self, scene: str, lines: list[daily.Line], after: float, before: float) -> list[dict]:
        records = await self.load(scene)
        grouped: dict[int, list[daily.Line]] = {}
        for line in lines:
            grouped.setdefault(int(line.time // HOUR) * HOUR, []).append(line)
        result = []
        for start, items in grouped.items():
            if after <= start and start + HOUR <= before:
                notes = await self.bucket(scene, start, items, records)
            else:
                notes = await extract(self.ctx, scene, items, role=self.ctx.config["model_role"],
                                      budget=self.ctx.config["batch_chars"])
            result.extend(remap(notes, lines))
        await self.save(scene, records)
        return result
