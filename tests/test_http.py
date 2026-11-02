"""Real loopback HTTP smoke checks with an ephemeral port; no external requests."""
import json
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
import server
from game import Game

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        except PermissionError as exc:
            raise unittest.SkipTest('Executor denies loopback bind: '+str(exc))
        cls.thread = Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:'+str(cls.http.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def setUp(self):
        with server.LOCK:
            server.GAME = Game()

    def fetch(self,path,body=None,origin=None):
        headers = {'Content-Type':'application/json'}
        if origin:
            headers['Origin'] = origin
        req = Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
        with urlopen(req,timeout=3) as response:
            return response.status,response.headers,response.read()

    def test_assets_state_vote_restart(self):
        for path,mime in [('/','text/html'),('/app.js','text/javascript'),('/style.css','text/css')]:
            code,headers,data = self.fetch(path)
            self.assertEqual(code,200)
            self.assertIn(mime,headers['Content-Type'])
            self.assertGreater(len(data),500)
        state = json.loads(self.fetch('/api/state')[2])
        self.assertEqual(state['status'],'ready')
        self.assertIn('SIMULATED',state['mode'])
        state = json.loads(self.fetch('/api/start',{})[2])
        vote = {'viewer':'test','option':'supply','token':state['token']}
        self.assertTrue(json.loads(self.fetch('/api/vote',vote)[2])['ok'])
        with self.assertRaises(HTTPError) as caught:
            self.fetch('/api/vote',vote)
        self.assertEqual(caught.exception.code,409)
        reset = json.loads(self.fetch('/api/restart',{})[2])
        self.assertEqual(reset['status'],'ready')
        self.assertNotEqual(reset['token'],state['token'])

    def test_bad_requests_and_static_allowlist(self):
        for path in ['/../game.py','/evidence/build-prompt.txt','/missing']:
            with self.assertRaises(HTTPError) as caught:
                self.fetch(path)
            self.assertEqual(caught.exception.code,404)
        with self.assertRaises(HTTPError) as caught:
            self.fetch('/api/start',{},'https://example.invalid')
        self.assertEqual(caught.exception.code,403)
        req = Request(self.base+'/api/vote',data=b'{broken')
        with self.assertRaises(HTTPError) as caught:
            urlopen(req,timeout=3)
        self.assertEqual(caught.exception.code,400)
        with self.assertRaises(HTTPError) as caught:
            self.fetch('/api/start',[])
        self.assertEqual(caught.exception.code,400)

class HandlerSmokeTests(unittest.TestCase):
    """Exercise actual HTTP parsing/routing over byte streams when bind is restricted."""
    def setUp(self):
        server.GAME = Game(clock=lambda: 0)

    def exchange(self, path, body=None, raw=None, origin=None):
        import io
        from types import SimpleNamespace
        payload = b'' if body is None else json.dumps(body).encode()
        if raw is not None:
            payload = raw
        method = 'GET' if body is None and raw is None else 'POST'
        headers = 'Host: 127.0.0.1:8000\r\nConnection: close\r\n'
        if method == 'POST':
            headers += 'Content-Length: {}\r\n'.format(len(payload))
        if origin:
            headers += 'Origin: '+origin+'\r\n'
        request = (method+' '+path+' HTTP/1.1\r\n'+headers+'\r\n').encode()+payload
        class Socket:
            def __init__(self):
                self.output = bytearray()
            def makefile(self, *args):
                return io.BytesIO(request)
            def sendall(self, data):
                self.output.extend(data)
        sock = Socket()
        server.Handler(sock, ('127.0.0.1',12345), SimpleNamespace(server_port=8000))
        head, data = bytes(sock.output).split(b'\r\n\r\n',1)
        self.assertIn(('Content-Length: '+str(len(data))).encode(), head)
        return int(head.split()[1]), head, data

    def test_full_http_mission_flow(self):
        for path in ['/', '/app.js', '/style.css']:
            code, _, data = self.exchange(path)
            self.assertEqual(code,200)
            self.assertGreater(len(data),500)
        state = json.loads(self.exchange('/api/start',{})[2])
        self.assertEqual(state['status'],'running')
        body = {'viewer':'smoke','option':'supply','token':state['token']}
        self.assertEqual(self.exchange('/api/vote',body)[0],200)
        self.assertEqual(self.exchange('/api/vote',body)[0],409)
        server.GAME.advance(60)
        state = json.loads(self.exchange('/api/state')[2])
        self.assertEqual(state['status'],'won')
        reset = json.loads(self.exchange('/api/restart',{})[2])
        self.assertEqual(reset['status'],'ready')
        self.assertNotEqual(reset['token'],state['token'])

    def test_http_validation_and_private_files(self):
        for path in ['/game.py','/../SESSION_HANDOFF.md','/evidence/build-prompt.txt']:
            self.assertEqual(self.exchange(path)[0],404)
        self.assertEqual(self.exchange('/api/start',{},origin='https://example.invalid')[0],403)
        self.assertEqual(self.exchange('/api/start',raw=b'{bad')[0],400)
        self.assertEqual(self.exchange('/api/start',[])[0],400)
        self.assertEqual(self.exchange('/api/missing',{})[0],404)

if __name__ == '__main__':
    unittest.main()
