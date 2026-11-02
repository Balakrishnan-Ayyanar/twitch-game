"""No real credentials/listeners/provider calls: fake temp storage and HTTP streams."""
import io
import json
import tempfile
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from urllib.parse import urlencode
from unittest.mock import patch
import unittest
import server
from oauth import OAuthService, OAuthConfig, REDIRECT, SCOPES
from local_config import LocalCredentials
from test_oauth import FakeProvider
import test_oauth as oauth_fixtures

class ActivationTests(unittest.TestCase):
    def setUp(self):
        old=(server.OAUTH,server.TWITCH,server.LIVE_ENABLED)
        def restore():server.OAUTH,server.TWITCH,server.LIVE_ENABLED=old
        self.addCleanup(restore)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        folder=self.root/'.twitch-local';folder.mkdir(mode=0o700)
        self.file=folder/'credentials.json'
        self.file.write_text(json.dumps({'schema_version':1,'client_id':'FAKECLIENT123','client_secret':'FAKESECRET_NOT_REAL'}))
        self.file.chmod(0o600)

    def main(self,args):
        out,err=io.StringIO(),io.StringIO()
        with patch('server.ThreadingHTTPServer') as listener,patch('oauth.build_opener') as oauth_io,patch('eventsub.build_opener') as helix_io,patch('eventsub.WebSocketFactory.__call__') as socket_io:
            with redirect_stdout(out),redirect_stderr(err):code=server.main(args,workspace=self.root)
            oauth_io.assert_not_called();helix_io.assert_not_called();socket_io.assert_not_called()
        self.assertNotIn('FAKESECRET',out.getvalue()+err.getvalue())
        self.assertNotIn('FAKECLIENT',out.getvalue()+err.getvalue())
        return code,listener,out.getvalue(),err.getvalue()

    def test_explicit_live_flag_wires_all_gates_without_starting_provider(self):
        code,listener,_,err=self.main(['--enable-twitch','--port','8000'])
        self.assertEqual(code,0);self.assertEqual(err,'')
        listener.assert_called_once_with(('127.0.0.1',8000),server.Handler)
        self.assertTrue(server.LIVE_ENABLED)
        self.assertTrue(server.OAUTH.ready())
        self.assertTrue(server.OAUTH.config.enabled)
        self.assertEqual(server.OAUTH.config.redirect,REDIRECT)
        self.assertEqual(server.OAUTH.config.expected_login,'balakrishnanayyanar')
        self.assertTrue(server.OAUTH.transport.allow_network)
        self.assertTrue(server.TWITCH.approved)
        self.assertIsNone(server.TWITCH.worker)
        worker=server.TWITCH.worker_factory(server.GAME,server.LOCK,lambda:None,approved=True)
        self.assertTrue(worker.approved)
        self.assertTrue(worker.socket_factory.allow_network)
        self.assertTrue(worker.helix.allow_network)
        self.assertFalse(worker.status()['connected'])
        self.assertEqual(SCOPES,('user:read:chat',))
        self.assertEqual(server.OAUTH._sessions,{})

    def test_default_and_storage_load_never_enable_live(self):
        with patch('server.load_local_credentials',side_effect=AssertionError('No secret discovery')):
            self.assertEqual(self.main([])[0],0)
        self.assertFalse(server.LIVE_ENABLED)
        self.assertFalse(server.OAUTH.ready())
        self.assertFalse(server.TWITCH.approved)
        self.assertEqual(self.main(['--load-twitch-config'])[0],0)
        self.assertFalse(server.LIVE_ENABLED)
        self.assertFalse(server.OAUTH.config.enabled)
        self.assertFalse(server.OAUTH.transport.allow_network)
        self.assertFalse(server.TWITCH.approved)
        self.assertEqual(self.main(['--check-twitch-config'])[0],0)

    def test_wrong_port_rejected_before_credentials_or_listener(self):
        with patch('server.load_local_credentials',side_effect=AssertionError('No credential read')):
            code,listener,_,err=self.main(['--enable-twitch','--port','8080'])
        self.assertEqual(code,2);listener.assert_not_called()
        self.assertEqual(err,'Live Twitch requires exact http://localhost:8000.\n')

    def test_missing_or_insecure_fake_storage_fails_closed(self):
        for mode in (0o644,):
            self.file.chmod(mode)
            code,listener,_,_=self.main(['--enable-twitch'])
            self.assertEqual(code,2);listener.assert_not_called()
        self.file.unlink()
        code,listener,_,_=self.main(['--enable-twitch'])
        self.assertEqual(code,2);listener.assert_not_called()
        self.assertFalse(server.LIVE_ENABLED)

    def test_startup_failure_is_sanitized_and_never_retried(self):
        import errno
        for error in (PermissionError(errno.EPERM,'PRIVATE'),OSError(errno.EADDRINUSE,'PRIVATE'),OSError('PRIVATE')):
            err=io.StringIO()
            with patch('server.ThreadingHTTPServer',side_effect=error) as listener,patch('server.load_local_credentials') as load:
                with redirect_stderr(err):code=server.main([],workspace=self.root)
                self.assertEqual(code,2)
                self.assertEqual(listener.call_count,1)
                load.assert_not_called()
            self.assertNotIn('PRIVATE',err.getvalue())
            self.assertNotIn('Traceback',err.getvalue())

    def test_cli_modes_are_mutually_exclusive(self):
        for flag in ('--load-twitch-config','--check-twitch-config'):
            with redirect_stderr(io.StringIO()),patch('server.load_local_credentials') as load:
                with self.assertRaises(SystemExit) as caught:server.main(['--enable-twitch',flag],workspace=self.root)
                self.assertEqual(caught.exception.code,2)
                load.assert_not_called()

