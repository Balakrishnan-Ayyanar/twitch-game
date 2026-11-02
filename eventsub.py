"""Guarded Twitch EventSub worker. Defaults perform no network/credential reads.

All external I/O is injectable. One worker owns its sockets; an official reconnect
may temporarily use an old socket and candidate socket in this same worker.
"""
from collections import deque
from dataclasses import dataclass
import hashlib
import json
import ssl
import threading
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener
from urllib.error import HTTPError
from oauth import SCOPES, TokenSnapshot, _NoRedirect
from twitch_adapter import TwitchAdapter, valid_user_id, valid_message_id

BASE_URL = 'wss://eventsub.wss.twitch.tv/ws'

class TransportFailure(Exception):
    pass

class Unauthorized(TransportFailure):
    pass


def safe_socket_url(url, reconnect=False):
    if not isinstance(url,str) or len(url) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'wss' or parsed.hostname != 'eventsub.wss.twitch.tv' or
                parsed.netloc not in ('eventsub.wss.twitch.tv','eventsub.wss.twitch.tv:443') or
                parsed.path != '/ws' or parsed.fragment or parsed.username or parsed.password or
                parsed.port not in (None,443)):
            return False
        if not parsed.query:
            return not reconnect
        query = parse_qs(parsed.query,keep_blank_values=True,strict_parsing=True,max_num_fields=2)
        if reconnect:
            return set(query) == {'reconnect'} and len(query['reconnect']) == 1 and bool(query['reconnect'][0])
        return not parsed.query
    except ValueError:
        return False

class LibrarySocket:
    """websocket-client handles protocol ping/pong in recv_data; TLS stays verified."""
    def __init__(self, connection, library):
        self.connection, self.library = connection, library

    def receive(self):
        try:
            opcode,data = self.connection.recv_data(control_frame=True)
        except self.library.WebSocketTimeoutException:
            return None
        if opcode == self.library.ABNF.OPCODE_CLOSE:
            raise TransportFailure('Socket closed.')
        if opcode in (self.library.ABNF.OPCODE_PING,self.library.ABNF.OPCODE_PONG):
            return None  # recv_data has already sent automatic protocol pong.
        if opcode != self.library.ABNF.OPCODE_TEXT:
            raise TransportFailure('Unexpected socket frame.')
        return data

    def close(self):
        self.connection.close(timeout=1)

class WebSocketFactory:
    def __init__(self, allow_network=False):
        self.allow_network = allow_network

    def __call__(self,url):
        if not self.allow_network or not (safe_socket_url(url) or safe_socket_url(url,True)):
            raise TransportFailure('Socket disabled or URL rejected.')
        import websocket  # Approved pinned dependency; no import/connection at server startup.
        context = ssl.create_default_context()
        connection = websocket.create_connection(url,timeout=1,enable_multithread=True,
            sslopt={'context':context,'cert_reqs':ssl.CERT_REQUIRED,'check_hostname':True},
            suppress_origin=True,http_no_proxy=['eventsub.wss.twitch.tv'])
        return LibrarySocket(connection,websocket)

class StdlibHelix:
    def __init__(self, allow_network=False):
        self.allow_network = allow_network

    def _request(self,path,token,body=None):
        if not self.allow_network:
            raise TransportFailure('Helix disabled.')
        data = None if body is None else json.dumps(body).encode()
        req = Request('https://api.twitch.tv/helix/'+path,data=data,headers={
            'Client-Id':token.client_id,'Authorization':'Bearer '+token.access,
            'Content-Type':'application/json'})
        try:
            with build_opener(_NoRedirect()).open(req,timeout=10) as response:
                raw = response.read(65537)
                status = response.status
            if len(raw) > 65536:
                raise ValueError()
            return status,json.loads(raw)
        except HTTPError as exc:
            if exc.code in (401,403):
                raise Unauthorized('Authorization rejected.') from None
            raise TransportFailure('Helix request failed.') from None
        except Exception:
            raise TransportFailure('Helix request failed.') from None

    def lookup(self,token):
        return self._request('users?login=balakrishnanayyanar',token)

    def subscribe(self,token,broadcaster_id,session_id):
        return self._request('eventsub/subscriptions',token,{
            'type':'channel.chat.message','version':'1',
            'condition':{'broadcaster_user_id':broadcaster_id,'user_id':token.user_id},
            'transport':{'method':'websocket','session_id':session_id}})

@dataclass
class Link:
    socket: object
    deadline: float
    session_id: str = ''
    keepalive: int = 10

