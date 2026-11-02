"""Disabled-by-default, in-memory local confidential OAuth preparation.

No environment/files are read. No transport is called until explicit configured
opt-in and a session-bound POST start followed by a valid callback. Server caller
must hold its lock. Tokens never belong in HTTP responses or diagnostic logs.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from twitch_adapter import valid_user_id

REDIRECT = 'http://localhost:8000/auth/twitch/callback'
SCOPES = ('user:read:chat',)

@dataclass(frozen=True)
class OAuthConfig:
    enabled: bool = False
    client_id: str = field(default='', repr=False)
    client_secret: str = field(default='', repr=False)
    redirect: str = REDIRECT
    expected_login: str = 'balakrishnanayyanar'

class OAuthFailure(Exception):
    """Sanitized failure only; never carry provider payloads, codes or tokens."""

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class StdlibOAuthHTTP:
    """Future HTTPS token transport; separate explicit network gate, off by default."""
    def __init__(self, allow_network=False):
        self.allow_network = allow_network

    def _json(self, request):
        if not self.allow_network:
            raise OAuthFailure('OAuth transport disabled.')
        try:
            with build_opener(_NoRedirect()).open(request, timeout=10) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError()
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except Exception:
            raise OAuthFailure('OAuth provider request failed.') from None

    def exchange(self, config, code):
        body = urlencode({'client_id': config.client_id, 'client_secret': config.client_secret,
                          'code': code, 'grant_type': 'authorization_code',
                          'redirect_uri': config.redirect}).encode()
        return self._json(Request('https://id.twitch.tv/oauth2/token', data=body,
                                  headers={'Content-Type':'application/x-www-form-urlencoded'}))

    def validate(self, token):
        return self._json(Request('https://id.twitch.tv/oauth2/validate',
                                 headers={'Authorization':'OAuth '+token}))

@dataclass(frozen=True)
class TokenSnapshot:
    """Backend-only capability. Never serialize into status, game state or logs."""
    access: str = field(repr=False)
    client_id: str
    user_id: str
    expires: float
    scopes: tuple = SCOPES

class OAuthService:
    SESSION_TTL = 1800
    STATE_TTL = 300
    LIMIT = 128

    def __init__(self, config=None, transport=None, clock=time.monotonic):
        self.config = config or OAuthConfig()
        self.transport = transport or StdlibOAuthHTTP()
        self.clock = clock
        self._sessions = OrderedDict()
        self._states = OrderedDict()

    def configured(self):
        c = self.config
        return (c.enabled is True and isinstance(c.client_id,str) and 0 < len(c.client_id) <= 256
                and isinstance(c.client_secret,str) and 0 < len(c.client_secret) <= 1024
                and c.redirect == REDIRECT and c.expected_login == 'balakrishnanayyanar')

    def ready(self):
        # A real transport has an additional opt-in; injected test transports do not perform I/O.
        return bool(self.configured() and (not isinstance(self.transport, StdlibOAuthHTTP)
                                          or self.transport.allow_network is True))

    def _binding(self):
        c = self.config
        return hashlib.sha256(json.dumps([c.enabled,c.client_id,c.client_secret,c.redirect,
                                          c.expected_login,SCOPES]).encode()).digest()

    def _prune(self):
        now = self.clock()
        for key,value in list(self._sessions.items()):
            if value['expires'] <= now:
                del self._sessions[key]
        for key,value in list(self._states.items()):
            if value['expires'] <= now or value['sid'] not in self._sessions:
                del self._states[key]

    def session(self, sid, origin, create=False):
        self._prune()
        record = self._sessions.get(sid) if isinstance(sid,str) else None
        if record and record['origin'] == origin:
            return sid,record,False
        if not create:
            raise OAuthFailure('Invalid local session.')
        sid = secrets.token_urlsafe(32)
        record = {'origin':origin,'csrf':secrets.token_urlsafe(32),
                  'expires':self.clock()+self.SESSION_TTL,'tokens':None}
        self._sessions[sid] = record
        while len(self._sessions) > self.LIMIT:
            self._sessions.popitem(last=False)
        return sid,record,True

    def status(self, sid, origin):
        sid,record,new = self.session(sid,origin,create=True)
        tokens = record['tokens']
        if tokens and (tokens['expires'] <= self.clock() or tokens['binding'] != self._binding() or not self.ready()):
            record['tokens'] = None
        return sid,new,{'ready':self.ready() and origin == 'http://localhost:8000',
                        'oauth_enabled':self.config.enabled is True,
                        'authenticated':record['tokens'] is not None,
                        'connected':False,'mode':'SIMULATED CHAT — Twitch disconnected',
                        'requested_scope':'user:read:chat','expected_login':'balakrishnanayyanar',
                        'csrf':record['csrf'],'authorization_origin':'http://localhost:8000'}

    def require_csrf(self, sid, origin, csrf):
        _,record,_ = self.session(sid,origin)
        if not isinstance(csrf,str) or not csrf.isascii() or not secrets.compare_digest(record['csrf'],csrf):
            raise OAuthFailure('Invalid request verification.')
        return record

    def start(self, sid, origin, csrf):
        self.require_csrf(sid,origin,csrf)
        if origin != 'http://localhost:8000' or not self.ready():
            raise OAuthFailure('OAuth is disabled or not configured for this origin.')
        # Only one pending attempt per session; starting again invalidates the old state.
        for key,value in list(self._states.items()):
            if value['sid'] == sid:
                del self._states[key]
        state = secrets.token_urlsafe(32)
        self._states[state] = {'sid':sid,'expires':self.clock()+self.STATE_TTL,
                               'binding':self._binding(),'origin':origin}
        while len(self._states) > self.LIMIT:
            self._states.popitem(last=False)
        return {'authorization_url':'https://id.twitch.tv/oauth2/authorize?'+urlencode({
            'client_id':self.config.client_id,'redirect_uri':self.config.redirect,
            'response_type':'code','scope':' '.join(SCOPES),'state':state})}

    def callback(self, sid, origin, state, code=None, error=None):
        self.session(sid,origin)
        if not isinstance(state,str) or len(state) > 128:
            raise OAuthFailure('Invalid or expired authorization attempt.')
        attempt = self._states.get(state)
        if not attempt or attempt['sid'] != sid or attempt['origin'] != origin:
            raise OAuthFailure('Invalid or expired authorization attempt.')
        del self._states[state]  # Single use, including provider denial/exchange failure.
        if (not self.ready() or attempt['binding'] != self._binding() or
                origin != 'http://localhost:8000'):
            raise OAuthFailure('Invalid or expired authorization attempt.')
        if error is not None or not isinstance(code,str) or not 1 <= len(code) <= 4096:
            raise OAuthFailure('Authorization was not completed.')
        try:
            result = self.transport.exchange(self.config,code)
            if not isinstance(result,dict):
                raise ValueError()
            token = result.get('access_token')
            refresh = result.get('refresh_token')
            if (not isinstance(token,str) or not 1 <= len(token) <= 4096 or
                    result.get('token_type','').lower() != 'bearer' or
                    result.get('scope') != list(SCOPES) or
                    not isinstance(result.get('expires_in'),int) or isinstance(result['expires_in'],bool) or
                    result['expires_in'] <= 0 or
                    (refresh is not None and (not isinstance(refresh,str) or not 1 <= len(refresh) <= 4096))):
                raise ValueError()
            identity = self.transport.validate(token)
            if (not isinstance(identity,dict) or identity.get('client_id') != self.config.client_id or
                    identity.get('login') != self.config.expected_login or
                    not valid_user_id(identity.get('user_id')) or identity.get('scopes') != list(SCOPES) or
                    not isinstance(identity.get('expires_in'),int) or isinstance(identity['expires_in'],bool) or
                    identity['expires_in'] <= 0):
                raise ValueError()
            self._sessions[sid]['tokens'] = {'access':token,'refresh':refresh,
                'user_id':identity['user_id'],'expires':self.clock()+min(result['expires_in'],identity['expires_in']),
                'binding':self._binding()}
        except Exception:
            raise OAuthFailure('Authorization exchange or validation failed.') from None
        return {'authenticated':True,'connected':False,'mode':'SIMULATED CHAT — Twitch disconnected'}

    def authenticated_token(self, sid, origin):
        """Caller holds game lock; revalidate session/config/expiry on every access."""
        self.session(sid,origin)
        self.status(sid,origin)
        _,record,_ = self.session(sid,origin)
        tokens = record['tokens']
        if not tokens or not self.ready():
            raise OAuthFailure('Local authorization unavailable.')
        return TokenSnapshot(tokens['access'],self.config.client_id,tokens['user_id'],tokens['expires'])

    def disconnect(self, sid, origin, csrf):
        record = self.require_csrf(sid,origin,csrf)
        record['tokens'] = None
        record['csrf'] = secrets.token_urlsafe(32)
        for key,value in list(self._states.items()):
            if value['sid'] == sid:
                del self._states[key]
        return {'authenticated':False,'connected':False,'message':'Local authorization cleared; no remote revocation performed.'}
