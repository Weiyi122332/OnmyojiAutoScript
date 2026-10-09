import assert from 'node:assert/strict';
import { test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { EventEmitter } from 'node:events';
import { startService, pickAccount, STATUS_PATH } from '../src/service.mjs';
import { normalizeConfig } from '../src/config.mjs';

const NOW = Date.parse('2026-10-09T20:00:00+08:00');
const event = fields => ({ post_type: 'message', message_type: 'group', self_id: 789, group_id: 123,
    user_id: 456, time: NOW / 1000, message: [{ type: 'text', text: '福利寮已开' }], ...fields });

async function fixture(t, overrides = {}, history = []) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'trss-welfare-'));
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const reservation = net.createServer();
    await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
    const port = reservation.address().port;
    await new Promise(resolve => reservation.close(resolve));
    const config = normalizeConfig({ bot_id: '789', group_id: '123', member_id: '456', api_token: 'test-token',
        keywords: '福利寮已开', http_host: '127.0.0.1', http_port: port, ...overrides });
    const configPath = path.join(directory, 'config.json');
    fs.writeFileSync(configPath, JSON.stringify(config));
    const calls = [], logs = [];
    const bot = new EventEmitter();
    bot.uin = [789];
    bot[789] = { gl: new Map([[123, {}]]), pickGroup(groupId) {
        assert.equal(groupId, 123);
        return { async getChatHistory(...args) { calls.push(args); return history; } };
    } };
    const service = await startService({ bot, logger: { info: line => logs.push(line), warn: line => logs.push(line) },
        dataPath: directory, configPath, clock: () => NOW });
    t.after(() => service.close());
    const url = `http://127.0.0.1:${port}${STATUS_PATH}`;
    const query = (token = 'test-token', options = {}) => fetch(url, {
        ...options, headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(3000),
    });
    let stamp = Date.now();
    const save = raw => {
        fs.writeFileSync(configPath, typeof raw === 'string' ? raw : JSON.stringify(raw));
        stamp += 1000;
        fs.utimesSync(configPath, stamp / 1000, stamp / 1000);
    };
    return { bot, service, calls, logs, query, config, configPath, save };
}

test('ordinary flattened TRSS messages open today without a prefix, and other bots do not', async t => {
    const f = await fixture(t);
    assert.equal((await (await f.query()).json()).opened, false);
    f.bot.emit('message.group', event({ self_id: 999 }));
    assert.equal((await (await f.query()).json()).opened, false);
    f.bot.emit('message.group', event());
    assert.deepEqual(await (await f.query()).json(), { date: '2026-10-09', opened: true });
    assert.equal(f.calls.length, 1);
    assert.ok(f.logs.every(line => !line.includes('test-token') && !line.includes('456')));
});

test('history is read through the selected TRSS account and handles flattened text', async t => {
    const f = await fixture(t, {}, [event()]);
    const response = await f.query();
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await response.json(), { date: '2026-10-09', opened: true });
    assert.deepEqual(f.calls, [[undefined, 100, false]]);
});

test('HTTP only exposes an authenticated read-only status endpoint', async t => {
    const f = await fixture(t);
    assert.equal((await f.query('wrong-token')).status, 401);
    assert.equal((await f.query('test-token', { method: 'POST' })).status, 405);
    assert.equal(f.calls.length, 0);
    const response = await f.query();
    assert.deepEqual(Object.keys(await response.json()).sort(), ['date', 'opened']);
});

test('config reload changes account matching and token, invalid config blocks and recovers', async t => {
    const f = await fixture(t);
    f.bot.emit('message.group', event());
    assert.equal((await (await f.query()).json()).opened, true);
    f.save({ ...f.config, member_id: '999', api_token: 'new-token' });
    assert.equal((await f.query()).status, 401);
    assert.equal((await (await f.query('new-token')).json()).opened, false);
    f.bot.emit('message.group', event({ user_id: 999 }));
    assert.equal((await (await f.query('new-token')).json()).opened, true);
    f.save('{invalid');
    assert.equal((await f.query('new-token')).status, 503);
    f.save({ ...f.config, enabled: false });
    assert.deepEqual(await (await f.query()).json(), { date: '2026-10-09', opened: false });
});

test('port change requires restart and cleanup releases port and event listener', async t => {
    const f = await fixture(t);
    f.save({ ...f.config, http_port: f.config.http_port === 65535 ? 65534 : f.config.http_port + 1 });
    assert.equal((await f.query()).status, 503);
    f.save(f.config);
    assert.equal((await f.query()).status, 200);
    await f.service.close();
    assert.equal(f.bot.listenerCount('message.group'), 0);
    assert.equal(f.service.server.listening, false);
});

test('multi-account selection uses group membership and otherwise requires bot_id', () => {
    const one = { pickGroup() {}, gl: new Map([[123, {}]]) };
    const two = { pickGroup() {}, gl: new Map() };
    const bot = { uin: [1, 2], 1: one, 2: two };
    assert.equal(pickAccount(bot, { group_id: '123', bot_id: '' }), one);
    two.gl.set(123, {});
    assert.throws(() => pickAccount(bot, { group_id: '123', bot_id: '' }));
    assert.equal(pickAccount(bot, { group_id: '123', bot_id: '2' }), two);
    assert.throws(() => pickAccount(bot, { group_id: '123', bot_id: '3' }));
});
