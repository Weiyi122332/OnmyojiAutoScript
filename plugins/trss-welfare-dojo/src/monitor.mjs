import fs from 'node:fs';
import path from 'node:path';
import { fingerprint, words } from './config.mjs';

// Fixed UTC+8, independent of the server's timezone.
export const chinaDay = (millis = Date.now()) => new Date(millis + 8 * 3600000).toISOString().slice(0, 10);

export function writeJson(file, value) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const temporary = `${file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2), { mode: 0o600 });
    fs.renameSync(temporary, file);
}

export function messageText(message) {
    if (Array.isArray(message.message)) {
        return message.message.filter(s => s?.type === 'text' && typeof (s.text ?? s.data?.text) === 'string')
            .map(s => s.text ?? s.data.text).join('');
    }
    const text = typeof message.message === 'string' ? message.message : message.raw_message;
    if (typeof text !== 'string') return '';
    return text.replace(/\[CQ:[^\]]*\]/g, '').replace(/&#91;/g, '[').replace(/&#93;/g, ']')
        .replace(/&#44;/g, ',').replace(/&amp;/g, '&');
}

export function latestMatch(messages, config, now = Date.now()) {
    let latest = null;
    for (const message of messages) {
        if (!message || message.post_type !== 'message' || message.message_type !== 'group' || message.anonymous) continue;
        if (String(message.group_id) !== config.group_id ||
            String(message.user_id ?? message.sender?.user_id) !== config.member_id) continue;
        if (typeof message.time !== 'number' && typeof message.time !== 'string') continue;
        const time = Number(message.time);
        const sent = time * 1000;
        if (!Number.isFinite(sent) || sent <= 0 || sent > now || chinaDay(sent) !== chinaDay(now)) continue;
        const text = messageText(message);
        const excluded = words(config.excluded_keywords).some(word => text.includes(word));
        const opening = words(config.keywords).some(word => text.includes(word));
        if (!excluded && !opening) continue;
        const candidate = { time, allowed: opening && !excluded };
        if (!latest || time > latest.time || (time === latest.time && !candidate.allowed)) latest = candidate;
    }
    return latest;
}

export class WelfareMonitor {
    constructor(ctx, config, clock = Date.now) {
        this.ctx = ctx;
        this.config = config;
        this.clock = clock;
        this.file = path.join(ctx.dataPath, 'today.json');
        this.closed = false;
        this.revision = 0;
        this.historyDay = null;
        this.historyPromise = null;
        this.abort = new AbortController();
        this.state = null;
        if (fs.existsSync(this.file)) {
            try { this.state = JSON.parse(fs.readFileSync(this.file, 'utf8')); }
            catch { ctx.logger.warn('福利寮状态读取失败，将重新核对当天消息'); }
        }
        this.ensureDay();
    }

    ensureDay() {
        const date = chinaDay(this.clock());
        const identity = fingerprint(this.config);
        if (!this.state || this.state.date !== date || this.state.fingerprint !== identity) {
            this.state = { date, fingerprint: identity, opened: false, latestTime: 0, latestAllowed: false };
            this.historyDay = null;
            writeJson(this.file, this.state);
        }
    }

    isConfigured() {
        return this.config.enabled && this.config.group_id && this.config.member_id && words(this.config.keywords).length;
    }

    apply(match) {
        this.ensureDay();
        if (!match || this.closed || this.state.opened === true) return;
        if (chinaDay(match.time * 1000) !== this.state.date || match.time * 1000 > this.clock()) return;
        if (match.time < this.state.latestTime ||
            (match.time === this.state.latestTime && this.state.latestAllowed === false)) return;
        const next = { ...this.state, latestTime: match.time, latestAllowed: match.allowed, opened: match.allowed };
        writeJson(this.file, next);
        this.state = next;
        if (match.allowed) this.ctx.logger.info('已确认今天开启福利寮');
    }

    onMessage(message) {
        if (this.closed || !this.isConfigured()) return;
        if (this.config.bot_id && String(message.self_id) !== this.config.bot_id) return;
        this.apply(latestMatch([message], this.config, this.clock()));
    }

    update(config) {
        this.abort.abort();
        this.abort = new AbortController();
        this.config = config;
        this.revision++;
        this.historyPromise = null;
        this.ensureDay();
    }

    action(params) {
        const signal = this.abort.signal;
        return new Promise((resolve, reject) => {
            const cancel = () => { clearTimeout(timer); reject(new Error('检测已停止')); };
            const timer = setTimeout(() => {
                signal.removeEventListener('abort', cancel);
                reject(new Error('消息补读超时'));
            }, 8000);
            signal.addEventListener('abort', cancel, { once: true });
            Promise.resolve().then(() => {
                if (signal.aborted) throw new Error('检测已停止');
                return this.ctx.fetchHistory(params);
            }).then(resolve, reject).finally(() => {
                clearTimeout(timer);
                signal.removeEventListener('abort', cancel);
            });
        });
    }

    async readHistory(revision, date) {
        const messages = [], cursors = new Set();
        let cursor;
        for (let pageNumber = 0; pageNumber < this.config.history_max_pages; pageNumber++) {
            const params = { group_id: this.config.group_id, count: this.config.history_page_size,
                reverse_order: false, disable_get_url: true, parse_mult_msg: false };
            if (cursor !== undefined) params.message_seq = cursor;
            const history = await this.action(params);
            if (this.closed || revision !== this.revision || date !== chinaDay(this.clock())) return;
            if (!Array.isArray(history)) throw new Error('消息补读结果无效');
            const page = history.filter(m => m && typeof m === 'object').map(m => ({
                post_type: 'message', message_type: 'group', group_id: this.config.group_id, ...m,
            }));
            messages.push(...page);
            const match = latestMatch(messages, this.config, this.clock());
            if (match) { this.apply(match); break; }
            const dated = page.filter(m => Number.isFinite(Number(m.time)) && Number(m.time) > 0
                && Number(m.time) * 1000 <= this.clock())
                .sort((a, b) => Number(a.time) - Number(b.time));
            const oldest = dated[0];
            if (!oldest || chinaDay(Number(oldest.time) * 1000) < date) break;
            const next = String(oldest.message_id ?? '');
            if (!next || cursors.has(next)) break;
            cursors.add(next);
            cursor = next;
        }
        if (!this.closed && revision === this.revision && date === chinaDay(this.clock())) this.historyDay = date;
    }

    async status() {
        if (this.closed) throw new Error('插件已停止');
        this.ensureDay();
        if (this.isConfigured() && !this.state.opened && this.historyDay !== this.state.date) {
            if (!this.historyPromise) {
                const operation = this.readHistory(this.revision, this.state.date);
                this.historyPromise = operation;
                operation.finally(() => { if (this.historyPromise === operation) this.historyPromise = null; }).catch(() => {});
            }
            try { await this.historyPromise; }
            catch (error) { if (!this.state.opened || this.closed) throw error; }
        }
        this.ensureDay();
        return { date: this.state.date, opened: Boolean(this.isConfigured() && this.state.opened === true) };
    }

    close() {
        this.closed = true;
        this.revision++;
        this.abort.abort();
    }
}
