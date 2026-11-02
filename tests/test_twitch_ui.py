"""Run actual vanilla control JS with fake fetch/navigation/DOM in native JSCore.

Uses Python stdlib ctypes and installed macOS JavaScriptCore; no browser network,
UI automation, packages or credentials. Canvas visual QA is outside this test.
"""
import ctypes
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parent.parent
AUTH_URL='https://id.twitch.tv/oauth2/authorize?'+urlencode({
    'client_id':'FAKECLIENT123','redirect_uri':'http://localhost:8000/auth/twitch/callback',
    'response_type':'code','scope':'user:read:chat','state':'FAKE_STATE_'+'x'*33})

class ControlJSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform!='darwin':raise unittest.SkipTest('Native JavaScriptCore tests require macOS')
        cls.js=ctypes.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
        signatures={
            'JSGlobalContextCreate':([ctypes.c_void_p],ctypes.c_void_p),
            'JSGlobalContextRelease':([ctypes.c_void_p],None),
            'JSStringCreateWithUTF8CString':([ctypes.c_char_p],ctypes.c_void_p),
            'JSStringRelease':([ctypes.c_void_p],None),
            'JSEvaluateScript':([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)],ctypes.c_void_p),
            'JSValueToStringCopy':([ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)],ctypes.c_void_p),
            'JSStringGetMaximumUTF8CStringSize':([ctypes.c_void_p],ctypes.c_size_t),
            'JSStringGetUTF8CString':([ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t],ctypes.c_size_t)}
        for name,(args,result) in signatures.items():
            method=getattr(cls.js,name);method.argtypes=args;method.restype=result
        cls.source=(ROOT/'static/twitch-ui.js').read_text()

    def setUp(self):
        self.context=self.js.JSGlobalContextCreate(None)
        self.addCleanup(self.js.JSGlobalContextRelease,self.context)

    def value(self,value):
        string=self.js.JSValueToStringCopy(self.context,value,None)
        try:
            buffer=ctypes.create_string_buffer(self.js.JSStringGetMaximumUTF8CStringSize(string))
            self.js.JSStringGetUTF8CString(string,buffer,len(buffer))
            return buffer.value.decode()
        finally:self.js.JSStringRelease(string)

    def evaluate(self,code):
        string=self.js.JSStringCreateWithUTF8CString(code.encode())
        exception=ctypes.c_void_p()
        try:result=self.js.JSEvaluateScript(self.context,string,None,None,1,ctypes.byref(exception))
        finally:self.js.JSStringRelease(string)
        if exception.value:self.fail(self.value(exception.value))
        return self.value(result)

    def run_js(self,script):
        harness='''
          const AUTH_URL=AUTH_PLACEHOLDER;
          let calls=[],navigations=[],views=[],errorBodyReads=0;
          let statusData={ready:true,authenticated:false,connected:false,transport_enabled:true,
            transport_status:'disabled',csrf:'C'.repeat(43),access_token:'PRIVATE_NOT_FOR_UI'};
          let replies={};
          const check=(condition,label)=>{if(!condition)throw Error(label);};
          const fakeFetch=async(path,options={})=>{
            calls.push({path,options});
            if(path==='/api/twitch/status')return {ok:true,json:async()=>({...statusData})};
            if(replies[path])return replies[path](options);
            if(path==='/auth/twitch/start')return {ok:true,json:async()=>({authorization_url:AUTH_URL})};
            if(path==='/api/twitch/connect')statusData.transport_status='connecting';
            if(path==='/api/twitch/disconnect'){statusData.connected=false;statusData.transport_status='stopped';}
            if(path==='/auth/twitch/disconnect'){statusData.authenticated=false;statusData.csrf='D'.repeat(43);}
            return {ok:true,json:async()=>({connected:false})};
          };
          const make=(origin='http://localhost:8000')=>ChatTwitch.createControls({origin,fetch:fakeFetch,
            navigate:url=>navigations.push(url),view:model=>views.push(model)});
        '''.replace('AUTH_PLACEHOLDER',json.dumps(AUTH_URL))
        self.evaluate(self.source+'\n'+harness+"\nglobalThis.__result='PENDING';\n(async()=>{"+script+"})().then(()=>{__result='PASS'},error=>{__result='FAIL: '+String(error)});")
        self.assertEqual(self.evaluate('__result'),'PASS')

    def test_refresh_and_default_disabled_never_initiate_auth_or_connect(self):
        self.run_js('''const c=make();check(calls.length===0,'construction does no I/O');
          statusData.ready=false;await c.refresh();await c.authorize();await c.connect();
          check(calls.every(call=>call.path==='/api/twitch/status'),'only status reads');
          check(navigations.length===0,'no auth navigation');
          check(views.every(v=>!v.connected),'no false connection');
          check(!JSON.stringify(views).includes('PRIVATE'),'status extras not rendered');''')

    def test_authorize_click_posts_fresh_csrf_and_navigates_only_official_url(self):
        self.run_js('''const c=make();await c.refresh();
          statusData.csrf='F'.repeat(43);await c.authorize();
          const posts=calls.filter(call=>call.options.method==='POST');
          check(posts.length===1&&posts[0].path==='/auth/twitch/start','intentional auth POST');
          check(posts[0].options.headers['X-CSRF-Token']==='F'.repeat(43),'fresh session csrf');
          check(posts[0].options.credentials==='same-origin','host cookie');
          check(posts[0].options.body==='{}','no browser token/secret upload');
          check(navigations.length===1&&navigations[0]===AUTH_URL,'official navigation only');
          check(!calls.some(call=>call.path==='/api/twitch/connect'),'no automatic connect');''')

    def test_host_and_bad_authorization_targets_cannot_navigate(self):
        self.run_js('''const wrong=make('http://127.0.0.1:8000');await wrong.refresh();await wrong.authorize();
          check(calls.length===0&&navigations.length===0,'canonical local origin only');
          for(const bad of [AUTH_URL.replace('https:','http:'),AUTH_URL.replace('id.twitch.tv','evil.invalid'),
            AUTH_URL.replace('id.twitch.tv','id.twitch.tv.evil.invalid'),AUTH_URL+'#fragment',
            AUTH_URL+'\\n',AUTH_URL+'&scope=user%3Aread%3Aemail',AUTH_URL+'&access_token=PRIVATE',
            AUTH_URL.replace('user%3Aread%3Achat','chat%3Aedit'),
            AUTH_URL.replace('localhost%3A8000','localhost%3A8080'),
            AUTH_URL.replace('localhost%3A8000','evil.invalid'),AUTH_URL.replace('response_type=code','response_type=token')]){
            let rejected=false;try{ChatTwitch.authorizationURL(bad);}catch(_){rejected=true;}
            check(rejected,'reject unauthorized URL');
          }
          replies['/auth/twitch/start']=()=>({ok:true,json:async()=>({authorization_url:'https://evil.invalid/?code=PRIVATE'})});
          const c=make();await c.authorize();check(navigations.length===0,'malicious response never navigates');
          check(!JSON.stringify(views).includes('PRIVATE'),'never render response URL');''')

    def test_missing_csrf_and_provider_error_body_stay_sanitized(self):
        self.run_js('''const c=make();statusData.csrf='invalid';await c.authorize();
          check(!calls.some(call=>call.options.method==='POST'),'missing csrf blocks');
          statusData.csrf='C'.repeat(43);
          replies['/auth/twitch/start']=()=>({ok:false,json:async()=>{errorBodyReads++;return {error:'PRIVATE_PROVIDER_BODY'};}});
          await c.authorize();check(errorBodyReads===0,'error body not read');
          check(!JSON.stringify(views).includes('PRIVATE'),'no error reflection');check(navigations.length===0,'no navigation');''')

    def test_oauth_and_transport_states_connect_disconnect_logout(self):
        self.run_js('''const c=make();statusData.authenticated=true;await c.refresh();
          check(views.at(-1).authenticated&&!views.at(-1).connected&&views.at(-1).canConnect,'separate auth/chat states');
          await c.connect();check(!views.at(-1).connected&&!views.at(-1).canConnect,'request is not ack');
          statusData.connected=true;statusData.transport_status='connected';await c.refresh();
          check(views.at(-1).connected&&views.at(-1).canDisconnect,'verified status');
          await c.disconnect();check(!views.at(-1).connected&&views.at(-1).authenticated,'disconnect keeps auth');
          await c.logout();check(!views.at(-1).authenticated,'local logout');
          check(calls.filter(call=>call.options.method==='POST').map(call=>call.path).join(',')===
            '/api/twitch/connect,/api/twitch/disconnect,/auth/twitch/disconnect','protected lifecycle paths');''')

    def test_mount_wires_user_clicks_and_only_polls_status(self):
        self.run_js('''const nodes={},intervals=[];
          const doc={getElementById:id=>nodes[id]||(nodes[id]={disabled:true,listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}})};
          const win={location:{origin:'http://localhost:8000',assign:url=>navigations.push(url)},fetch:fakeFetch,
            setInterval:fn=>intervals.push(fn)};
          ChatTwitch.mount(doc,win);await Promise.resolve();await Promise.resolve();
          check(intervals.length===1,'one status timer');
          check(calls.every(call=>call.path==='/api/twitch/status'),'mount never starts auth/connect');
          check(nodes.twitchAuthorize.listeners.click,'intentional authorize listener');
          await nodes.twitchAuthorize.listeners.click();
          check(navigations.length===1,'click invokes auth');
          check(nodes.twitchOAuthStatus.textContent==='Ready — authorization required','separate OAuth label');
          check(nodes.twitchTransportStatus.textContent==='Not connected','honest transport label');''')

    def test_backend_loss_clears_connection_and_disables_every_action_until_fresh_status(self):
        self.run_js('''const c=make();statusData.authenticated=true;statusData.connected=true;await c.refresh();
          c.setBackendAvailable(false);const model=views.at(-1);
          check(!model.known&&!model.connected&&!model.canAuthorize&&!model.canConnect&&!model.canDisconnect&&!model.canLogout,'offline controls');
          const before=calls.length;await c.connect();await c.authorize();check(calls.length===before,'offline actions do nothing');
          c.setBackendAvailable(true);await c.refresh();check(views.at(-1).known&&views.at(-1).connected,'fresh backend status recovers');''')

    def test_receipts_distinguish_subscription_delivery_and_vote_without_raw_chat(self):
        self.run_js('''const c=make();statusData.connected=true;statusData.subscription_acks=1;await c.refresh();
          check(views.at(-1).note.includes('unverified'),'ack not delivery');
          statusData.validated_notifications=1;statusData.receipts=[{outcome:'not_command',action:'PRIVATE_RAW_CHAT',round:1,mission:1,body:'PRIVATE_PROVIDER',chatter:'PRIVATE_ID'}];await c.refresh();
          check(views.at(-1).accepted_votes===0&&views.at(-1).note.includes('no accepted vote'),'delivery not vote');
          check(!JSON.stringify(views).includes('PRIVATE'),'safe evidence fields only');
          statusData.accepted_votes=1;statusData.receipts=[{outcome:'accepted',action:'supply',round:1,mission:1}];await c.refresh();
          check(views.at(-1).accepted_votes===1&&views.at(-1).receipts[0].action==='supply','accepted proof');''')

    def test_preflight_and_actual_impact_explain_timing_without_changing_rules(self):
        self.run_js('''check(ChatTwitch.preflight(null,false).includes('not paused'),'offline not pause');
          check(ChatTwitch.preflight({status:'ready',transport_enabled:true,connected:false},true).includes('before deployment'),'live preflight');
          check(ChatTwitch.preflight({status:'ready',connected:true},true).includes('7-second'),'voting timing');
          const text=ChatTwitch.impact({round:1,action:'supply',reason:'most_votes',battery_delta:1,oxygen_delta:-6,route_before:14,route_after:18,counts:{north:0,scan:0,supply:2},effect:'South opened.'});
          check(text.includes('+1%')&&text.includes('-6s')&&text.includes('14 → 18')&&text.includes('supply 2'),'actual capped effects');''')

    def test_retry_and_stopping_controls_are_actionable(self):
        self.run_js('''const c=make();statusData.authenticated=true;statusData.transport_status='reconnecting';statusData.can_connect=false;
          statusData.retry_count=2;statusData.retry_limit=5;statusData.retry_in_seconds=2;await c.refresh();
          check(!views.at(-1).canConnect&&views.at(-1).canDisconnect&&views.at(-1).note.includes('2/5'),'bounded retry');
          statusData.transport_status='stopped';statusData.transport_stopping=true;await c.refresh();
          check(!views.at(-1).canConnect&&views.at(-1).note.includes('Stopping'),'wait for thread');
          statusData.transport_stopping=false;statusData.can_connect=true;await c.refresh();check(views.at(-1).canConnect,'safe retry');''')

    def test_dashboard_disables_game_controls_offline_and_recovers_without_auto_actions(self):
        from game import Game
        snapshot=Game(clock=lambda:0).snapshot()
        source=(ROOT/'static/app.js').read_text()
        harness='''
          var networkDown=true,posts=0,timers=[];
          const nodes={};const makeNode=()=>({style:{},disabled:false,hidden:false,textContent:'',value:'pilot',scrollHeight:0,
            getContext:()=>({}),addEventListener(){},setAttribute(){},replaceChildren(){},append(){}});
          const document={getElementById:id=>nodes[id]||(nodes[id]=makeNode()),createElement:()=>makeNode(),createTextNode:text=>({textContent:text})};
          globalThis.window=globalThis;window.location={origin:'http://localhost:8000',assign(){throw Error('No navigation');}};
          const setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};const clearTimeout=()=>{};
          const setInterval=()=>1;const requestAnimationFrame=()=>{};
          let snapshot=SNAPSHOT;
          const fetch=async(path,options={})=>{
            if(options.method==='POST')posts++;
            if(networkDown)throw Error('offline');
            return {ok:true,json:async()=>path==='/api/state'?snapshot:{csrf:'C'.repeat(43),ready:false,connected:false}};
          };
          window.fetch=fetch;window.setInterval=setInterval;
        '''.replace('SNAPSHOT',json.dumps(snapshot))
        self.evaluate(self.source+'\n'+harness+'\n'+source)
        self.assertEqual(self.evaluate("String(nodes.start.disabled&&nodes.restart.disabled&&nodes.viewer.disabled)"),'true')
        self.assertEqual(self.evaluate("String(nodes.chatMode.textContent.includes('OFFLINE'))"),'true')
        self.evaluate("networkDown=false;globalThis.__done='PENDING';poll().then(()=>{__done=String(!nodes.start.disabled&&!nodes.restart.disabled&&posts===0)});")
        self.assertEqual(self.evaluate('__done'),'true')
        self.evaluate("snapshot.transport_enabled=true;snapshot.connected=false;poll();")
        self.assertEqual(self.evaluate('String(nodes.start.disabled)'),'true')
        self.evaluate("networkDown=true;poll();")
        self.assertEqual(self.evaluate('String(nodes.start.disabled&&nodes.restart.disabled&&posts===0)'),'true')

    def test_main_js_syntax_and_no_persistent_secret_storage(self):
        app=(ROOT/'static/app.js').read_text()
        self.evaluate('new Function('+json.dumps(app)+');')
        for forbidden in ('localStorage','sessionStorage','console.'):
            self.assertNotIn(forbidden,self.source)
        html=(ROOT/'static/index.html').read_text()
        self.assertLess(html.index('src="/twitch-ui.js"'),html.index('src="/app.js"'))
        for control in ('twitchAuthorize','twitchConnect','twitchDisconnect','twitchLogout'):
            self.assertIn('id="'+control+'" disabled',html)

if __name__ == '__main__':unittest.main()
