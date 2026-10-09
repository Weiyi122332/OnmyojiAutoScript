import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { normalizeConfig } from '../src/config.mjs';
import { chinaDay, latestMatch, messageText, WelfareMonitor } from '../src/monitor.mjs';

const NOW = Date.parse('2026-10-09T20:00:00+08:00');
const config = normalizeConfig({ group_id: '123', member_id: '456', api_token: 'test-token',
    keywords: '福利寮已开|可以打了', excluded_keywords: '未开启|道馆取消' });
const event = (text = '福利寮已开', fields = {}) => ({ post_type: 'message', message_type: 'group',
    group_id: 123, user_id: 456, time: NOW / 1000, message_id: 1,
    message: [{ type: 'text', data: { text } }], ...fields });

function context(t, pages = [{ messages: [] }]) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'welfare-dojo-'));
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const calls = [];
    return { dataPath: directory, configPath: path.join(directory, 'config.json'), calls,
        logger: { info() {}, warn() {} },
        async fetchHistory(...args) {
            calls.push(args);
            const page = pages.shift();
            if (page instanceof Error) throw page;
            return page?.messages;
        },
    };
}

test('only the configured group, sender and ordinary text can match', () => {
    for (const fields of [{ group_id: 999 }, { user_id: 999 }, { message_type: 'private' },
        { post_type: 'notice' }, { anonymous: {} }, { group_id: undefined },
        { message: [{ type: 'image', data: { file: '福利寮已开' } }] },
        { message: [{ type: 'reply', data: { id: '福利寮已开' } }] }]) {
        assert.equal(latestMatch([event(undefined, fields)], config, NOW), null);
    }
    assert.equal(latestMatch([event()], config, NOW).allowed, true);
    assert.equal(latestMatch([event('可以打了')], config, NOW).allowed, true);
    assert.equal(messageText({ message: '[CQ:reply,id=福利寮已开]普通文字&amp;' }), '普通文字&');
    assert.equal(latestMatch([event('', { message: null, raw_message: '福利寮已开' })], config, NOW).allowed, true);
});

test('yesterday, future and malformed timestamps cannot open today', () => {
    for (const time of [(NOW - 86400000) / 1000, (NOW + 1000) / 1000, NOW, Infinity, NaN, 'invalid', null]) {
        assert.equal(latestMatch([event(undefined, { time })], config, NOW), null);
    }
    const midnight = Date.parse('2026-10-09T00:05:00+08:00');
    assert.equal(chinaDay(midnight), '2026-10-09');
    assert.equal(latestMatch([event('', { raw_message: '福利寮已开', message: null,
        time: midnight / 1000 })], config, midnight).allowed, true);
    assert.equal(latestMatch([event(undefined, { time: (midnight - 360000) / 1000 })], config, midnight), null);
});

test('latest cancellation wins before first opening, including equal timestamps', () => {
    const open = event(undefined, { time: NOW / 1000 - 10 });
    assert.equal(latestMatch([event('道馆取消'), open], config, NOW).allowed, false);
    assert.equal(latestMatch([event('福利寮已开，但未开启')], config, NOW).allowed, false);
    assert.equal(latestMatch([event(), event('道馆取消')], config, NOW).allowed, false);
});

test('today status persists through restart and expires at Beijing midnight', async t => {
    const ctx = context(t);
    let now = NOW;
    const monitor = new WelfareMonitor(ctx, config, () => now);
    monitor.onMessage(event());
    assert.deepEqual(await monitor.status(), { date: '2026-10-09', opened: true });
    assert.equal(ctx.calls.length, 0);
    const restarted = new WelfareMonitor(ctx, config, () => now);
    assert.equal((await restarted.status()).opened, true);
    now = Date.parse('2026-10-10T00:00:00+08:00');
    assert.deepEqual(await restarted.status(), { date: '2026-10-10', opened: false });
    restarted.onMessage(event());
    assert.equal((await restarted.status()).opened, false);
    const stored = fs.readFileSync(path.join(ctx.dataPath, 'today.json'), 'utf8');
    assert.ok(!stored.includes('test-token') && !stored.includes('福利寮'));
});

test('a message checked just before midnight cannot open the next day', t => {
    const ctx = context(t);
    const before = Date.parse('2026-10-09T23:59:59.999+08:00');
    let now = before;
    const monitor = new WelfareMonitor(ctx, config, () => now);
    now = before + 1;
    monitor.apply(latestMatch([event(undefined, { time: before / 1000 })], config, before));
    assert.equal(monitor.state.date, '2026-10-10');
    assert.equal(monitor.state.opened, false);
});

test('a matched day stays open after later cancellation and stops reading history', async t => {
    const ctx = context(t);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    monitor.onMessage(event());
    monitor.onMessage(event('道馆取消'));
    await monitor.status(); await monitor.status();
    assert.equal(monitor.state.opened, true);
    assert.equal(ctx.calls.length, 0);
});

