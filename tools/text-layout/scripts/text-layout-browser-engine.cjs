const fs = require('node:fs');
const http = require('node:http');

function getJson(url, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (error) {
          reject(error);
        }
      });
    });
    request.setTimeout(timeoutMs, () => request.destroy(new Error(`Timeout al consultar ${url}`)));
    request.on('error', reject);
  });
}

function wait(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

class CDPClient {
  constructor(wsUrl, commandTimeoutMs = 10000) {
    this.ws = new WebSocket(wsUrl);
    this.commandTimeoutMs = commandTimeoutMs;
    this.id = 1;
    this.callbacks = new Map();
    this.isReady = new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
    this.ws.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id && this.callbacks.has(message.id)) {
        const callback = this.callbacks.get(message.id);
        this.callbacks.delete(message.id);
        callback(message);
      }
    });
  }

  async send(method, params = {}) {
    await this.isReady;
    const messageId = this.id++;
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.callbacks.delete(messageId);
        reject(new Error(`CDP no respondió a ${method}`));
      }, this.commandTimeoutMs);
      this.callbacks.set(messageId, message => {
        clearTimeout(timeoutId);
        if (message.error) reject(new Error(message.error.message || `Falló ${method}`));
        else resolve(message.result);
      });
      this.ws.send(JSON.stringify({ id: messageId, method, params }));
    });
  }

  async evaluate(expression) {
    const response = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture: true
    });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text || 'Falló la evaluación de la página.');
    return response.result ? response.result.value : null;
  }

  close() {
    this.ws.close();
  }
}

function resolveEdgePath(configuredPath = process.env.DEVBRAIN_EDGE_PATH) {
  const candidates = configuredPath
    ? [configuredPath]
    : [
        'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
        'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
      ];
  return candidates.find(candidate => fs.existsSync(candidate)) || null;
}

async function getFreePort() {
  const server = http.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}

async function waitForTarget(port, attempts = 40) {
  let version = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      version = await getJson(`http://127.0.0.1:${port}/json/version`);
      if (version.webSocketDebuggerUrl) return version;
    } catch {
      await wait(150);
    }
  }
  throw new Error('Microsoft Edge no abrió el puerto de depuración remoto.');
}

async function waitForPage(cdp, attempts = 50) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const state = await cdp.evaluate('document.readyState');
    if (state === 'complete' || state === 'interactive') return;
    await wait(100);
  }
  throw new Error('La página no terminó de cargar en el navegador.');
}

module.exports = { CDPClient, getJson, wait, resolveEdgePath, getFreePort, waitForTarget, waitForPage };
