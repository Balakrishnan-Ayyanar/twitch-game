"""Intentional, backend-only ElevenLabs narration. Import/dry-run never reads a key.

No redirect following, POST retries, cloning, browser key or provider error output.
"""
import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parent.parent
MAX_CHARS = 4000
MAX_AUDIO = 20 * 1024 * 1024
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,100}$')

class NarrationError(Exception):
    """Only fixed, sanitized messages leave this boundary."""

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise NarrationError('Provider redirect refused.')

@dataclass(repr=False)
class HTTPS:
    key: str = field(repr=False)
    def __repr__(self):
        return 'HTTPS(key=<redacted>)'
    def request(self, method, path, payload=None):
        if method not in ('GET', 'POST') or not re.fullmatch(r'/v1/(?:models|voices|user/subscription|text-to-speech/[A-Za-z0-9_-]{1,100})', path):
            raise NarrationError('Provider endpoint refused.')
        if (method == 'POST') != path.startswith('/v1/text-to-speech/'):
            raise NarrationError('Provider method refused.')
        url = 'https://api.elevenlabs.io' + path
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.netloc != 'api.elevenlabs.io':
            raise NarrationError('Provider host refused.')
        if not isinstance(self.key,str) or not self.key or len(self.key)>512 or any(ord(c)<33 or ord(c)>126 for c in self.key):
            raise NarrationError('API key unavailable or invalid.')
        headers = {'xi-api-key': self.key, 'Accept': 'audio/mpeg' if method=='POST' else 'application/json'}
        body = None
        if payload is not None:
            body=json.dumps(payload).encode('utf-8');headers['Content-Type']='application/json'
        request=Request(url,data=body,headers=headers,method=method)
        try:
            # HTTPSHandler uses default verified TLS. No caller-controlled URLs/opener.
            with build_opener(NoRedirect()).open(request,timeout=45) as response:
                expected=200
                if response.status!=expected:raise NarrationError('Provider request failed.')
                limit=MAX_AUDIO if method=='POST' else 2*1024*1024
                data=response.read(limit+1)
                if len(data)>limit:raise NarrationError('Provider response too large.')
                content_type=response.headers.get_content_type()
                if method=='POST':
                    if content_type!='audio/mpeg' or not data:raise NarrationError('Audio response invalid.')
                    return data
                if content_type!='application/json':raise NarrationError('Provider response invalid.')
                return json.loads(data.decode('utf-8'))
        except NarrationError:
            raise
        except (HTTPError, URLError, OSError, ValueError):
            # Never inspect/reflect provider body, headers, URL or exception text.
            raise NarrationError('Provider request failed.') from None

def identifier(value):
    if not isinstance(value,str) or not IDENTIFIER.fullmatch(value):
        raise NarrationError('Invalid voice/model selection.')
    return value

def usage(subscription):
    if not isinstance(subscription,dict):raise NarrationError('Subscription response invalid.')
    return {key: subscription[key] for key in ('character_count','character_limit')
            if type(subscription.get(key)) is int and subscription[key]>=0}

def inspect_provider(transport):
    models=transport.request('GET','/v1/models')
    voices=transport.request('GET','/v1/voices')
    subscription=transport.request('GET','/v1/user/subscription')
    if not isinstance(models,list) or not isinstance(voices,dict) or not isinstance(voices.get('voices'),list):
        raise NarrationError('Provider catalog invalid.')
    model_ids=[]; offered=[]
    for model in models:
        if isinstance(model,dict) and model.get('can_do_text_to_speech') is True and isinstance(model.get('model_id'),str) and IDENTIFIER.fullmatch(model['model_id']):
            model_ids.append(model['model_id'])
    for voice in voices['voices']:
        # Only existing provider premade voices. No cloning/custom/community voices.
        if isinstance(voice,dict) and voice.get('category')=='premade' and isinstance(voice.get('voice_id'),str) and IDENTIFIER.fullmatch(voice['voice_id']):
            offered.append({'voice_id':voice['voice_id'],'category':'premade'})
    return {'models':model_ids,'premade_voices':offered,'usage':usage(subscription),
            'preferred_model':'eleven_multilingual_v2' if 'eleven_multilingual_v2' in model_ids else None}

