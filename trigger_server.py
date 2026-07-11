#!/usr/bin/env python3
"""
OFI dashboard update trigger server
Port: 8765
POST /update -> GitHub Actions workflow_dispatch
"""
import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

env_path = Path(__file__).parent / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
TRIGGER_SECRET = os.environ.get('TRIGGER_SECRET', '')
REPO           = 'mantech0/ofi-analysis'
WORKFLOW_FILE  = 'update.yml'

CORS_HEADERS = {
    'Access-Control-Allow-Origin':  '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[trigger] {fmt % args}')

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(data))
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        if self.path != '/update':
            self._send(404, {'error': 'not found'})
            return

        auth = self.headers.get('Authorization', '')
        if TRIGGER_SECRET and auth != f'Bearer {TRIGGER_SECRET}':
            self._send(401, {'error': 'unauthorized'})
            return

        if not GITHUB_TOKEN:
            self._send(500, {'error': 'GITHUB_TOKEN not set'})
            return

        url = f'https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches'
        payload = json.dumps({'ref': 'main'}).encode()
        req = urllib.request.Request(
            url, data=payload, method='POST',
            headers={
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept':        'application/vnd.github.v3+json',
                'Content-Type':  'application/json',
            }
        )
        try:
            with urllib.request.urlopen(req) as resp:
                self._send(200, {'status': 'dispatched', 'http': resp.status})
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            self._send(e.code, {'error': body})
        except Exception as e:
            self._send(500, {'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('TRIGGER_PORT', 8765))
    print(f'[trigger] listening on :{port}')
    HTTPServer(('0.0.0.0', port), Handler).serve_forever()