class EventSubTransport:
    MAX_RETRIES = 5

    def __init__(self, game, lock, token_provider, approved=False, socket_factory=None,
                 helix=None, clock=time.monotonic, wall_clock=time.time):
        self.game, self.lock, self.token_provider = game,lock,token_provider
        self.approved = approved
        self.socket_factory = socket_factory or WebSocketFactory()
        self.helix = helix or StdlibHelix()
        self.clock, self.wall_clock = clock,wall_clock
        self.stop_event = threading.Event()
        self.thread = None
        self.primary = self.candidate = None
        self.adapter = None
        self._identity = None
        self._connected = False
        self.ever_verified = False
        self.reason = 'disabled'
        self.retry_count = 0
        self.next_attempt = 0
        self.owner = None
        self._running = False
        self.subscription_acks = 0
        self.validated_notifications = 0
        self.accepted_votes = 0
        self.receipts = deque(maxlen=12)

    def status(self):
        with self.lock:
            if self._connected:
                try:
                    self._credential()  # Local memory only; never provider validation I/O.
                except Unauthorized:
                    self.stop('authorization required')
            stopping = bool(self.thread and self.thread.is_alive() and self.stop_event.is_set())
            return {'connected':self._connected,'transport_enabled':self.approved is True,
                    'transport_status':self.reason,'transport_stopping':stopping,
                    'can_connect':bool(self.approved and not self._running and not stopping and
                                       self.reason != 'authorization required'),
                    'retry_count':min(self.retry_count,self.MAX_RETRIES),'retry_limit':self.MAX_RETRIES,
                    'retry_in_seconds':round(max(0,self.next_attempt-self.clock()),1) if self.reason == 'reconnecting' else 0,
                    'subscription_acks':self.subscription_acks,
                    'validated_notifications':self.validated_notifications,'accepted_votes':self.accepted_votes,
                    'receipt_scope':'Current server process; retained across mission restart and reconnect.',
                    'receipts':[dict(receipt,age_seconds=round(max(0,self.clock()-stamp),1)) for stamp,receipt in self.receipts],
                    'browser_votes_enabled':not self.ever_verified,
                    'mode':('TWITCH CHAT CONNECTED' if self._connected else
                            'TWITCH DISCONNECTED — simulated votes disabled' if self.ever_verified else
                            'SIMULATED CHAT — Twitch disconnected')}

    def _credential(self):
        try:
            with self.lock:
                token = self.token_provider()
        except Exception:
            raise Unauthorized('Authorization unavailable.') from None
        if (not isinstance(token,TokenSnapshot) or token.scopes != SCOPES or
                not valid_user_id(token.user_id) or not isinstance(token.access,str) or
                not token.access or token.expires <= self.clock()):
            raise Unauthorized('Authorization unavailable.')
        identity = (token.client_id,token.user_id,hashlib.sha256(token.access.encode()).digest())
        if self._identity is not None and self._identity != identity:
            raise Unauthorized('Authorization changed.')
        return token,identity

    def start(self, owner, threaded=True):
        with self.lock:
            if self.approved is not True or self._running or (self.thread and self.thread.is_alive()):
                raise TransportFailure('Transport disabled or already active.')
            try:
                _,identity = self._credential()
            except Exception:
                raise TransportFailure('Authorization unavailable.') from None
            self._identity = identity
            self.owner = owner
            self.stop_event.clear()
            self._running = True
            self.retry_count = 0
            self.next_attempt = self.clock()
            self.reason = 'connecting'
            if threaded:
                self.thread = threading.Thread(target=self._run,daemon=True,name='eventsub-local')
                self.thread.start()
        return self.status()

    def stop(self, reason='stopped'):
        # No join under the game lock. The worker owns closure and checks stop after I/O.
        with self.lock:
            self.stop_event.set()
            self._connected = False
            self.reason = reason
            self.owner = None
            self._identity = None
        if not self.thread or not self.thread.is_alive():
            self._close_all()
            self._running = False

    def _close(self,link):
        if link:
            try:
                link.socket.close()
            except Exception:
                pass

    def _close_all(self):
        self._close(self.primary)
        self._close(self.candidate)
        self.primary = self.candidate = None

    def _retry(self):
        with self.lock:
            self._connected = False
        self._close_all()
        with self.lock:
            self.retry_count += 1
            if self.retry_count > self.MAX_RETRIES:
                self.stop('retry limit reached')
                return
            self.next_attempt = self.clock()+min(16,2**(self.retry_count-1))
            self.reason = 'reconnecting'

    def _open(self,url):
        if self.stop_event.is_set():
            raise TransportFailure('Stopped.')
        socket = self.socket_factory(url)
        if self.stop_event.is_set():
            self._close(Link(socket,0))
            raise TransportFailure('Stopped.')
        return Link(socket,self.clock()+10)

    def _verify_lookup(self,token):
        status,body = self.helix.lookup(token)
        if status in (401,403):
            raise Unauthorized('Authorization rejected.')
        data = body.get('data') if isinstance(body,dict) else None
        if (status != 200 or not isinstance(data,list) or len(data) != 1 or
                not isinstance(data[0],dict) or data[0].get('login') != 'balakrishnanayyanar' or
                not valid_user_id(data[0].get('id')) or data[0]['id'] != token.user_id):
            raise Unauthorized('Broadcaster verification failed.')
        if self.adapter is None:
            self.adapter = TwitchAdapter(self.game,data[0]['id'],token.user_id,clock=self.wall_clock)
            self.adapter.source = 'twitch'
        elif self.adapter.broadcaster_id != data[0]['id'] or self.adapter.user_id != token.user_id:
            raise Unauthorized('Broadcaster changed.')

    def _subscribe(self,token,session_id):
        status,body = self.helix.subscribe(token,self.adapter.broadcaster_id,session_id)
        if status in (401,403):
            raise Unauthorized('Authorization rejected.')
        data = body.get('data') if isinstance(body,dict) else None
        if status != 202 or not isinstance(data,list) or len(data) != 1 or not isinstance(data[0],dict):
            raise TransportFailure('Subscription not acknowledged.')
        sub = data[0]
        if (sub.get('type') != 'channel.chat.message' or sub.get('version') != '1' or
                sub.get('status') != 'enabled' or not valid_message_id(sub.get('id')) or
                sub.get('condition') != {'broadcaster_user_id':self.adapter.broadcaster_id,'user_id':token.user_id} or
                not isinstance(sub.get('transport'),dict) or sub['transport'].get('method') != 'websocket' or
                sub['transport'].get('session_id') != session_id):
            raise TransportFailure('Subscription response mismatch.')

    def _message(self,link,raw,token,ingress_token):
        if not isinstance(raw,(str,bytes)) or len(raw) > 65536:
            raise TransportFailure('Invalid message.')
        try:
            message = json.loads(raw)
        except (ValueError,UnicodeError):
            raise TransportFailure('Invalid message.') from None
        if not isinstance(message,dict) or not isinstance(message.get('metadata'),dict) or not isinstance(message.get('payload'),dict):
            raise TransportFailure('Invalid envelope.')
        kind = message['metadata'].get('message_type')
        payload = message['payload']
        if kind == 'session_welcome':
            session = payload.get('session')
            if (link.session_id or not isinstance(session,dict) or not valid_message_id(session.get('id')) or
                    session.get('status') != 'connected' or
                    not isinstance(session.get('keepalive_timeout_seconds'),int) or
                    isinstance(session['keepalive_timeout_seconds'],bool) or
                    not 1 <= session['keepalive_timeout_seconds'] <= 600):
                raise TransportFailure('Invalid welcome.')
            link.session_id = session['id']
            link.keepalive = session['keepalive_timeout_seconds']
            handover = link is self.candidate
            if handover:
                old = self.primary
                self.primary, self.candidate = link,None
                self._close(old)  # Official handover transfers subscriptions; no duplicate POST.
            else:
                self._subscribe(token,link.session_id)
            self._credential()  # Re-check authorization after blocking HTTP.
            with self.lock:
                if self.stop_event.is_set():
                    return
                self._connected = self.ever_verified = True
                if not handover:
                    self.subscription_acks += 1
                self.reason = 'connected'
        elif not link.session_id:
            raise TransportFailure('Welcome required.')
        elif kind == 'session_keepalive':
            pass
        elif kind == 'session_reconnect':
            session = payload.get('session')
            if (link is not self.primary or not isinstance(session,dict) or session.get('id') != link.session_id or
                    session.get('status') != 'reconnecting' or not safe_socket_url(session.get('reconnect_url'),True)):
                raise TransportFailure('Invalid reconnect.')
            if not self.candidate:
                self.candidate = self._open(session['reconnect_url'])
        elif kind == 'notification':
            with self.lock:
                if self._connected and not self.stop_event.is_set():
                    self._credential()
                    self.game.tick()
                    self.adapter.accept_notification(message,ingress_token)
                    if self.adapter.last_receipt is not None:
                        self.validated_notifications += 1
                        receipt = dict(self.adapter.last_receipt)
                        if receipt['outcome'] == 'accepted':
                            self.accepted_votes += 1
                        self.receipts.append((self.clock(),receipt))
        elif kind == 'revocation':
            sub = payload.get('subscription')
            if (isinstance(sub,dict) and sub.get('type') == 'channel.chat.message' and sub.get('version') == '1' and
                    sub.get('condition') == {'broadcaster_user_id':self.adapter.broadcaster_id,'user_id':token.user_id}):
                raise Unauthorized('Subscription revoked.')
            raise TransportFailure('Invalid revocation.')
        else:
            raise TransportFailure('Unexpected message.')
        link.deadline = self.clock()+link.keepalive+2

    def step(self):
        """One bounded worker iteration; tests call directly with fake I/O/clock."""
        if not self._running:
            return
        if self.stop_event.is_set():
            self._close_all()
            self._running = False
            return
        try:
            token, _ = self._credential()
            if self.primary is None:
                if self.clock() < self.next_attempt:
                    return
                self._verify_lookup(token)
                self.primary = self._open(BASE_URL)
            for link in (self.primary,self.candidate):
                if link is None or self.stop_event.is_set():
                    continue
                if self.clock() >= link.deadline:
                    raise TransportFailure('Watchdog expired.')
                raw = link.socket.receive()
                # No application queue: capture round and dispatch immediately under game lock.
                if raw is not None and not self.stop_event.is_set():
                    with self.lock:
                        self.game.tick()
                        ingress_token = self.game.token
                    self._message(link,raw,token,ingress_token)
                if self.clock() >= link.deadline:
                    raise TransportFailure('Watchdog expired.')
        except Unauthorized:
            self.stop('authorization required')
            self._close_all()
            self._running = False
        except Exception:
            if not self.stop_event.is_set():
                self._retry()
        if self.stop_event.is_set():
            self._close_all()
            self._running = False

    def _run(self):
        try:
            while self._running and not self.stop_event.is_set():
                self.step()
                self.stop_event.wait(.05)  # Cancelable, never an unbounded backoff sleep.
        finally:
            self._close_all()
            with self.lock:
                self._connected = False
                self._running = False
                if self.reason in ('connected','connecting','reconnecting'):
                    self.reason = 'worker stopped'

