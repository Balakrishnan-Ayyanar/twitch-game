"""Loopback HTTP server. Stdlib core; optional guarded EventSub dependency."""
import argparse
import json
import errno
import sys
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit, parse_qs
from http.cookies import SimpleCookie, CookieError
from oauth import OAuthService, OAuthFailure, StdlibOAuthHTTP
from game import Game
from eventsub import (TwitchController, TransportFailure, EventSubTransport, WebSocketFactory, StdlibHelix)
from local_config import load_local_credentials, LocalConfigError

ROOT = Path(__file__).resolve().parent / 'static'
GAME = Game()
LOCK = RLock()
OAUTH = OAuthService()  # No credential/env reads, opt-in or live network by default.
TWITCH = TwitchController(GAME, LOCK, lambda: OAUTH)  # Separate activation off.
LIVE_ENABLED = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Callback query strings contain one-use codes/state. Never log targets,
        # provider errors, request bodies or credentials (including malformed requests).
        pass

    def request_origin(self, require_origin=False):
        hosts = self.headers.get_all('Host', [])
        port = self.server.server_port
        allowed = {'localhost:8000'} if LIVE_ENABLED and port == 8000 else (set() if LIVE_ENABLED else {'localhost:'+str(port), '127.0.0.1:'+str(port)})
        if len(hosts) != 1 or hosts[0].lower() not in allowed:
            self.reply(403, {'error':'Untrusted local host'})
            return None
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.reply(400, {'error':'Invalid request target'})
            return None
        if target.scheme or target.netloc or not self.path.startswith('/') or self.path.startswith('//'):
            self.reply(400, {'error':'Invalid request target'})
            return None
        origin = 'http://'+hosts[0].lower()
        origins = self.headers.get_all('Origin', [])
        if len(origins) > 1 or (origins and origins[0] != origin) or (require_origin and not origins):
            self.reply(403, {'error':'Same-origin request required'})
            return None
        return origin

    def session_id(self):
        values = self.headers.get_all('Cookie', [])
        if len(values) > 1 or (values and len(values[0]) > 4096):
            return None
        try:
            cookie = SimpleCookie()
            cookie.load(values[0] if values else '')
            return cookie['cmc_session'].value if 'cmc_session' in cookie else None
        except CookieError:
            return None

    def reply(self, code, body, content_type='application/json; charset=utf-8', extra_headers=None):
        data = json.dumps(body).encode() if content_type.startswith('application/json') else body
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        if getattr(self, '_new_session_cookie', None):
            self.send_header('Set-Cookie', 'cmc_session='+self._new_session_cookie+'; Path=/; HttpOnly; SameSite=Lax; Max-Age=1800')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for name,value in (extra_headers or {}).items():
            self.send_header(name,value)
        self.end_headers()
        self.wfile.write(data)

    def callback_reply(self, code, result):
        # Browser redirects remove code/state from the displayed URL. JSON clients
        # retain the existing API contract and get only a fixed local return link.
        if 'text/html' in self.headers.get('Accept',''):
            outcome = 'authorized' if code == 200 else 'authorization_failed'
            self.reply(303,b'',content_type='text/plain; charset=utf-8',extra_headers={
                'Location':'http://localhost:8000/?twitch='+outcome})
        else:
            self.reply(code,dict(result,return_to='http://localhost:8000/'))

    def do_GET(self):
        origin = self.request_origin()
        if origin is None:
            return
        path = urlsplit(self.path).path
        if path in ('/api/twitch/status', '/auth/twitch/callback'):
            with LOCK:
                try:
                    if path == '/api/twitch/status':
                        sid,new,result = OAUTH.status(self.session_id(),origin)
                        if new:
                            self._new_session_cookie = sid
                        result.update(TWITCH.status())
                        self.reply(200,result)
                    else:
                        query = urlsplit(self.path).query
                        if len(query) > 8192:
                            raise ValueError()
                        params = parse_qs(query,keep_blank_values=True,max_num_fields=12)
                        if (len(params.get('state',[])) != 1 or
                                any(len(v) != 1 for v in params.values()) or
                                ('code' in params) == ('error' in params)):
                            raise ValueError()
                        result = OAUTH.callback(self.session_id(),origin,params['state'][0],
                            code=params.get('code',[None])[0],error=params.get('error',[None])[0])
                        self.callback_reply(200,result)
                except (OAuthFailure, ValueError):
                    if path == '/auth/twitch/callback':
                        self.callback_reply(400,{'error':'Local authorization unavailable or invalid.'})
                    else:
                        self.reply(400,{'error':'Local authorization unavailable or invalid.'})
            return
        if path == '/api/state':
            with LOCK:
                GAME.tick()
                result = GAME.snapshot()
                result.update(TWITCH.status())
                self.reply(200, result)
            return
        files = {'/': ('index.html','text/html; charset=utf-8'), '/app.js': ('app.js','text/javascript; charset=utf-8'), '/twitch-ui.js': ('twitch-ui.js','text/javascript; charset=utf-8'), '/style.css': ('style.css','text/css; charset=utf-8')}
        if path not in files:
            self.reply(404, {'error': 'Not found'})
            return
        name, mime = files[path]
        self.reply(200, (ROOT / name).read_bytes(), mime)

    def do_POST(self):
        oauth_path = self.path in ('/auth/twitch/start', '/auth/twitch/disconnect', '/api/twitch/connect', '/api/twitch/disconnect')
        origin = self.request_origin(require_origin=oauth_path)
        if origin is None:
            return
        if oauth_path and self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            self.reply(400,{'error':'Expected JSON request'})
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('Invalid body length')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected JSON object')
        except (ValueError, UnicodeError):
            self.reply(400, {'error': 'Invalid JSON request'})
            return
        with LOCK:
            if oauth_path:
                try:
                    if self.path == '/auth/twitch/start':
                        result = OAUTH.start(self.session_id(),origin,self.headers.get('X-CSRF-Token'))
                    elif self.path == '/api/twitch/connect':
                        result = TWITCH.connect(self.session_id(),origin,self.headers.get('X-CSRF-Token'))
                    elif self.path == '/api/twitch/disconnect':
                        result = TWITCH.disconnect(self.session_id(),origin,self.headers.get('X-CSRF-Token'))
                    else:
                        TWITCH.disconnect(self.session_id(),origin,self.headers.get('X-CSRF-Token'))
                        result = OAUTH.disconnect(self.session_id(),origin,self.headers.get('X-CSRF-Token'))
                    self.reply(200,result)
                except (OAuthFailure, TransportFailure):
                    self.reply(403,{'error':'Local authorization disabled or request verification failed.'})
                return
            GAME.tick()
            if self.path == '/api/start':
                GAME.start()
            elif self.path == '/api/restart':
                GAME.restart()
            elif self.path == '/api/vote':
                if not TWITCH.status()['browser_votes_enabled']:
                    self.reply(409, {'ok':False,'message':'Simulated votes disabled after verified Twitch activation.'})
                    return
                ok, message = GAME.vote(body.get('viewer'), body.get('option'), body.get('token'))
                self.reply(200 if ok else 409, {'ok': ok, 'message': message})
                return
            else:
                self.reply(404, {'error': 'Not found'})
                return
            result = GAME.snapshot()
            result.update(TWITCH.status())
            self.reply(200, result)

