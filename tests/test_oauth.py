"""Mocked OAuth only: no browser navigation, credentials, sockets or network."""
import copy
import io
import json
from contextlib import redirect_stderr
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from oauth import OAuthConfig, OAuthFailure, OAuthService, REDIRECT, StdlibOAuthHTTP
import server

class FakeProvider:
    def __init__(self):
        self.exchanges, self.validations = [], []
        self.result = {'access_token':'FAKE_ACCESS_NOT_REAL','refresh_token':'FAKE_REFRESH_NOT_REAL',
                       'token_type':'bearer','scope':['user:read:chat'],'expires_in':3600}
        self.identity = {'client_id':'fake-client','user_id':'101','login':'balakrishnanayyanar',
                         'scopes':['user:read:chat'],'expires_in':3500}
        self.fail = False

    def exchange(self, config, code):
        self.exchanges.append(code)
        if self.fail:
            raise RuntimeError('PRIVATE_PROVIDER_ERROR_FAKE_ACCESS_NOT_REAL')
        return copy.deepcopy(self.result)

    def validate(self, token):
        self.validations.append(token)
        return copy.deepcopy(self.identity)

class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.provider = FakeProvider()
        self.config = OAuthConfig(True,'fake-client','FAKE_SECRET_NOT_REAL')
        self.service = OAuthService(self.config,self.provider,clock=lambda:self.now[0])
        self.origin = 'http://localhost:8000'
        self.sid,_,self.status = self.service.status(None,self.origin)
        self.csrf = self.status['csrf']

    def start(self, sid=None, csrf=None):
        result = self.service.start(sid or self.sid,self.origin,csrf or self.csrf)
        parsed = urlsplit(result['authorization_url'])
        self.assertEqual(parsed.netloc,'id.twitch.tv')
        params = parse_qs(parsed.query)
        self.assertEqual(params['scope'],['user:read:chat'])
        self.assertEqual(params['redirect_uri'],[REDIRECT])
        self.assertEqual(params['response_type'],['code'])
        return params['state'][0]

    def test_default_disabled_missing_config_and_network_gate(self):
        for config in (OAuthConfig(),OAuthConfig(True),replace(self.config,enabled=False),
                       replace(self.config,client_secret=''),replace(self.config,redirect='http://evil.invalid')):
            service = OAuthService(config,self.provider)
            sid,_,status = service.status(None,self.origin)
            self.assertFalse(status['ready'])
            with self.assertRaises(OAuthFailure):
                service.start(sid,self.origin,status['csrf'])
        gated = OAuthService(self.config)
        self.assertFalse(gated.ready())
        with patch('oauth.build_opener',side_effect=AssertionError('Network forbidden')) as open_mock:
            with self.assertRaises(OAuthFailure):
                StdlibOAuthHTTP().exchange(self.config,'fake-code')
            open_mock.assert_not_called()
        self.assertEqual(self.provider.exchanges,[])

    def test_stdlib_exchange_and_validation_with_injected_mock_http(self):
        # Even the explicit network gate here is test-only: all HTTP is intercepted.
        transport = StdlibOAuthHTTP(allow_network=True)
        self.service.transport = transport
        state = self.start()
        responses = [io.BytesIO(json.dumps(self.provider.result).encode()),
                     io.BytesIO(json.dumps(self.provider.identity).encode())]
        with patch('oauth.build_opener') as factory:
            factory.return_value.open.side_effect = responses
            result = self.service.callback(self.sid,self.origin,state,'FAKE_CODE_NOT_REAL')
            calls = factory.return_value.open.call_args_list
        self.assertTrue(result['authenticated'])
        self.assertEqual(len(calls),2)
        token_request = calls[0].args[0]
        self.assertEqual(token_request.full_url,'https://id.twitch.tv/oauth2/token')
        form = parse_qs(token_request.data.decode())
        self.assertEqual(form['grant_type'],['authorization_code'])
        self.assertEqual(form['redirect_uri'],[REDIRECT])
        self.assertEqual(form['client_secret'],['FAKE_SECRET_NOT_REAL'])
        validate_request = calls[1].args[0]
        self.assertEqual(validate_request.full_url,'https://id.twitch.tv/oauth2/validate')
        self.assertEqual(validate_request.get_header('Authorization'),'OAuth FAKE_ACCESS_NOT_REAL')

    def test_mock_http_failure_is_sanitized_and_attempt_consumed(self):
        self.service.transport = StdlibOAuthHTTP(allow_network=True)
        state = self.start()
        with patch('oauth.build_opener') as factory:
            factory.return_value.open.side_effect = RuntimeError('PRIVATE_PROVIDER_DATA')
            with self.assertRaises(OAuthFailure) as caught:
                self.service.callback(self.sid,self.origin,state,'PRIVATE_FAKE_CODE')
            self.assertEqual(factory.return_value.open.call_count,1)
        self.assertNotIn('PRIVATE',str(caught.exception))
        self.assertIsNone(self.service._sessions[self.sid]['tokens'])
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,state,'fake')

    def test_success_minimal_scopes_tokens_backend_only_and_disconnect(self):
        state = self.start()
        result = self.service.callback(self.sid,self.origin,state,'FAKE_CODE_NOT_REAL')
        self.assertTrue(result['authenticated'])
        self.assertFalse(result['connected'])
        self.assertEqual(self.provider.exchanges,['FAKE_CODE_NOT_REAL'])
        status = self.service.status(self.sid,self.origin)[2]
        text = json.dumps([result,status])+repr(self.config)
        for secret in ('FAKE_CODE_NOT_REAL','FAKE_ACCESS_NOT_REAL','FAKE_REFRESH_NOT_REAL','FAKE_SECRET_NOT_REAL'):
            self.assertNotIn(secret,text)
        self.assertTrue(status['authenticated'])
        self.service.disconnect(self.sid,self.origin,self.csrf)
        self.assertFalse(self.service.status(self.sid,self.origin)[2]['authenticated'])
        self.assertIsNone(self.service._sessions[self.sid]['tokens'])
        with self.assertRaises(OAuthFailure):
            self.service.start(self.sid,self.origin,self.csrf)  # CSRF rotated.

    def test_csrf_origin_and_session_binding(self):
        for sid,origin,csrf in [(None,self.origin,self.csrf),(self.sid,self.origin,'wrong'),
                               (self.sid,'http://127.0.0.1:8000',self.csrf)]:
            with self.assertRaises(OAuthFailure):
                self.service.start(sid,origin,csrf)
        state = self.start()
        other = self.service.status(None,self.origin)[0]
        with self.assertRaises(OAuthFailure):
            self.service.callback(other,self.origin,state,'fake')
        self.assertEqual(self.provider.exchanges,[])
        self.assertTrue(self.service.callback(self.sid,self.origin,state,'fake')['authenticated'])

    def test_expiry_replay_and_replaced_attempt(self):
        first = self.start()
        second = self.start()
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,first,'fake')
        self.service.callback(self.sid,self.origin,second,'fake')
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,second,'fake')
        state = self.start()
        self.now[0] += self.service.STATE_TTL
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,state,'fake')
        self.assertEqual(len(self.provider.exchanges),1)
        self.now[0] += self.service.SESSION_TTL
        with self.assertRaises(OAuthFailure):
            self.service.start(self.sid,self.origin,self.csrf)

    def test_configuration_binding_and_provider_denial(self):
        for replacement in (replace(self.config,client_id='other'),replace(self.config,client_secret='other'),
                            replace(self.config,redirect='http://localhost:9999/auth/twitch/callback'),
                            replace(self.config,enabled=False)):
            self.service.config = self.config
            state = self.start()
            self.service.config = replacement
            with self.assertRaises(OAuthFailure):
                self.service.callback(self.sid,self.origin,state,'fake')
        self.service.config = self.config
        state = self.start()
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,state,error='PRIVATE_PROVIDER_ERROR')
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,state,'fake')
        self.assertEqual(self.provider.exchanges,[])

    def test_invalid_identity_scopes_and_exchange_payloads(self):
        cases = [('result','scope',[]),('result','scope',['user:read:chat','chat:edit']),
                 ('result','access_token',None),('result','token_type','other'),
                 ('result','expires_in',True),('result','refresh_token',[]),
                 ('identity','client_id','other'),('identity','login','other'),
                 ('identity','user_id','display-name'),('identity','scopes',[]),
                 ('identity','scopes',['user:read:chat','user:read:email']),('identity','expires_in',0)]
        for target,key,value in cases:
            self.provider = FakeProvider()
            getattr(self.provider,target)[key] = value
            self.service.transport = self.provider
            state = self.start()
            with self.subTest(target=target,key=key):
                with self.assertRaises(OAuthFailure):
                    self.service.callback(self.sid,self.origin,state,'fake')
                self.assertIsNone(self.service._sessions[self.sid]['tokens'])

    def test_provider_exception_sanitized_and_tokens_expire(self):
        self.provider.fail = True
        state = self.start()
        with self.assertRaises(OAuthFailure) as caught:
            self.service.callback(self.sid,self.origin,state,'PRIVATE_FAKE_CODE')
        self.assertNotIn('PRIVATE',str(caught.exception))
        with self.assertRaises(OAuthFailure):
            self.service.callback(self.sid,self.origin,state,'fake')
        self.provider.fail = False
        self.service.callback(self.sid,self.origin,self.start(),'fake')
        self.service._sessions[self.sid]['tokens']['expires'] = self.now[0]
        self.assertFalse(self.service.status(self.sid,self.origin)[2]['authenticated'])

    def test_bounded_sessions_and_states(self):
        self.service.LIMIT = 2
        for _ in range(5):
            sid,_,status = self.service.status(None,self.origin)
            self.service.start(sid,self.origin,status['csrf'])
        self.assertLessEqual(len(self.service._sessions),2)
        self.assertLessEqual(len(self.service._states),2)

class OAuthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.previous = server.OAUTH
        self.provider = FakeProvider()
        self.now = [100.0]
        server.OAUTH = OAuthService(OAuthConfig(True,'fake-client','FAKE_SECRET_NOT_REAL'),
                                    self.provider,clock=lambda:self.now[0])
        self.addCleanup(setattr,server,'OAUTH',self.previous)

    def exchange(self,path,body=None,host='localhost:8000',origin=None,cookie=None,csrf=None,extra=''):
        payload = b'' if body is None else json.dumps(body).encode()
        method = 'GET' if body is None else 'POST'
        headers = 'Host: '+host+'\r\nConnection: close\r\n'+extra
        if body is not None:
            headers += 'Content-Type: application/json\r\nContent-Length: '+str(len(payload))+'\r\n'
        for name,value in [('Origin',origin),('Cookie',cookie),('X-CSRF-Token',csrf)]:
            if value is not None:
                headers += name+': '+value+'\r\n'
        request = (method+' '+path+' HTTP/1.1\r\n'+headers+'\r\n').encode()+payload
        class Socket:
            output = bytearray()
            def makefile(self,*args): return io.BytesIO(request)
            def sendall(self,data): self.output.extend(data)
        sock = Socket()
        captured = io.StringIO()
        with redirect_stderr(captured):
            server.Handler(sock,('127.0.0.1',1234),SimpleNamespace(server_port=8000))
        head,raw = bytes(sock.output).split(b'\r\n\r\n',1)
        self.assertEqual(captured.getvalue(),'')
        return int(head.split()[1]),head.decode(),raw

    def session(self,host='localhost:8000'):
        code,headers,raw = self.exchange('/api/twitch/status',host=host)
        self.assertEqual(code,200)
        cookie = next(line.split(': ',1)[1].split(';')[0] for line in headers.split('\r\n') if line.startswith('Set-Cookie:'))
        self.assertIn('HttpOnly; SameSite=Lax',headers)
        self.assertNotIn('Domain=',headers)
        self.assertIn('Referrer-Policy: no-referrer',headers)
        return cookie,json.loads(raw)['csrf']

    def begin(self,cookie,csrf):
        code,_,raw = self.exchange('/auth/twitch/start',{},origin='http://localhost:8000',cookie=cookie,csrf=csrf)
        self.assertEqual(code,200)
        return parse_qs(urlsplit(json.loads(raw)['authorization_url']).query)['state'][0]

    def test_localhost_full_mock_flow_status_disconnect_and_redaction(self):
        cookie,csrf = self.session()
        state = self.begin(cookie,csrf)
        path = '/auth/twitch/callback?'+urlencode({'state':state,'code':'PRIVATE_FAKE_CODE'})
        code,headers,raw = self.exchange(path,cookie=cookie)
        self.assertEqual(code,200)
        self.assertTrue(json.loads(raw)['authenticated'])
        self.assertFalse(json.loads(raw)['connected'])
        for sentinel in ('PRIVATE_FAKE_CODE','FAKE_ACCESS_NOT_REAL','FAKE_REFRESH_NOT_REAL','FAKE_SECRET_NOT_REAL',state):
            self.assertNotIn(sentinel,headers+raw.decode())
        self.assertEqual(self.exchange(path,cookie=cookie)[0],400)
        self.assertTrue(json.loads(self.exchange('/api/twitch/status',cookie=cookie)[2])['authenticated'])
        self.assertEqual(self.exchange('/auth/twitch/disconnect',{},cookie=cookie,csrf=csrf)[0],403)
        self.assertEqual(self.exchange('/auth/twitch/disconnect',{},origin='http://localhost:8000',cookie=cookie,csrf=csrf)[0],200)
        self.assertFalse(json.loads(self.exchange('/api/twitch/status',cookie=cookie)[2])['authenticated'])

    def test_hosts_origins_dns_rebind_and_duplicate_headers(self):
        for host in ('evil.invalid:8000','localhost.evil.invalid:8000','127.0.0.1.evil.invalid:8000',
                     'localhost:9999','localhost','user@localhost:8000','127.0.0.2:8000'):
            self.assertEqual(self.exchange('/api/state',host=host)[0],403)
        self.assertEqual(self.exchange('/api/state',extra='Host: evil.invalid\r\n')[0],403)
        for host in ('localhost:8000','127.0.0.1:8000'):
            self.assertEqual(self.exchange('/api/state',host=host)[0],200)
            self.assertEqual(self.exchange('/api/twitch/status',host=host,origin='https://evil.invalid')[0],403)
        self.assertEqual(self.exchange('/api/state',origin='http://127.0.0.1:8000')[0],403)
        self.assertEqual(self.exchange('http://localhost:8000/api/state')[0],400)
        self.assertEqual(self.exchange('http://[bad')[0],400)
        self.assertEqual(self.exchange('/api/state',origin='null')[0],403)
        self.assertEqual(self.exchange('/api/state',origin='http://localhost:8000',extra='Origin: http://localhost:8000\r\n')[0],403)

    def test_start_requires_post_origin_session_csrf_and_canonical_origin(self):
        cookie,csrf = self.session()
        self.assertEqual(self.exchange('/auth/twitch/start',cookie=cookie)[0],404)
        variants = [dict(cookie=cookie,csrf=csrf),dict(origin='http://localhost:8000',csrf=csrf),
                    dict(origin='http://localhost:8000',cookie=cookie,csrf='wrong'),
                    dict(origin='https://evil.invalid',cookie=cookie,csrf=csrf)]
        for kwargs in variants:
            self.assertEqual(self.exchange('/auth/twitch/start',{},**kwargs)[0],403)
        ip_cookie,ip_csrf = self.session('127.0.0.1:8000')
        self.assertEqual(self.exchange('/auth/twitch/start',{},host='127.0.0.1:8000',origin='http://127.0.0.1:8000',cookie=ip_cookie,csrf=ip_csrf)[0],403)
        self.assertEqual(self.provider.exchanges,[])

    def test_callback_attacks_provider_error_expiry_and_missing_config(self):
        cookie,csrf = self.session()
        state = self.begin(cookie,csrf)
        other,_ = self.session()
        path = '/auth/twitch/callback?'+urlencode({'state':state,'code':'PRIVATE_CODE'})
        self.assertEqual(self.exchange(path,cookie=other)[0],400)
        self.assertEqual(self.exchange(path)[0],400)
        self.assertEqual(self.exchange(path+'&code=duplicate',cookie=cookie)[0],400)
        self.assertEqual(self.exchange(path+'&error=denied',cookie=cookie)[0],400)
        error_path = '/auth/twitch/callback?'+urlencode({'state':state,'error':'PRIVATE_ERROR','error_description':'PRIVATE_DESCRIPTION'})
        result = self.exchange(error_path,cookie=cookie)
        self.assertEqual(result[0],400)
        self.assertNotIn('PRIVATE',result[2].decode())
        self.assertEqual(self.exchange(path,cookie=cookie)[0],400)
        state = self.begin(cookie,csrf)
        self.now[0] += 301
        self.assertEqual(self.exchange('/auth/twitch/callback?'+urlencode({'state':state,'code':'fake'}),cookie=cookie)[0],400)
        self.assertEqual(self.provider.exchanges,[])
        server.OAUTH = OAuthService()
        cookie,csrf = self.session()
        raw = self.exchange('/api/twitch/status',cookie=cookie)[2]
        self.assertFalse(json.loads(raw)['ready'])
        self.assertFalse(json.loads(raw)['authenticated'])
        self.assertEqual(self.exchange('/auth/twitch/start',{},origin='http://localhost:8000',cookie=cookie,csrf=csrf)[0],403)

if __name__ == '__main__':
    unittest.main()
