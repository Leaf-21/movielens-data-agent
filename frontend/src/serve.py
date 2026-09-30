#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
前端静态服务器 + Agent 反向代理（成员C）

职责：
  1. 提供 frontend/public 下的静态页面（index.html / style.css / js/*）。
  2. 把 /api/* 与 /health 反向代理到成员B的 Agent 服务，
     从而前端与 Agent 同源，避免浏览器跨域（CORS）问题。

选型说明：
  与成员A/B 的服务层保持一致，仅用 Python 标准库（http.server + urllib），
  零第三方依赖，演示环境无需额外安装。

启动：
  python3 frontend/src/serve.py --port 8000
  环境变量 ML_AGENT_URL 指向成员B的 Agent 服务（默认 http://127.0.0.1:8090）
  python3 frontend/src/serve.py --port 8000 --agent-url http://127.0.0.1:8090
"""

import argparse
import http.client
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          os.pardir, 'public')
PUBLIC_DIR = os.path.abspath(PUBLIC_DIR)

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.ico': 'image/x-icon',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
}

G = {}


class Handler(BaseHTTPRequestHandler):

    # ---- 静态资源 ----
    def _serve_static(self, path):
        if path in ('/', ''):
            path = '/index.html'
        rel = os.path.normpath(path.lstrip('/'))
        full = os.path.join(PUBLIC_DIR, rel)
        # 防止目录穿越
        if not os.path.abspath(full).startswith(PUBLIC_DIR):
            self._send(403, 'text/plain; charset=utf-8', b'forbidden')
            return
        if not os.path.isfile(full):
            self._send(404, 'text/plain; charset=utf-8', b'404 not found')
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, 'rb') as f:
            body = f.read()
        self._send(200, MIME.get(ext, 'application/octet-stream'), body)

    # ---- 代理到 Agent ----
    def _proxy(self, method):
        target = G['agent_url']
        parsed = urlparse(target)
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else None

        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=30)
        headers = {'Content-Type': self.headers.get('Content-Type',
                                                     'application/json')}
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self._send(resp.status,
                       resp.getheader('Content-Type', 'application/json; charset=utf-8'),
                       data)
        except Exception as e:
            payload = json.dumps({
                'status': 'FAILED',
                'error': {'code': 'PROXY_ERROR',
                          'message': '前端代理无法连接 Agent 服务 (%s): %s' % (target, e)},
            }, ensure_ascii=False).encode('utf-8')
            self._send(200, 'application/json; charset=utf-8', payload)
        finally:
            conn.close()

    def _send(self, status, ctype, body):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/') or self.path == '/health':
            self._proxy('GET')
        else:
            self._serve_static(urlparse(self.path).path)

    def do_POST(self):
        if self.path.startswith('/api/'):
            self._proxy('POST')
        else:
            self._send(404, 'text/plain; charset=utf-8', b'404')

    def log_message(self, fmt, *args):
        sys.stderr.write('[frontend] %s - %s\n' % (self.address_string(), fmt % args))


def serve(host, port, agent_url):
    G['agent_url'] = agent_url
    httpd = ThreadingHTTPServer((host, port), Handler)
    print('=' * 62)
    print(' MovieLens 前端服务（成员C）')
    print('   页面地址 : http://%s:%d' % (host, port))
    print('   Agent    : %s （/api/* 与 /health 反代到此）' % agent_url)
    print('   静态目录 : %s' % PUBLIC_DIR)
    print('=' * 62)
    print(' 请先启动成员B的 Agent 服务，再打开上面的页面地址')
    print(' 停止服务请按 Ctrl+C')
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[frontend] 收到中断，正在停止 ...')
    finally:
        httpd.server_close()
    return 0


def main():
    ap = argparse.ArgumentParser(description='前端静态服务 + Agent 反代（成员C）')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--agent-url',
                    default=os.environ.get('ML_AGENT_URL', 'http://127.0.0.1:8090'),
                    help='成员B的 Agent 服务地址')
    args = ap.parse_args()
    return serve(args.host, args.port, args.agent_url)


if __name__ == '__main__':
    sys.exit(main())
