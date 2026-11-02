"""Fake-only narration protocol checks: no provider/key/socket use."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from tools import elevenlabs_narration as n

class Fake:
    def __init__(self, fail=False):self.calls=[];self.fail=fail;self.count=10
    def request(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if path=='/v1/models':return [{'model_id':'eleven_multilingual_v2','can_do_text_to_speech':True},{'model_id':'transcription','can_do_text_to_speech':False}]
        if path=='/v1/voices':return {'voices':[{'voice_id':'premade123','category':'premade'},{'voice_id':'custom123','category':'cloned'}]}
        if path=='/v1/user/subscription':return {'character_count':self.count,'character_limit':10000,'private_field':'DO_NOT_REFLECT'}
        if method=='POST':
            if self.fail:raise n.NarrationError('Provider request failed.')
            self.count+=len(payload['text']);return b'FAKE_MP3'
        raise AssertionError('Unexpected request')

class NarrationTests(unittest.TestCase):
    def test_dry_run_reads_no_key_and_makes_no_request(self):
        with patch.object(n.os.environ,'get',side_effect=lambda name,*args: (_ for _ in ()).throw(AssertionError('key read')) if name=='ELEVENLABS_API_KEY' else None), patch.object(n.HTTPS,'request',side_effect=AssertionError('network')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(n.main(['--dry-run']),0)
        data=json.loads(output.getvalue());self.assertFalse(data['network']);self.assertFalse(data['key_read']);self.assertLessEqual(data['characters'],4000)
    def test_default_is_dry_run_and_generation_requires_explicit_approval(self):
        with patch.object(n.os.environ,'get',side_effect=lambda name,*args: (_ for _ in ()).throw(AssertionError('key read')) if name=='ELEVENLABS_API_KEY' else None),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(n.main([]),0)
            self.assertEqual(n.main(['--generate','--voice-id','premade123']),1)
        fake=Fake()
        with self.assertRaises(n.NarrationError):n.generate(fake,'hello','premade123','eleven_multilingual_v2')
        self.assertEqual(fake.calls,[])
    def test_premade_and_tts_model_selection_only(self):
        catalog=n.inspect_provider(Fake())
        self.assertEqual(catalog['preferred_model'],'eleven_multilingual_v2')
        self.assertEqual(catalog['premade_voices'],[{'voice_id':'premade123','category':'premade'}])
        self.assertNotIn('DO_NOT_REFLECT',json.dumps(catalog))
        for voice,model in [('custom123','eleven_multilingual_v2'),('premade123','transcription'),('../unsafe','eleven_multilingual_v2')]:
            with self.assertRaises(n.NarrationError):n.select(catalog,voice,model)
    def test_length_rejected_before_network(self):
        for text in ['', 'x'*4001, 'bad\x00text']:
            fake=Fake()
            with self.assertRaises(n.NarrationError):n.generate(fake,text,'premade123','eleven_multilingual_v2',True)
            self.assertEqual(fake.calls,[])
        self.assertEqual(len(n.validate_text('x'*4000)),4000)
    def test_one_generation_and_sanitized_usage_receipt(self):
        fake=Fake();audio,receipt=n.generate(fake,'hello','premade123','eleven_multilingual_v2',True)
        self.assertEqual(audio,b'FAKE_MP3');self.assertEqual(receipt['character_count_delta'],5)
        self.assertEqual(sum(method=='POST' for method,_,_ in fake.calls),1)
        self.assertNotIn('DO_NOT_REFLECT',json.dumps(receipt))
    def test_post_failure_has_no_retry(self):
        fake=Fake(fail=True)
        with self.assertRaises(n.NarrationError):n.generate(fake,'hello','premade123','eleven_multilingual_v2',True)
        self.assertEqual(sum(method=='POST' for method,_,_ in fake.calls),1)
    def test_key_repr_and_error_body_are_redacted(self):
        sentinel='SYNTHETIC_TEST_KEY_NEVER_REAL'
        transport=n.HTTPS(sentinel)
        self.assertNotIn(sentinel,repr(transport))
        from urllib.error import HTTPError
        body=io.BytesIO(b'PRIVATE_PROVIDER_BODY')
        opener=unittest.mock.Mock()
        opener.open.side_effect=HTTPError('https://api.elevenlabs.io/v1/models',401,'sensitive',{},body)
        with patch.object(n,'build_opener',return_value=opener):
            with self.assertRaises(n.NarrationError) as error:transport.request('GET','/v1/models')
        self.assertEqual(str(error.exception),'Provider request failed.');self.assertEqual(body.tell(),0)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.elevenlabs.io/v1/models')
        self.assertEqual(request.get_header('Xi-api-key'),sentinel)
    def test_redirect_refused_for_all_destinations(self):
        for destination in ['https://evil.test/', 'https://api.elevenlabs.io/v1/models','http://api.elevenlabs.io/v1/models']:
            with self.assertRaises(n.NarrationError):n.NoRedirect().redirect_request(None,None,302,'',{},destination)
    def test_endpoint_and_method_allowlist(self):
        transport=n.HTTPS('SYNTHETIC')
        with patch.object(n,'build_opener',side_effect=AssertionError('network')):
            for method,path in [('GET','https://evil.test'),('POST','/v1/voices'),('GET','/v1/text-to-speech/voice'),('GET','/v1/models?key=x')]:
                with self.assertRaises(n.NarrationError):transport.request(method,path)
    def test_inspect_never_generates(self):
        fake=Fake()
        with patch.object(n.os.environ,'get',side_effect=lambda name,*args: 'SYNTHETIC' if name=='ELEVENLABS_API_KEY' else None),patch.object(n,'HTTPS',return_value=fake),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(n.main(['--inspect']),0)
        self.assertTrue(all(method=='GET' for method,_,_ in fake.calls))
        self.assertNotIn('SYNTHETIC',output.getvalue())
    def test_output_refuses_symlink_and_existing_generation(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'video').mkdir();(root/'video/public').mkdir()
            (root/'target').mkdir();(root/'video/public/media').symlink_to(root/'target',target_is_directory=True)
            with patch.object(n,'ROOT',root):
                with self.assertRaises(n.NarrationError):n.output_directory()
            (root/'video/public/media').unlink();(root/'video/public/media').mkdir()
            (root/'video/public/media/narration.mp3').write_bytes(b'FAKE')
            with patch.object(n,'ROOT',root):
                with self.assertRaises(n.NarrationError):n.output_directory()
    def test_cli_sanitizes_unexpected_local_or_provider_value_error(self):
        with patch.object(n.os.environ,'get',return_value='SYNTHETIC'),patch.object(n,'inspect_provider',side_effect=ValueError('PRIVATE_BODY')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(n.main(['--inspect']),1)
        self.assertNotIn('PRIVATE_BODY',output.getvalue());self.assertNotIn('SYNTHETIC',output.getvalue())

if __name__=='__main__':unittest.main()
