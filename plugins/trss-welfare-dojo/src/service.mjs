import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import { createHash, timingSafeEqual } from 'node:crypto';
import { CONFIG_COMMENTS, normalizeConfig } from './config.mjs';
import { WelfareMonitor, writeJson } from './monitor.mjs';

export const STATUS_PATH = '/welfare-dojo/today';

export function pickAccount(bot, config) {
    if (config.bot_id) {
        const account = bot[config.bot_id];
        if (!account?.pickGroup) throw new Error('指定机器人账号尚未连接');
        return account;
    }
    const accounts = Array.from(bot.uin ?? []).map(id => bot[id]).filter(account => account?.pickGroup);
    const inGroup = accounts.filter(account => account.gl?.has(Number(config.group_id)) || account.gl?.has(config.group_id));
    if (inGroup.length === 1) return inGroup[0];
    if (accounts.length === 1) return accounts[0];
    throw new Error('请填写 bot_id 以选择已连接的机器人账号');
}

export async function startService({ bot, logger, dataPath = path.join(process.cwd(), 'data/oas-welfare-dojo'),
                                     configPath = path.join(dataPath, 'config.json'), clock = Date.now }) {
    const exists = fs.existsSync(configPath);
    const config = normalizeConfig(exists ? JSON.parse(fs.readFileSync(configPath, 'utf8')) : {}, true);
    writeJson(configPath, { _comments: CONFIG_COMMENTS, ...config });
    const monitor = new WelfareMonitor({ dataPath, logger, fetchHistory: async params => {
        const account = pickAccount(bot, monitor.config);
        const group = account.pickGroup(Number(params.group_id));
        if (typeof group?.getChatHistory !== 'function') throw new Error('当前协议不支持群历史消息');
        return group.getChatHistory(params.message_seq, params.count, false);
    } }, config, clock);

    let settingsStamp = fs.statSync(configPath).mtimeMs;
    let settingsError = false;
    let lastWarning = 0;
    function refreshConfig() {
        try {
            const stamp = fs.statSync(configPath).mtimeMs;
            if (stamp !== settingsStamp || settingsError) {
                const updated = normalizeConfig(JSON.parse(fs.readFileSync(configPath, 'utf8')));
                if (updated.http_host !== config.http_host || updated.http_port !== config.http_port) {
                    throw new Error('修改监听地址或端口后需要重启云崽');
                }
                monitor.update(updated);
                settingsStamp = stamp;
                settingsError = false;
            }
        } catch {
            settingsError = true;
            if (Date.now() - lastWarning >= 60000) {
                logger.warn('福利寮配置读取失败，请检查配置格式；修改监听地址或端口后需重启云崽');
                lastWarning = Date.now();
            }
        }
        return !settingsError;
    }

    const listener = event => {
        if (!refreshConfig()) return;
        try { monitor.onMessage({ post_type: 'message', message_type: 'group', ...event }); }
        catch { logger.warn('福利寮消息状态保存失败'); }
    };
    const hash = value => createHash('sha256').update(value).digest();
    const server = http.createServer(async (req, res) => {
        const send = (code, body) => {
            res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
            res.end(JSON.stringify(body));
        };
        req.resume();
        if (req.url !== STATUS_PATH) return send(404, { error: 'not-found' });
        if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return send(405, { error: 'method-not-allowed' }); }
        if (!refreshConfig()) return send(503, { error: 'unavailable' });
        const header = req.headers.authorization;
        if (typeof header !== 'string' || !timingSafeEqual(hash(header), hash(`Bearer ${monitor.config.api_token}`))) {
            return send(401, { error: 'unauthorized' });
        }
        try { send(200, await monitor.status()); }
        catch {
            if (Date.now() - lastWarning >= 60000) {
                logger.warn('福利寮当天消息补读失败，请检查机器人连接及历史消息接口');
                lastWarning = Date.now();
            }
            send(503, { error: 'unavailable' });
        }
    });
    try {
        await new Promise((resolve, reject) => {
            server.once('error', reject);
            server.listen(config.http_port, config.http_host, () => { server.off('error', reject); resolve(); });
        });
    } catch (error) { monitor.close(); throw error; }
    server.on('error', error => logger.warn(`福利寮接口错误：${error.code ?? 'unknown'}`));
    bot.on('message.group', listener);
    logger.info(`福利寮检测已启动：端口 ${config.http_port}，接口 ${STATUS_PATH}`);
    if (!exists) logger.info('请在 data/oas-welfare-dojo/config.json 填写群号、成员QQ号和开启关键词');
    return { server, monitor, close: async () => {
        bot.off('message.group', listener);
        monitor.close();
        if (!server.listening) return;
        await new Promise(resolve => { server.close(resolve); server.closeAllConnections?.(); });
    } };
}
