import { createHash, randomBytes } from 'node:crypto';

export const DEFAULT_CONFIG = {
    enabled: true, bot_id: '', group_id: '', member_id: '',
    keywords: '福利寮已开启', excluded_keywords: '福利寮未开启|道馆取消',
    api_token: '', http_host: '0.0.0.0', http_port: 2537, history_page_size: 100, history_max_pages: 5,
};

export const CONFIG_COMMENTS = {
    enabled: '是否启用福利寮消息检测：true 开启，false 关闭。',
    bot_id: '机器人QQ号，使用字符串；单账号可留空，多账号建议填写。',
    group_id: '需要监测的QQ群号，使用字符串；机器人必须在该群内。',
    member_id: '指定发言成员的QQ号，使用字符串；只匹配该成员今天的群消息，日期按北京时间核对。',
    keywords: '开启关键词，命中任意一个即可；多个词用英文竖线 | 或换行 \\n 分隔，不需要命令前缀或 @机器人。',
    excluded_keywords: '排除或取消关键词，多个词用英文竖线 | 或换行 \\n 分隔；同一消息命中排除词时不算开启。当天首次确认开启后不再撤销。',
    api_token: '接口访问令牌；启动时为空则自动生成，OAS 使用同一令牌。',
    http_host: 'HTTP监听地址，默认 0.0.0.0 表示监听所有网卡；远程访问使用服务器IP。修改后需重启机器人服务。',
    http_port: 'HTTP接口端口，默认 2537；Docker需映射该端口，服务器需开放该端口。修改后需重启机器人服务。',
    history_page_size: '启动或新一天首次查询时补读群历史的每页条数，默认100，范围1–500；之后通过群消息事件监听。',
    history_max_pages: '首次查询最多补读的页数，默认5，范围1–20；超出范围的历史开启消息可能无法恢复。',
};

export const words = (value) => value.split(/[\r\n|]+/).map(s => s.trim()).filter(Boolean);

export function normalizeConfig(raw = {}, initial = false) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('配置格式错误');
    const result = { ...DEFAULT_CONFIG };
    for (const key of ['bot_id', 'group_id', 'member_id', 'keywords', 'excluded_keywords', 'api_token', 'http_host']) {
        if (raw[key] !== undefined && typeof raw[key] !== 'string') throw new Error('配置字段类型错误');
        result[key] = (raw[key] ?? result[key]).trim();
    }
    if (raw.enabled !== undefined && typeof raw.enabled !== 'boolean') throw new Error('启用状态必须为布尔值');
    result.enabled = raw.enabled ?? true;
    for (const [key, max] of [['history_page_size', 500], ['history_max_pages', 20], ['http_port', 65535]]) {
        const value = raw[key] ?? result[key];
        if (!Number.isInteger(value) || value < 1 || value > max) throw new Error('历史读取范围无效');
        result[key] = value;
    }
    if (initial && !result.api_token) result.api_token = randomBytes(24).toString('hex');
    if (!result.api_token) throw new Error('请设置插件访问令牌');
    if (!result.http_host) throw new Error('监听地址不能为空');
    for (const key of ['bot_id', 'group_id', 'member_id']) {
        if (result[key] && !/^[1-9]\d*$/.test(result[key])) throw new Error('QQ 号码格式错误');
    }
    return result;
}

export function fingerprint(config) {
    return createHash('sha256').update(JSON.stringify([
        config.bot_id, config.group_id, config.member_id, words(config.keywords), words(config.excluded_keywords),
    ])).digest('hex');
}
