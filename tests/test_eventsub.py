"""All socket/Helix/provider operations are injected fakes. No live connection."""
import copy
import json
import io
from urllib.error import HTTPError
import ssl
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch, Mock
from eventsub import (EventSubTransport, TwitchController, WebSocketFactory, LibrarySocket,
                      StdlibHelix, TransportFailure, Unauthorized, BASE_URL, safe_socket_url)
from oauth import OAuthService, OAuthConfig, OAuthFailure, TokenSnapshot
from game import Game
from test_twitch_adapter import notification as adapter_notification, NOW
from test_oauth import FakeProvider
import test_oauth as oauth_fixtures
import server


def notification(*args,**kwargs):
    event=adapter_notification(*args,**kwargs)
    event['payload']['subscription']['condition']['user_id']='101'
    return event

def message(kind,session=None):
    return json.dumps({'metadata':{'message_type':kind},'payload':{} if session is None else {'session':session}})

def welcome(sid='session-1'):
    return message('session_welcome',{'id':sid,'status':'connected','keepalive_timeout_seconds':10})

def reconnect(url=BASE_URL+'?reconnect=opaque',sid='session-1'):
    return message('session_reconnect',{'id':sid,'status':'reconnecting','reconnect_url':url})

class FakeSocket:
    def __init__(self,items=()): self.items,self.closed = list(items),False
    def receive(self):
        if not self.items: return None
        value = self.items.pop(0)
        if isinstance(value,Exception): raise value
        return value
    def close(self): self.closed=True

class FakeSockets:
    def __init__(self,sockets=()): self.sockets,self.urls = list(sockets),[]
    def __call__(self,url):
        self.urls.append(url)
        if not self.sockets: raise TransportFailure('PRIVATE_SOCKET_ERROR')
        value=self.sockets.pop(0)
        if isinstance(value,Exception): raise value
        return value

