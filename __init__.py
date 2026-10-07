"""Group summaries: a short one on request, and a daily card built in batches from a time window."""

from pathlib import Path
import asyncio
from datetime import datetime
import json
import re
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import Field

from len_bot.next.plugin import Invocation, Plugin, command, tool

from . import card, daily, incremental, window

MIN_MESSAGES = 5


def recent(ctx: Invocation) -> str:
    return json.dumps([
        {"sender": message.sender.uid, "nickname": message.sender.card or message.sender.nickname,
         "time": message.time, "is_self": message.is_self, "send_status": message.send_status,
         "text": "".join(segment.data["text"] if segment.type == "text" else f"[{segment.type}]"
                         for segment in message.segments)}
        for message in ctx.recent_messages(ctx.config["message_limit"])
        if ctx.message is None or message.id != ctx.message.id
    ], ensure_ascii=False)


class GroupDigest(Plugin):
    async def start(self) -> None:
        self.running: set[str] = set()
        self.locks = {scene: asyncio.Lock() for scene in self.ctx.enabled_scenes}
        self.cache = incremental.Cache(self.ctx)
        match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(self.ctx.config["daily_time"]))
        if match is None:
            raise ValueError(f"每天几点发要写成 22:00 这样的 24 小时制时间：{self.ctx.config['daily_time']!r}")
        hour, minute = int(match[1]), int(match[2])
        for scene in self.ctx.config["daily_scenes"]:
            if scene in self.ctx.enabled_scenes:
                self.ctx.cron("daily-summary", f"{minute} {hour} * * *", self.scheduled,
                              scene=scene, timezone=self.ctx.timezone(scene))
        for scene in self.ctx.config["incremental_scenes"]:
            if scene in self.ctx.enabled_scenes:
                self.ctx.cron("hourly-notes", "0 * * * *", self.prepare,
                              scene=scene, timezone=self.ctx.timezone(scene))

    async def prepare(self, ctx: Invocation) -> None:
        async with self.locks[ctx.scene]:
            await self.cache.prepare(ctx.scene)

    async def scheduled(self, ctx: Invocation) -> None:
        if ctx.scene not in self.running:
            after, before = window.resolve(self.ctx.now(), ctx.timezone())
            await self.produce(ctx.scene, after, before, requested=False)

    def begin(self, scene: str, after: float, before: float) -> str:
        """Start in the background; the caller (a chat turn or a command) does not wait for the model."""
        if scene in self.running:
            return "这个群的总结已经在生成了，完成后会发出来。"
        self.running.add(scene)
        self.ctx.start_task(f"群聊总结 {scene}", self.produce(scene, after, before, requested=True))
        zone = ZoneInfo(self.ctx.timezone(scene))
        period = f"{datetime.fromtimestamp(after, zone):%m月%d日 %H:%M} 至 {datetime.fromtimestamp(before, zone):%m月%d日 %H:%M}"
        return f"开始生成群聊总结（{period}），生成好后卡片会直接发到群里。"

    async def produce(self, scene: str, after: float, before: float, *, requested: bool) -> None:
        self.running.add(scene)
        try:
            async with self.locks[scene]:
                lines = daily.read_window(self.ctx, scene, after, before)
                if len(lines) < MIN_MESSAGES:
                    if requested:
                        await self.ctx.send(scene, f"这段时间群里只有 {len(lines)} 条消息，这次就不做总结了。")
                    return
                notes = (await self.cache.report_notes(scene, lines, after, before)
                         if scene in self.ctx.config["incremental_scenes"] else None)
                summary = await daily.summarize(self.ctx, scene, lines, after, before,
                                                role=self.ctx.config["model_role"], budget=self.ctx.config["batch_chars"],
                                                notes=notes)
            image = card.render(summary, card.find_font(self.ctx.config["font_path"]),
                                "群聊总结")
            await self.ctx.send_image(scene, image, summary.description())
        except Exception as error:
            self.ctx.report_error(f"群聊总结 {scene}", error)
            if requested:
                await self.ctx.send(scene, f"群聊总结没生成出来：{error}")
        finally:
            self.running.discard(scene)

    @command("群总结", "对本群最近消息做一次显式模型生成，可补充总结要求")
    async def summarize(self, ctx: Invocation, args: str) -> None:
        system = (Path(__file__).with_name("prompts") / "group_summary.md").read_text(encoding="utf-8")
        result = await ctx.generate(json.dumps({"要求": args or "概括最近的话题与未完事项", "群聊记录": recent(ctx)},
                                               ensure_ascii=False),
                                    role=ctx.config["model_role"], system=system)
        await ctx.reply(result)

    @command("群日报", "生成本群过去 24 小时的总结卡片；可跟小时数，例如 /群日报 6")
    async def report(self, ctx: Invocation, args: str) -> None:
        text = args.strip()
        if text and not (text.isdigit() and 1 <= int(text) <= 72):
            await ctx.reply("用法：/群日报 或 /群日报 小时数（1–72）")
            return
        after, before = window.resolve(ctx.now(), ctx.timezone(), hours=int(text) if text else 24)
        await ctx.reply(self.begin(ctx.scene, after, before))

    @tool("group_summary_card", "按时间范围生成本群日报（群聊总结卡片），生成后发回当前群。"
                                "有人要回顾今天、昨天或最近群里聊了什么时使用。过去 12 小时用 hours=12；"
                                "今天下午、指定日期或昨天整天用 start_at、end_at，按本群时区给出 ISO 日期时间。"
                                "过去 24 小时用 hours=24。跨度最多 72 小时，小时数与起止时间不能混用。"
                                "在后台生成，调用后立即返回；卡片做好后会自动发出，不需要再转述内容。")
    async def summary_tool(self, ctx: Invocation,
                           hours: Annotated[int | None, Field(ge=1, le=72, description="向前回溯的小时数；省略全部参数时为 24 小时")] = None,
                           *, start_at: Annotated[str | None, Field(description="范围起点，ISO 日期时间；无时区时使用本群时区")] = None,
                           end_at: Annotated[str | None, Field(description="范围终点（不含），ISO 日期时间，不能晚于当前时间")] = None) -> str:
        after, before = window.resolve(ctx.now(), ctx.timezone(), hours=hours, start_at=start_at, end_at=end_at)
        return self.begin(ctx.scene, after, before)

    @command("群工作", "基于最近群聊委派长工作或文件交付；参数是实际交付要求")
    async def work(self, ctx: Invocation, args: str) -> None:
        if not args:
            await ctx.reply("用法：/群工作 交付要求，例如把刚才讨论的活动安排做成 CSV 文件。")
            return
        task = await ctx.delegate(args, args, context=recent(ctx))
        await ctx.reply(f"已接下这项工作（任务 {task['id']}），完成后再告诉你。")