class LiveProtocolTests(unittest.TestCase):
    exchange=oauth_fixtures.OAuthHTTPTests.exchange
    session=oauth_fixtures.OAuthHTTPTests.session
    begin=oauth_fixtures.OAuthHTTPTests.begin

    def setUp(self):
        old=(server.OAUTH,server.TWITCH,server.LIVE_ENABLED)
        def restore():server.OAUTH,server.TWITCH,server.LIVE_ENABLED=old
        self.addCleanup(restore)
        server.configure_runtime(LocalCredentials('FAKECLIENT123','FAKESECRET_NOT_REAL'),live=True)
        self.provider=FakeProvider()
        self.provider.identity['client_id']='FAKECLIENT123'
        server.OAUTH.transport=self.provider
        # Nothing invokes the real worker/factories in these protocol tests.

    def test_live_exact_host_and_origin_and_new_asset(self):
        self.assertEqual(self.exchange('/',host='127.0.0.1:8000')[0],403)
        self.assertEqual(self.exchange('/',host='localhost:8080')[0],403)
        self.assertEqual(self.exchange('/',host='localhost.evil.invalid:8000')[0],403)
        self.assertEqual(self.exchange('/')[0],200)
        code,_,body=self.exchange('/twitch-ui.js')
        self.assertEqual(code,200);self.assertIn(b'X-CSRF-Token',body)
        cookie,csrf=self.session()
        result=self.exchange('/auth/twitch/start',{},origin='http://127.0.0.1:8000',cookie=cookie,csrf=csrf)
        self.assertEqual(result[0],403)
        self.assertEqual(self.provider.exchanges,[])

    def test_browser_callback_clean_redirect_no_codes_or_tokens(self):
        cookie,csrf=self.session();state=self.begin(cookie,csrf)
        path='/auth/twitch/callback?'+urlencode({'state':state,'code':'PRIVATE_CALLBACK_CODE'})
        code,headers,raw=self.exchange(path,cookie=cookie,extra='Accept: text/html\r\n')
        self.assertEqual(code,303)
        self.assertIn('Location: http://localhost:8000/?twitch=authorized',headers)
        self.assertIn('Referrer-Policy: no-referrer',headers)
        self.assertEqual(raw,b'')
        for value in ('PRIVATE_CALLBACK_CODE',state,'FAKE_ACCESS_NOT_REAL','FAKE_REFRESH_NOT_REAL','FAKESECRET_NOT_REAL'):
            self.assertNotIn(value,headers+raw.decode())
        status=json.loads(self.exchange('/api/twitch/status',cookie=cookie)[2])
        self.assertTrue(status['authenticated']);self.assertFalse(status['connected'])
        self.assertTrue(status['transport_enabled'])
        self.assertEqual(status['requested_scope'],'user:read:chat')
        self.assertEqual(status['expected_login'],'balakrishnanayyanar')
        # Replay stays rejected, including when requesting HTML.
        code,headers,_=self.exchange(path,cookie=cookie,extra='Accept: text/html\r\n')
        self.assertEqual(code,303)
        self.assertIn('Location: http://localhost:8000/?twitch=authorization_failed',headers)
        self.assertEqual(len(self.provider.exchanges),1)

    def test_browser_provider_denial_sanitized_no_exchange(self):
        cookie,csrf=self.session();state=self.begin(cookie,csrf)
        path='/auth/twitch/callback?'+urlencode({'state':state,'error':'PRIVATE_PROVIDER_BODY','error_description':'DO_NOT_RENDER'})
        code,headers,raw=self.exchange(path,cookie=cookie,extra='Accept: text/html\r\n')
        self.assertEqual(code,303);self.assertEqual(raw,b'')
        self.assertIn('authorization_failed',headers)
        self.assertNotIn('PRIVATE',headers);self.assertNotIn('DO_NOT_RENDER',headers)
        self.assertEqual(self.provider.exchanges,[])

    def test_json_callback_retains_sanitized_contract_and_local_link(self):
        cookie,csrf=self.session();state=self.begin(cookie,csrf)
        path='/auth/twitch/callback?'+urlencode({'state':state,'code':'FAKECODE'})
        code,_,raw=self.exchange(path,cookie=cookie)
        self.assertEqual(code,200)
        result=json.loads(raw)
        self.assertTrue(result['authenticated'])
        self.assertEqual(result['return_to'],'http://localhost:8000/')
        self.assertNotIn('FAKECODE',raw.decode())

if __name__ == '__main__':unittest.main()