def select(catalog, voice_id, model_id):
    identifier(voice_id);identifier(model_id)
    if voice_id not in [v['voice_id'] for v in catalog['premade_voices']] or model_id not in catalog['models']:
        raise NarrationError('Requested existing premade voice/model unavailable.')
    return voice_id,model_id

def validate_text(text):
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_CHARS or any(ord(c)<32 and c not in '\n\t' for c in text):
        raise NarrationError('Narration must contain 1–4000 valid characters.')
    return text

def generate(transport,text,voice_id,model_id,approved=False):
    validate_text(text)
    if approved is not True:raise NarrationError('Explicit generation approval required.')
    catalog=inspect_provider(transport)
    select(catalog,voice_id,model_id)
    # Exactly one POST. Never retry on errors/timeouts/uncertain charge outcome.
    audio=transport.request('POST','/v1/text-to-speech/'+voice_id,
                            {'text':text,'model_id':model_id})
    if not isinstance(audio,bytes) or not audio or len(audio)>MAX_AUDIO:
        raise NarrationError('Audio response invalid.')
    try:after=usage(transport.request('GET','/v1/user/subscription'))
    except NarrationError:after={}
    before=catalog['usage']
    receipt={'action':'one_narration_generation','characters_requested':len(text),
             'model_id':model_id,'voice_category':'premade','usage_before':before,'usage_after':after,
             'limits':'Usage reflects account counters; not a billing guarantee. No automatic POST retries.'}
    if 'character_count' in before and 'character_count' in after:
        receipt['character_count_delta']=after['character_count']-before['character_count']
    return audio,receipt

def output_directory():
    # Fixed local ignored destination. Never follow parent links or overwrite outputs.
    target=ROOT
    for part in ('video','public','media'):
        target=target/part
        try:target.mkdir(mode=0o700)
        except FileExistsError:pass
        info=target.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise NarrationError('Unsafe local output directory.')
    for name in ('narration.mp3','narration-receipt.json'):
        if os.path.lexists(target/name):raise NarrationError('Local output already exists; generation refused.')
    return target

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--inspect',action='store_true')
    mode.add_argument('--generate',action='store_true')
    parser.add_argument('--voice-id');parser.add_argument('--model-id',default='eleven_multilingual_v2')
    parser.add_argument('--approve-generation',action='store_true')
    args=parser.parse_args(argv)
    try:
        text=validate_text((ROOT/'video/narration.txt').read_text(encoding='utf-8'))
        if not args.inspect and not args.generate:
            print(json.dumps({'mode':'dry-run','characters':len(text),'words':len(text.split()),'network':False,'key_read':False}))
            return 0
        if args.generate and (not args.approve_generation or not args.voice_id):
            raise NarrationError('Explicit approval and reviewed voice selection required.')
        directory=output_directory() if args.generate else None
        # Only these intentional operations read this one environment variable.
        transport=HTTPS(os.environ.get('ELEVENLABS_API_KEY',''))
        if args.inspect:
            print(json.dumps(inspect_provider(transport),indent=2));return 0
        audio,receipt=generate(transport,text,args.voice_id,args.model_id,approved=True)
        for name,blob in [('narration.mp3',audio),('narration-receipt.json',json.dumps(receipt,indent=2).encode())]:
            descriptor=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(descriptor,'wb') as stream:stream.write(blob)
        print('Narration saved locally; sanitized usage receipt saved. No publication.');return 0
    except (NarrationError,OSError,ValueError):
        print('Narration operation refused or failed. Check local setup/selection; no provider details exposed. Do not automatically retry generation.')
        return 1

if __name__=='__main__':
    raise SystemExit(main())