test('startup history uses internal action data, paginates and then stops', async t => {
    const ordinary = event('普通消息', { time: NOW / 1000 - 1, message_id: 22 });
    const ctx = context(t, [{ messages: [ordinary] }, { messages: [event(undefined, { time: NOW / 1000 - 2 })] }]);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    assert.equal((await monitor.status()).opened, true);
    await monitor.status();
    assert.equal(ctx.calls.length, 2);
    assert.equal(ctx.calls[0][0].group_id, '123');
    assert.equal(ctx.calls[1][0].message_seq, '22');
});

test('ordinary startup history is read once, then events update status', async t => {
    const ctx = context(t, [{ messages: [] }]);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    assert.equal((await monitor.status()).opened, false);
    assert.equal((await monitor.status()).opened, false);
    monitor.onMessage(event());
    assert.equal((await monitor.status()).opened, true);
    assert.equal(ctx.calls.length, 1);
});

test('history supplies missing protocol fields but checks sender and latest cancellation', async t => {
    const ctx = context(t, [{ messages: [
        { user_id: 456, time: NOW / 1000 - 10, raw_message: '福利寮已开' },
        { sender: { user_id: 456 }, time: NOW / 1000, raw_message: '道馆取消' },
        { user_id: 999, time: NOW / 1000, raw_message: '福利寮已开' },
    ] }]);
    assert.equal((await new WelfareMonitor(ctx, config, () => NOW).status()).opened, false);
});

test('live cancellation is not overwritten by older history', async t => {
    const ctx = context(t, [{ messages: [event(undefined, { time: NOW / 1000 - 10 })] }]);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    monitor.onMessage(event('道馆取消'));
    assert.equal((await monitor.status()).opened, false);
});

test('history stops at yesterday, repeated cursor and configured page limit', async t => {
    for (const [pages, limit, expected] of [
        [[{ messages: [event(undefined, { time: (NOW - 86400000) / 1000 })] }], 5, 1],
        [[{ messages: [event('普通消息')] }, { messages: [event('普通消息')] }], 5, 2],
        [[{ messages: [event('普通消息')] }], 1, 1],
    ]) {
        const ctx = context(t, pages);
        const monitor = new WelfareMonitor(ctx, { ...config, history_max_pages: limit }, () => NOW);
        assert.equal((await monitor.status()).opened, false);
        assert.equal(ctx.calls.length, expected);
    }
});

test('failed or malformed history is retried and never opens the gate', async t => {
    for (const failure of [new Error('failed'), { messages: null }, { status: 'ok', data: { messages: [event()] } }]) {
        const ctx = context(t, [failure, { messages: [event()] }]);
        const monitor = new WelfareMonitor(ctx, config, () => NOW);
        await assert.rejects(monitor.status());
        assert.equal(monitor.state.opened, false);
        assert.equal((await monitor.status()).opened, true);
    }
});

test('concurrent queries share one history request', async t => {
    const ctx = context(t, [{ messages: [event()] }]);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    const results = await Promise.all([monitor.status(), monitor.status()]);
    assert.equal(ctx.calls.length, 1);
    assert.equal(results.every(r => r.opened === true), true);
});

test('configuration changes discard old detection and disabled plugin performs no history calls', async t => {
    const ctx = context(t, [{ messages: [] }]);
    const monitor = new WelfareMonitor(ctx, config, () => NOW);
    monitor.onMessage(event());
    monitor.update({ ...config, member_id: '999' });
    assert.equal((await monitor.status()).opened, false);
    monitor.update({ ...config, enabled: false });
    monitor.onMessage(event());
    assert.equal((await monitor.status()).opened, false);
    assert.equal(ctx.calls.length, 1);
});

test('cleanup or reconfiguration during history prevents old results from being applied', async t => {
    for (const cleanup of [true, false]) {
        const ctx = context(t);
        let finish;
        ctx.fetchHistory = () => new Promise(resolve => { finish = resolve; });
        const monitor = new WelfareMonitor(ctx, config, () => NOW);
        const result = monitor.status();
        const rejected = assert.rejects(result);
        await Promise.resolve();
        if (cleanup) monitor.close();
        else monitor.update({ ...config, member_id: '999' });
        await rejected;
        finish([event()]);
        await Promise.resolve();
        assert.equal(monitor.state.opened, false);
    }
});

test('configuration validates IDs, limits and token and generates a first-run token', () => {
    assert.ok(normalizeConfig({}, true).api_token.length >= 32);
    for (const partial of [{ group_id: 'invalid' }, { member_id: '0' }, { api_token: '' },
        { history_max_pages: 21 }, { history_page_size: 0 }, { enabled: 'yes' }]) {
        assert.throws(() => normalizeConfig({ ...config, ...partial }));
    }
});
