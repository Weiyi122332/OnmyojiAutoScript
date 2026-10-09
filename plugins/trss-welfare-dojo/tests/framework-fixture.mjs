// Minimal local TRSS loader harness. Not included in the installation package.
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import net from 'node:net';
import { EventEmitter } from 'node:events';
import { fileURLToPath, pathToFileURL } from 'node:url';

const directory = process.argv[2];
const framework = path.join(directory, 'Yunzai');
const baseFile = path.join(framework, 'lib/plugins/plugin.js');
fs.mkdirSync(path.dirname(baseFile), { recursive: true });
if (process.argv[3]) fs.copyFileSync(process.argv[3], baseFile);
else fs.writeFileSync(baseFile, `export const PluginCleanup = Symbol('PluginCleanup');
export default class plugin { constructor(options) { Object.assign(this, options); } }`);
fs.writeFileSync(path.join(framework, 'package.json'), '{"type":"module"}');
const pluginPath = path.join(framework, 'plugins/trss-welfare-dojo');
const source = fileURLToPath(new URL('../', import.meta.url));
fs.mkdirSync(pluginPath, { recursive: true });
for (const file of ['index.js', 'package.json']) fs.copyFileSync(path.join(source, file), path.join(pluginPath, file));
fs.cpSync(path.join(source, 'src'), path.join(pluginPath, 'src'), { recursive: true });
const dataPath = path.join(framework, 'data/oas-welfare-dojo');
fs.mkdirSync(dataPath, { recursive: true });
const raw = JSON.parse(fs.readFileSync(path.join(directory, 'plugin.json'), 'utf8'));
const reservation = net.createServer();
await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
raw.http_port = reservation.address().port;
raw.http_host = '127.0.0.1';
await new Promise(resolve => reservation.close(resolve));
fs.writeFileSync(path.join(dataPath, 'config.json'), JSON.stringify(raw));
process.chdir(framework);
const bot = globalThis.Bot = new EventEmitter();
bot.uin = [789];
bot[789] = { gl: new Map([[123, {}]]), pickGroup() { return { async getChatHistory() { return []; } }; } };
globalThis.logger = { info() {}, warn() {} };
const entry = await import(pathToFileURL(path.join(pluginPath, 'index.js')));
const plugins = Object.values(entry).filter(value => value?.prototype);
if (plugins.length !== 1) throw new Error('Invalid plugin exports');
const instance = new plugins[0]();
await instance.init();
new plugins[0](); // TRSS creates a separate message instance after init.
const service = globalThis[Symbol.for('oas.trss-welfare-dojo.service')];
const base = await import(pathToFileURL(baseFile));
async function dispose() {
    for (const cleanup of instance[base.PluginCleanup]) {
        if (cleanup.active) { cleanup.active = false; await cleanup.dispose.call(instance); }
    }
}
if (process.argv[4] === 'check-only') {
    await dispose();
    if (bot.listenerCount('message.group') || service.server.listening) throw new Error('Cleanup failed');
    process.stdout.write('Native entry, init and cleanup verified\n');
} else {
    const controls = http.createServer(async (req, res) => {
        if (req.method !== 'POST' || req.url !== '/event') { res.writeHead(404).end(); return; }
        let body = '';
        for await (const part of req) body += part;
        bot.emit('message.group', JSON.parse(body));
        res.setHeader('Content-Type', 'application/json');
        res.end('{"ok":true}');
    });
    await new Promise(resolve => controls.listen(0, '127.0.0.1', resolve));
    process.stdout.write(JSON.stringify({ port: service.server.address().port, event_port: controls.address().port }) + '\n');
    process.on('SIGTERM', async () => { controls.close(); await dispose(); });
}