def configure_runtime(credentials=None, live=False):
    """Wire capabilities only. Never connect or grant on startup/configuration."""
    global OAUTH, TWITCH, LIVE_ENABLED
    if live and credentials is None:
        raise LocalConfigError('Local credential configuration unavailable or invalid.')
    config = credentials.disabled_oauth_config() if credentials is not None else None
    if live:
        config = replace(config,enabled=True)  # Account, redirect and scope stay fixed.
    OAUTH = OAuthService(config=config,transport=StdlibOAuthHTTP(allow_network=live))
    if live:
        def worker_factory(game,lock,token_provider,approved):
            return EventSubTransport(game,lock,token_provider,approved=approved,
                socket_factory=WebSocketFactory(allow_network=True),helix=StdlibHelix(allow_network=True))
        TWITCH = TwitchController(GAME,LOCK,lambda:OAUTH,approved=True,worker_factory=worker_factory)
    else:
        TWITCH = TwitchController(GAME,LOCK,lambda:OAUTH)
    LIVE_ENABLED = live is True


def main(argv=None, workspace=None):
    """File loading is explicit and storage-only; default startup reads no secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    config_options = parser.add_mutually_exclusive_group()
    config_options.add_argument('--load-twitch-config', action='store_true',
        help='Explicitly load fixed local credentials into DISABLED OAuth memory; no live activation')
    config_options.add_argument('--check-twitch-config', action='store_true',
        help='Validate fixed local credential storage and exit without binding or network')
    config_options.add_argument('--enable-twitch', action='store_true',
        help='Explicit read-chat activation on localhost:8000; loads fixed protected credentials')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    if args.enable_twitch and args.port != 8000:
        print('Live Twitch requires exact http://localhost:8000.',file=sys.stderr)
        return 2
    credentials = None
    if args.load_twitch_config or args.check_twitch_config or args.enable_twitch:
        try:
            credentials = load_local_credentials(ROOT.parent if workspace is None else workspace)
        except LocalConfigError:
            print('Local credential configuration unavailable or invalid.', file=sys.stderr)
            return 2
        if args.check_twitch_config:
            print('Local credential storage valid. OAuth and all live gates remain disabled.')
            return 0
    configure_runtime(credentials,live=args.enable_twitch)
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            message = 'Local port is already in use. Check your own foreground server; no process was stopped.'
        elif error.errno in (errno.EACCES,errno.EPERM):
            message = 'Loopback startup denied. Stop and report the permission issue; do not bypass OS restrictions.'
        else:
            message = 'Local server could not start. Check the documented foreground Terminal setup.'
        print(message,file=sys.stderr)
        return 2
    print('Chat Mission Control: http://{}:{}'.format('localhost' if LIVE_ENABLED else '127.0.0.1',server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with LOCK:
            if TWITCH.worker:
                TWITCH.worker.stop()
        server.server_close()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