class TwitchController:
    """Single operator-owned worker, activated by protected local POST only."""
    def __init__(self,game,lock,oauth_provider,approved=False,worker_factory=EventSubTransport):
        self.game,self.lock,self.oauth_provider = game,lock,oauth_provider
        self.approved,self.worker_factory = approved,worker_factory
        self.worker = None

    def status(self):
        if self.worker:
            return self.worker.status()
        return {'connected':False,'transport_enabled':self.approved is True,'transport_status':'disabled',
                'transport_stopping':False,'can_connect':self.approved is True,
                'retry_count':0,'retry_limit':EventSubTransport.MAX_RETRIES,'retry_in_seconds':0,
                'subscription_acks':0,'validated_notifications':0,'accepted_votes':0,'receipts':[],
                'receipt_scope':'Current server process; retained across mission restart and reconnect.',
                'browser_votes_enabled':True,'mode':'SIMULATED CHAT — Twitch disconnected'}

    def connect(self,sid,origin,csrf):
        oauth = self.oauth_provider()
        oauth.require_csrf(sid,origin,csrf)
        if origin != 'http://localhost:8000' or self.approved is not True:
            raise TransportFailure('Transport disabled.')
        oauth.authenticated_token(sid,origin)
        if self.worker is None:
            self.worker = self.worker_factory(self.game,self.lock,
                lambda:self.oauth_provider().authenticated_token(sid,origin),approved=True)
        elif self.worker.owner not in (None,(sid,origin)):
            raise TransportFailure('Transport owned by another session.')
        else:
            self.worker.token_provider = lambda:self.oauth_provider().authenticated_token(sid,origin)
        return self.worker.start((sid,origin))

    def disconnect(self,sid,origin,csrf):
        self.oauth_provider().require_csrf(sid,origin,csrf)
        if self.worker:
            if self.worker.owner not in (None,(sid,origin)):
                raise TransportFailure('Transport owned by another session.')
            self.worker.stop()
        return self.status()
