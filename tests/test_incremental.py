"""Report windows and persisted notes through real tools and a local model protocol."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
from pathlib import Path
import re
import shutil

import pytest

from len_bot.plugin import ChatMessage, Segment, Sender, Invocation
from len_bot.plugin_testing import PluginTest

SCENE = 'onebot:group:80001'
OTHER = 'onebot:group:80002'
NOW = datetime.fromisoformat('2026-10-06T18:00:00+08:00').timestamp()


@pytest.fixture
def package(tmp_path):
    target = tmp_path / 'digest_copy'
    shutil.copytree(Path(__file__).parents[1], target, ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
    manifest = target / 'plugin.toml'
    manifest.write_text(manifest.read_text().replace('name = "group_digest"', 'name = "digest_copy"'), encoding='utf-8')
    return target


@asynccontextmanager
async def model_source(gate=None):
    calls = []
    async def respond(reader, writer):
        headers = await reader.readuntil(b'\r\n\r\n')
        length = int(re.search(rb'content-length:\s*(\d+)', headers, re.I)[1])
        request = json.loads(await reader.readexactly(length))
        system = request['messages'][0]['content']
        material = json.loads(request['messages'][-1]['content'])
        kind = 'final' if 'headline' in system else 'chunk'
        calls.append((kind, material))
        if kind == 'chunk':
            transcript = material['群聊记录']
            indices = [int(value) for value in re.findall(r'^\[(\d+)\]', transcript, re.M)]
            result = {'topics': [{'title': '安排', 'summary': transcript, 'people': ['小满'], 'evidence': indices}],
                      'quotes': [{'index': indices[0], 'why': '原话'}]}
        else:
            notes = material.get('各段整理', [])
            quotes = [quote for note in notes for quote in note['quotes']]
            result = {'headline': '选定时间里的安排', 'topics': [{'title': '安排', 'summary': '讨论活动', 'people': ['小满']}],
                      'quotes': [{'index': quote['index'], 'comment': '原话'} for quote in quotes]}
        if gate is not None:
            await gate.wait()
        body = json.dumps({'id': 'synthetic', 'object': 'chat.completion', 'created': 1790000000,
                           'model': 'local', 'choices': [{'index': 0, 'message': {'role': 'assistant',
                           'content': json.dumps(result, ensure_ascii=False)}, 'finish_reason': 'stop'}],
                           'usage': {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}}).encode()
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)).encode()
                     + b'\r\nConnection: close\r\n\r\n' + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()
    server = await asyncio.start_server(respond, '127.0.0.1', 0)
    async with server:
        yield f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1', calls


def models(url):
    return {'providers': {'local': {'api': 'openai-chat', 'base_url': url, 'api_key': 'synthetic'}},
            'roles': {'mind': {'provider': 'local', 'model': 'local', 'context_window_tokens': 65536}}}


def message(bot, hour: int, minute: int, text: str, *, scene=SCENE):
    number = str(len(bot.host.messages) + 1)
    timestamp = datetime.fromisoformat(f'2026-10-06T{hour:02}:{minute:02}:00+08:00').timestamp()
    item = ChatMessage(number, 'onebot', 'onebot:90001', scene, number, Sender('onebot:70001', '小满', None, None),
                       timestamp, [Segment('text', {'text': text})], None, False, False, 'received')
    bot.host.messages.append(item)
    return item


async def finish(bot):
    tasks = [task for task in bot.host.tasks if '群聊总结 ' in task.get_name()]
    await asyncio.gather(*tasks)
    assert not bot.host.plugins['digest_copy'].errors


def chunk_calls(calls):
    return [material for kind, material in calls if kind == 'chunk']


@pytest.mark.asyncio
async def test_hourly_notes_survive_reload_and_only_new_hour_is_analyzed(package):
    async with model_source() as (url, calls), PluginTest(package, config={'incremental_scenes': [SCENE]}, scenes=[SCENE, OTHER], now=lambda: NOW, models=models(url)) as bot:
        for index in range(6):
            message(bot, 13, index * 5, f'午后安排 {index}')
        message(bot, 12, 5, '另一个群', scene=OTHER)
        record = bot.host.plugins['digest_copy']
        await record.instance.prepare(Invocation(record.context, SCENE))
        assert len(chunk_calls(calls)) == 1 and not bot.deliveries
        await bot.host.reload('digest_copy', bot.host.config)
        record = bot.host.plugins['digest_copy']
        await record.instance.prepare(Invocation(record.context, SCENE))
        assert len(chunk_calls(calls)) == 1
        for index in range(6):
            message(bot, 14, index * 5, f'新一小时 {index}')
        await record.instance.prepare(Invocation(record.context, SCENE))
        assert len(chunk_calls(calls)) == 2
        result = await bot.tool('group_summary_card', {'start_at': '2026-10-06T13:00:00', 'end_at': '2026-10-06T15:00:00'})
        assert json.loads(result)['status'] == 'started'
        assert '13:00' in result and '15:00' in result
        await finish(bot)
        assert len(chunk_calls(calls)) == 2 and calls[-1][0] == 'final'
        assert calls[-1][1]['统计']['消息数'] == 12
        assert '另一个群' not in json.dumps(calls[-1][1], ensure_ascii=False)
        assert bot.deliveries[-1].scene == SCENE


@pytest.mark.asyncio
async def test_partial_hour_reads_only_requested_messages_and_recall_invalidates_notes(package):
    async with model_source() as (url, calls), PluginTest(package, config={'incremental_scenes': [SCENE]}, now=lambda: NOW, models=models(url)) as bot:
        outside = message(bot, 13, 5, '范围外秘密')
        inside = [message(bot, 13, 30 + index * 4, f'范围内 {index}') for index in range(6)]
        record = bot.host.plugins['digest_copy']
        await record.instance.prepare(Invocation(record.context, SCENE))
        assert len(chunk_calls(calls)) == 1
        await bot.tool('group_summary_card', {'start_at': '2026-10-06T13:30:00+08:00', 'end_at': '2026-10-06T14:00:00+08:00'})
        await finish(bot)
        assert len(chunk_calls(calls)) == 2
        assert '范围外秘密' not in json.dumps(calls[-2:], ensure_ascii=False)
        assert calls[-1][1]['统计']['消息数'] == 6
        inside[0].recalled = True
        await record.instance.prepare(Invocation(record.context, SCENE))
        assert len(chunk_calls(calls)) == 3
        assert '范围内 0' not in chunk_calls(calls)[-1]['群聊记录']


@pytest.mark.asyncio
async def test_disabled_incremental_and_tool_time_validation(package):
    async with PluginTest(package, scenes=[SCENE, OTHER], now=lambda: NOW) as bot:
        assert all(item['name'] != 'hourly-notes' for record in bot.state()['plugins'] for item in record['crons'])
        schema = next(item for item in bot.preview_tools() if item['name'] == 'group_summary_card')['parameters']
        assert 'description' in schema['properties']['start_at']
        assert {'hours', 'start_at', 'end_at'} <= schema['properties'].keys()
        for arguments in ({'hours': 0}, {'hours': 12, 'start_at': '2026-10-06T12:00:00', 'end_at': '2026-10-06T14:00:00'},
                          {'start_at': '2026-10-06T12:00:00'},
                          {'start_at': '2026-10-06T14:00:00', 'end_at': '2026-10-06T13:00:00'},
                          {'start_at': '2026-10-06T12:00:00', 'end_at': '2026-10-06T19:00:00'}):
            with pytest.raises((ValueError, RuntimeError)):
                await bot.tool('group_summary_card', arguments)
        assert not bot.deliveries


@pytest.mark.asyncio
async def test_relative_twelve_hours_reads_exact_interval(package):
    async with model_source() as (url, calls), PluginTest(package, now=lambda: NOW, models=models(url)) as bot:
        message(bot, 5, 59, '十二小时前的消息')
        for index in range(6):
            message(bot, 8 + index, 0, f'近十二小时 {index}')
        await bot.tool('group_summary_card', {'hours': 12})
        await finish(bot)
        assert calls[-1][1]['统计']['消息数'] == 6
        assert '十二小时前的消息' not in calls[-1][1]['群聊记录']


@pytest.mark.asyncio
async def test_duplicate_report_returns_actual_running_window(package):
    gate = asyncio.Event()
    async with model_source(gate) as (url, calls), PluginTest(package, now=lambda: NOW, models=models(url)) as bot:
        for index in range(6):
            message(bot, 13, index * 5, f'安排 {index}')
        first = json.loads(await bot.tool('group_summary_card', {'hours': 12}))
        second = json.loads(await bot.tool('group_summary_card', {'hours': 1}))
        assert first['status'] == 'started' and second['status'] == 'already_running'
        assert first['window'] == second['window']
        gate.set()
        await bot.wait_tasks('群聊总结 ')
        assert len(bot.deliveries) == 1