class FakeHelix:
    def __init__(self):
        self.lookups,self.subscriptions = [],[]
        self.lookup_result = (200,{'data':[{'id':'101','login':'balakrishnanayyanar'}]})
        self.subscribe_result = None
    def lookup(self,token):
        self.lookups.append(token.user_id)
        return copy.deepcopy(self.lookup_result)
    def subscribe(self,token,broadcaster,sid):
        self.subscriptions.append((broadcaster,token.user_id,sid))
        return copy.deepcopy(self.subscribe_result) if self.subscribe_result is not None else (202,{'data':[{
            'id':'subscription-1','status':'enabled','type':'channel.chat.message','version':'1',
            'condition':{'broadcaster_user_id':broadcaster,'user_id':token.user_id},
            'transport':{'method':'websocket','session_id':sid}}]})

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.now=[100.]
        self.lock=threading.RLock()
        self.game=Game(clock=lambda:0)
        self.game.start()
        self.token=TokenSnapshot('FAKE_ACCESS_NOT_REAL','fake-client','101',1000)
        self.socket=FakeSocket([welcome()])
        self.sockets=FakeSockets([self.socket])
        self.helix=FakeHelix()
        self.worker=EventSubTransport(self.game,self.lock,lambda:self.token,approved=True,
            socket_factory=self.sockets,helix=self.helix,clock=lambda:self.now[0],wall_clock=lambda:NOW)

    def start(self):
        self.worker.start(('session','http://localhost:8000'),threaded=False)
        self.worker.step()

    def test_disabled_and_missing_authorization_never_do_io(self):
        self.worker.approved=False
        with self.assertRaises(TransportFailure): self.start()
        self.worker.approved=True
        self.token=None
        with self.assertRaises(TransportFailure): self.start()
        self.assertEqual(self.sockets.urls,[])
        self.assertEqual(self.helix.lookups,[])
        with self.assertRaises(TransportFailure): WebSocketFactory()(BASE_URL)
        with self.assertRaises(TransportFailure): StdlibHelix().lookup(TokenSnapshot('fake','c','101',999))

    def test_welcome_verified_ack_then_notify_and_redaction(self):
        self.worker.start(('session','origin'),threaded=False)
        self.assertFalse(self.worker.status()['connected'])
        self.worker.step()
        self.assertTrue(self.worker.status()['connected'])
        self.assertEqual(self.helix.subscriptions,[('101','101','session-1')])
        self.socket.items.append(json.dumps(notification()))
        self.worker.step()
        self.assertEqual(self.game.votes,{'twitch:303':'supply'})
        self.assertIn('Twitch chat vote',self.game.events[-1]['message'])
        self.assertFalse(self.worker.status()['browser_votes_enabled'])
        self.assertNotIn(self.token.access,json.dumps(self.worker.status())+repr(self.token))

    def test_lookup_and_subscription_wrong_ids_never_connected(self):
        self.helix.lookup_result=(200,{'data':[{'id':'999','login':'balakrishnanayyanar'}]})
        self.start()
        self.assertFalse(self.worker.status()['connected'])
        self.assertEqual(self.worker.reason,'authorization required')
        self.assertEqual(self.sockets.urls,[])
        self.setUp()
        self.helix.subscribe_result=(202,{'data':[{'id':'s','status':'enabled','type':'channel.chat.message',
            'version':'1','condition':{'broadcaster_user_id':'999','user_id':'101'},
            'transport':{'method':'websocket','session_id':'session-1'}}]})
        self.start()
        self.assertFalse(self.worker.status()['connected'])
        self.assertFalse(self.worker.ever_verified)

    def test_no_ack_wrong_status_or_unauthorized_not_connected(self):
        for status in (200,401,403):
            self.setUp()
            self.helix.subscribe_result=(status,{'data':[]})
            self.start()
            self.assertFalse(self.worker.status()['connected'])
            if status in (401,403):
                self.assertFalse(self.worker._running)
                self.assertEqual(self.worker.reason,'authorization required')

    def test_keepalive_and_watchdog_fresh_resubscribe(self):
        self.start()
        self.now[0]+=9
        self.socket.items.append(message('session_keepalive'))
        self.worker.step()
        self.assertTrue(self.worker.status()['connected'])
        fresh=FakeSocket([welcome('fresh-session')])
        self.sockets.sockets.append(fresh)
        self.now[0]+=13
        self.worker.step()
        self.assertFalse(self.worker.status()['connected'])
        self.assertTrue(self.socket.closed)
        self.now[0]+=1
        self.worker.step()
        self.assertTrue(self.worker.status()['connected'])
        self.assertEqual(len(self.helix.subscriptions),2)

    def test_official_handover_no_resubscribe_and_dedup_restart(self):
        self.start()
        self.socket.items.append(json.dumps(notification()))
        self.worker.step()
        new=FakeSocket([welcome('replacement')])
        self.sockets.sockets.append(new)
        self.socket.items.append(reconnect())
        self.worker.step()
        self.assertFalse(self.socket.closed)
        self.assertTrue(self.worker.status()['connected'])
        self.worker.step()
        self.assertTrue(self.socket.closed)
        self.assertIs(self.worker.primary.socket,new)
        self.assertEqual(len(self.helix.subscriptions),1)
        self.game.restart();self.game.start()
        new.items.append(json.dumps(notification()))
        self.worker.step()
        self.assertEqual(self.game.votes,{})
        new.items.append(json.dumps(notification('n2','c2')))
        self.worker.step()
        self.assertEqual(self.game.votes,{'twitch:303':'supply'})

    def test_loss_retry_bounded_backoff_and_cancel(self):
        self.start()
        self.socket.items.append(TransportFailure('PRIVATE_FAILURE'))
        self.worker.step()
        self.assertFalse(self.worker.status()['connected'])
        attempts=len(self.sockets.urls)
        self.worker.step()
        self.assertEqual(len(self.sockets.urls),attempts)
        for _ in range(8):
            self.now[0]+=17
            self.worker.step()
        self.assertFalse(self.worker._running)
        self.assertEqual(self.worker.reason,'retry limit reached')
        self.assertNotIn('PRIVATE',json.dumps(self.worker.status()))
        self.assertFalse(self.worker.status()['browser_votes_enabled'])
        self.setUp();self.start();self.worker.stop();self.worker.step()
        self.assertTrue(self.socket.closed)
        self.assertFalse(self.worker._running)

    def test_revocation_and_expired_or_cleared_token_stop(self):
        self.start()
        sub={'type':'channel.chat.message','version':'1','condition':{'broadcaster_user_id':'101','user_id':'101'}}
        self.socket.items.append(json.dumps({'metadata':{'message_type':'revocation'},'payload':{'subscription':sub}}))
        self.worker.step()
        self.assertEqual(self.worker.reason,'authorization required')
        self.assertTrue(self.socket.closed)
        self.setUp();self.start()
        self.token=replace(self.token,expires=100)
        self.worker.step()
        self.assertFalse(self.worker._running)
        self.assertFalse(self.worker.status()['connected'])
        self.setUp();self.start()
        self.worker.token_provider=Mock(side_effect=OAuthFailure('PRIVATE'))
        self.worker.step()
        self.assertEqual(self.worker.reason,'authorization required')
        self.assertEqual(len(self.sockets.urls),1)

    def test_stale_ingress_round_and_wrong_channel_rejected(self):
        self.start()
        token=self.game.token
        self.game.advance(7)
        self.worker._message(self.worker.primary,json.dumps(notification()),self.token,token)
        self.assertEqual(self.game.votes,{})
        wrong=notification('n2','c2')
        wrong['payload']['event']['broadcaster_user_id']='999'
        self.socket.items.append(json.dumps(wrong))
        self.worker.step()
        self.assertEqual(self.game.votes,{})
        self.assertTrue(self.worker.status()['connected'])

    def test_invalid_reconnect_never_dials_untrusted_url(self):
        self.start()
        self.socket.items.append(reconnect('wss://evil.invalid/ws?reconnect=x'))
        self.worker.step()
        self.assertEqual(self.sockets.urls,[BASE_URL])
        self.assertFalse(self.worker.status()['connected'])

    def test_tls_url_allowlist_and_no_socket_auth_headers(self):
        self.assertTrue(safe_socket_url(BASE_URL))
        self.assertTrue(safe_socket_url(BASE_URL+'?reconnect=opaque',True))
        for url in ['ws://eventsub.wss.twitch.tv/ws',BASE_URL+'#fragment',
                    'wss://eventsub.wss.twitch.tv:444/ws','wss://evil.invalid/ws',
                    'wss://user:pass@eventsub.wss.twitch.tv/ws',BASE_URL+'/other',
                    BASE_URL+'?access_token=secret',BASE_URL+'?reconnect=x&access_token=secret',
                    BASE_URL+'?reconnect=x&reconnect=y',BASE_URL+'?reconnect=',BASE_URL+'\n']:
            self.assertFalse(safe_socket_url(url,True),url)
        with patch('websocket.create_connection') as dial:
            wrapped=WebSocketFactory(allow_network=True)(BASE_URL)
            args,kwargs=dial.call_args
            self.assertEqual(args,(BASE_URL,))
            self.assertEqual(kwargs['sslopt']['cert_reqs'],ssl.CERT_REQUIRED)
            self.assertTrue(kwargs['sslopt']['check_hostname'])
            self.assertTrue(kwargs['sslopt']['context'].check_hostname)
            self.assertNotIn('header',kwargs)
            self.assertIsInstance(wrapped,LibrarySocket)

    def test_mock_helix_http_exact_subscription_and_unauthorized(self):
        class Response(io.BytesIO):
            status=202
        body={'data':[]}
        with patch('eventsub.build_opener') as factory:
            factory.return_value.open.return_value=Response(json.dumps(body).encode())
            status,result=StdlibHelix(allow_network=True).subscribe(self.token,'101','session-1')
            request=factory.return_value.open.call_args.args[0]
            self.assertEqual(status,202)
            self.assertEqual(result,body)
            self.assertEqual(request.full_url,'https://api.twitch.tv/helix/eventsub/subscriptions')
            self.assertEqual(json.loads(request.data),{'type':'channel.chat.message','version':'1',
                'condition':{'broadcaster_user_id':'101','user_id':'101'},
                'transport':{'method':'websocket','session_id':'session-1'}})
            self.assertEqual(request.get_header('Authorization'),'Bearer '+self.token.access)
        with patch('eventsub.build_opener') as factory:
            factory.return_value.open.side_effect=HTTPError('https://api.twitch.tv',401,'PRIVATE',{},None)
            with self.assertRaises(Unauthorized) as caught:
                StdlibHelix(allow_network=True).lookup(self.token)
            self.assertNotIn('PRIVATE',str(caught.exception))

    def test_stop_during_subscription_cannot_mark_connected(self):
        original=self.helix.subscribe
        def stop_then_ack(*args):
            self.worker.stop()
            return original(*args)
        self.helix.subscribe=stop_then_ack
        self.start()
        self.assertFalse(self.worker.status()['connected'])
        self.assertFalse(self.worker.ever_verified)
        self.assertTrue(self.socket.closed)

    def test_library_protocol_ping_pong_and_close(self):
        import websocket
        connection=Mock()
        connection.recv_data.side_effect=[(websocket.ABNF.OPCODE_PING,b'p'),
            (websocket.ABNF.OPCODE_PONG,b'p'),(websocket.ABNF.OPCODE_TEXT,b'{}'),
            (websocket.ABNF.OPCODE_CLOSE,b'')]
        wrapper=LibrarySocket(connection,websocket)
        self.assertIsNone(wrapper.receive());self.assertIsNone(wrapper.receive())
        self.assertEqual(wrapper.receive(),b'{}')
        with self.assertRaises(TransportFailure):wrapper.receive()
        connection.recv_data.assert_called_with(control_frame=True)

