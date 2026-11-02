"""Only synthetic credentials in newly-created temporary directories are read."""
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from contextlib import redirect_stdout, redirect_stderr
import unittest
from unittest.mock import patch, Mock
import local_config
from local_config import load_local_credentials, LocalConfigError, ERROR
from oauth import OAuthService
from eventsub import TwitchController, WebSocketFactory, StdlibHelix
import server

FAKE = {'schema_version':1,'client_id':'FAKECLIENTONLY123','client_secret':'FAKESECRET_ONLY_NOT_REAL'}

class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.root.chmod(0o700)
        self.folder=self.root/'.twitch-local'
        self.folder.mkdir(mode=0o700)
        self.file=self.folder/'credentials.json'
        self.write(FAKE)

    def write(self,data,raw=False):
        self.file.write_bytes(data if raw else json.dumps(data).encode())
        self.file.chmod(0o600)

    def invalid(self):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):
            with self.assertRaises(LocalConfigError) as caught:
                load_local_credentials(self.root)
        self.assertEqual(str(caught.exception),ERROR)
        self.assertEqual(out.getvalue()+err.getvalue(),'')
        self.assertNotIn(str(self.root),str(caught.exception))
        self.assertNotIn(FAKE['client_secret'],str(caught.exception))

    def test_valid_disabled_redacted_and_never_enables_network(self):
        credentials=load_local_credentials(self.root)
        self.assertEqual(credentials.client_id,FAKE['client_id'])
        self.assertEqual(credentials.client_secret,FAKE['client_secret'])
        config=credentials.disabled_oauth_config()
        self.assertFalse(config.enabled)
        for value in (FAKE['client_id'],FAKE['client_secret']):
            self.assertNotIn(value,repr(credentials)+repr(config))
        service=OAuthService(config)
        self.assertFalse(service.ready())
        self.assertFalse(service.transport.allow_network)
        self.assertFalse(WebSocketFactory().allow_network)
        self.assertFalse(StdlibHelix().allow_network)
        self.assertFalse(TwitchController(None,None,lambda:service).approved)
        self.file.chmod(0o400)
        self.assertEqual(load_local_credentials(self.root),credentials)

    def test_missing_file_and_directory(self):
        self.file.unlink();self.invalid()
        self.folder.rmdir();self.invalid()

    def test_malformed_json_duplicates_types_and_unsupported_keys(self):
        cases=[b'{bad PRIVATE',b'[]',b'null',b'\xff',b'\xef\xbb\xbf{}',
               b'{"schema_version":1,"client_id":"x","client_id":"y","client_secret":"z"}',
               b'{"schema_version":NaN,"client_id":"x","client_secret":"z"}']
        for raw in cases:
            with self.subTest(raw_type=len(raw)):
                self.write(raw,raw=True);self.invalid()
        for key,value in [('schema_version',True),('schema_version',2),('client_id',''),
                          ('client_id','x y'),('client_id','é'),('client_id',[]),
                          ('client_id','x'*257),('client_secret',''),('client_secret','x\ny'),
                          ('client_secret','é'),('client_secret','x'*1025),('client_secret',False),
                          ('enabled',True),('oauth_enabled',False),('scope','user:read:chat'),
                          ('redirect','http://localhost:8000/auth/twitch/callback')]:
            obj=dict(FAKE);obj[key]=value
            self.write(obj);self.invalid()
        for key in FAKE:
            obj=dict(FAKE);del obj[key]
            self.write(obj);self.invalid()

    def test_empty_and_oversized_file(self):
        for raw in (b'',b'x'*(local_config.MAX_BYTES+1)):
            self.write(raw,raw=True)
            with patch('local_config.os.read',side_effect=AssertionError('Must reject before reading')):
                self.invalid()

    def test_insecure_file_permissions_rejected_before_read(self):
        for mode in (0o644,0o640,0o660,0o777,0o700):
            self.file.chmod(mode)
            with patch('local_config.os.read',side_effect=AssertionError('Must not read insecure storage')):
                self.invalid()

    def test_extended_acl_rejected_without_reading(self):
        with patch('local_config._no_extended_acl',return_value=False),patch('local_config.os.read',side_effect=AssertionError('No ACL-protected reads')):
            self.invalid()

    def test_insecure_private_directory_and_workspace(self):
        for mode in (0o755,0o750,0o770):
            self.folder.chmod(mode)
            with patch('local_config.os.read',side_effect=AssertionError('Must not read insecure storage')):
                self.invalid()
        self.folder.chmod(0o700)
        self.root.chmod(0o777)
        self.invalid()
        self.root.chmod(0o700)

    def test_symlink_file_directory_and_workspace_rejected(self):
        target=self.root/'fake-target'
        self.file.rename(target)
        self.file.symlink_to(target)
        with patch('local_config.os.read',side_effect=AssertionError('No symlink reads')):
            self.invalid()
        self.file.unlink();target.rename(self.file)
        real_folder=self.root/'real-folder'
        self.folder.rename(real_folder);self.folder.symlink_to(real_folder,target_is_directory=True)
        self.invalid()
        self.folder.unlink();real_folder.rename(self.folder)
        alias=self.root/'root-alias';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(LocalConfigError):load_local_credentials(alias)

    def test_hardlink_nonregular_and_wrong_owner_rejected(self):
        other=self.root/'fake-hardlink'
        os.link(self.file,other)
        self.invalid();other.unlink()
        self.file.unlink();os.mkfifo(self.file,0o600)
        self.invalid();self.file.unlink();self.write(FAKE)
        # No chown/privilege use: emulate another effective owner by changing expected UID.
        with patch('local_config.os.getuid',return_value=os.getuid()+1):self.invalid()

    def test_file_changed_during_read_rejected(self):
        original=os.read
        changed=[False]
        def mutate(fd,size):
            result=original(fd,size)
            if not changed[0]:
                changed[0]=True
                with self.file.open('ab') as stream:stream.write(b' ')
            return result
        with patch('local_config.os.read',side_effect=mutate):self.invalid()

    def test_template_is_empty_not_a_credential_and_cannot_enable(self):
        # Read only the new tracked placeholder template, never a real config path.
        template=(Path(__file__).resolve().parent.parent/'twitch-config.example.json').read_bytes()
        self.assertEqual(json.loads(template),{'schema_version':1,'client_id':'','client_secret':''})
        self.write(template,raw=True);self.invalid()

    def test_cli_check_success_no_bind_network_or_values(self):
        out,err=io.StringIO(),io.StringIO()
        with patch('server.ThreadingHTTPServer') as bind,patch('oauth.build_opener') as network:
            with redirect_stdout(out),redirect_stderr(err):
                code=server.main(['--check-twitch-config'],workspace=self.root)
            bind.assert_not_called();network.assert_not_called()
        self.assertEqual(code,0)
        self.assertIn('all live gates remain disabled',out.getvalue())
        self.assertEqual(err.getvalue(),'')
        for value in FAKE.values():
            if isinstance(value,str):self.assertNotIn(value,out.getvalue())

    def test_cli_load_keeps_all_gates_off_with_mock_listener(self):
        previous=server.OAUTH
        self.addCleanup(setattr,server,'OAUTH',previous)
        out=io.StringIO()
        with patch('server.ThreadingHTTPServer') as listener,patch('oauth.build_opener') as network:
            with redirect_stdout(out):self.assertEqual(server.main(['--load-twitch-config'],workspace=self.root),0)
            listener.assert_called_once_with(('127.0.0.1',8000),server.Handler)
            network.assert_not_called()
        self.assertFalse(server.OAUTH.config.enabled)
        self.assertFalse(server.OAUTH.ready())
        self.assertFalse(server.OAUTH.transport.allow_network)
        self.assertFalse(server.TWITCH.approved)
        self.assertNotIn(FAKE['client_secret'],out.getvalue())

    def test_cli_fail_closed_no_bind_and_no_default_or_import_discovery(self):
        self.file.unlink()
        err=io.StringIO()
        with patch('server.ThreadingHTTPServer') as listener:
            with redirect_stderr(err):
                self.assertEqual(server.main(['--check-twitch-config'],workspace=self.root),2)
                self.assertEqual(server.main(['--load-twitch-config'],workspace=self.root),2)
            listener.assert_not_called()
        self.assertEqual(err.getvalue(),(ERROR+'\n')*2)
        with patch('server.load_local_credentials',side_effect=AssertionError('No default secret read')) as load:
            with patch('server.ThreadingHTTPServer'),redirect_stdout(io.StringIO()):
                server.main([],workspace=self.root)
            load.assert_not_called()

if __name__ == '__main__':unittest.main()
