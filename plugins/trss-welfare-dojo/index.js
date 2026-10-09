import * as PluginBase from '../../lib/plugins/plugin.js';
import { startService } from './src/service.mjs';

export class WelfareDojo extends PluginBase.default {
    constructor() {
        super({ name: '福利寮开启检测', dsc: '监听当天开启消息，供 OAS 查询', event: 'message.group', rule: [] });
    }

    async init() {
        const bot = globalThis.Bot;
        if (typeof bot?.on !== 'function' || typeof bot?.off !== 'function') {
            throw new Error('需要 TRSS-Yunzai 的 Bot 事件接口');
        }
        const key = Symbol.for('oas.trss-welfare-dojo.service');
        if (globalThis[key]) await globalThis[key].close();
        const service = await startService({ bot, logger: globalThis.logger });
        globalThis[key] = service;
        if (PluginBase.PluginCleanup) {
            this[PluginBase.PluginCleanup] = [{ active: true, dispose: async () => {
                await service.close();
                if (globalThis[key] === service) delete globalThis[key];
            } }];
        }
    }
}