class ControllerHTTPTests(unittest.TestCase):
    exchange=oauth_fixtures.OAuthHTTPTests.exchange
    session=oauth_fixtures.OAuthHTTPTests.session
    begin=oauth_fixtures.OAuthHTTPTests.begin

    def setUp(self):
        self.old_oauth,self.old_twitch=server.OAUTH,server.TWITCH
        self.addCleanup(setattr,server,'OAUTH',self.old_oauth)
        self.addCleanup(setattr,server,'TWITCH',self.old_twitch)
        self.game=Game(clock=lambda:0)
        provider=FakeProvider()
        service=OAuthService(OAuthConfig(True,'fake-client','FAKE_SECRET_NOT_REAL'),provider,clock=lambda:100)
        server.OAUTH=service
        self.cookie,self.csrf=self.session()
        state=self.begin(self.cookie,self.csrf)
        service.callback(self.cookie.split('=',1)[1],'http://localhost:8000',state,'FAKE_CODE')
        self.fake_socket=FakeSocket([welcome()])
        self.helix=FakeHelix()
        self.sockets=FakeSockets([self.fake_socket])
        outer=self
        class ManualWorker(EventSubTransport):
            def start(self,owner,threaded=False):return super().start(owner,threaded=False)
        def factory(game,lock,token_provider,approved):
            return ManualWorker(game,lock,token_provider,approved=approved,socket_factory=outer.sockets,
                helix=outer.helix,clock=lambda:100,wall_clock=lambda:NOW)
        server.TWITCH=TwitchController(self.game,server.LOCK,lambda:server.OAUTH,worker_factory=factory)

    def post(self,path,**kwargs):
        return self.exchange(path,{},cookie=self.cookie,csrf=self.csrf,**kwargs)

    def test_guarded_connect_csrf_origin_status_and_browser_vote_block(self):
        self.assertEqual(self.post('/api/twitch/connect',origin='http://localhost:8000')[0],403)
        server.TWITCH.approved=True
        self.assertEqual(self.post('/api/twitch/connect')[0],403)
        self.assertEqual(self.exchange('/api/twitch/connect',{},origin='http://localhost:8000')[0],403)
        self.assertEqual(self.post('/api/twitch/connect',origin='http://localhost:8000')[0],200)
        self.assertFalse(server.TWITCH.status()['connected'])
        server.TWITCH.worker.step()
        status=json.loads(self.exchange('/api/twitch/status',cookie=self.cookie)[2])
        self.assertTrue(status['connected'])
        self.assertNotIn('FAKE_ACCESS_NOT_REAL',json.dumps(status))
        result=json.loads(self.exchange('/api/state')[2])
        self.assertFalse(result['browser_votes_enabled'])
        self.assertEqual(self.exchange('/api/vote',{'viewer':'a','option':'north','token':'x'})[0],409)
        self.assertEqual(self.post('/api/twitch/disconnect')[0],403)
        self.assertEqual(self.post('/api/twitch/disconnect',origin='http://localhost:8000')[0],200)
        self.assertFalse(server.TWITCH.status()['connected'])
        self.assertFalse(server.TWITCH.status()['browser_votes_enabled'])

    def test_safe_oauth_snapshot_and_local_logout_stops_worker(self):
        sid=self.cookie.split('=',1)[1]
        snapshot=server.OAUTH.authenticated_token(sid,'http://localhost:8000')
        self.assertEqual(snapshot.scopes,('user:read:chat',))
        self.assertNotIn(snapshot.access,repr(snapshot))
        server.TWITCH.approved=True
        self.post('/api/twitch/connect',origin='http://localhost:8000')
        server.TWITCH.worker.step()
        self.assertEqual(self.post('/auth/twitch/disconnect',origin='http://localhost:8000')[0],200)
        self.assertFalse(server.TWITCH.status()['connected'])
        with self.assertRaises(OAuthFailure):server.OAUTH.authenticated_token(sid,'http://localhost:8000')

if __name__ == '__main__':unittest.main()
