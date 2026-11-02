/* Read-only operator controls. CSRF/status stay in closure memory, never storage/logs. */
(function(root){
  'use strict';
  const ORIGIN='http://localhost:8000';
  function authorizationURL(raw){
    if(typeof raw!=='string'||raw.length>4096||/[\u0000-\u0020\u007f]/.test(raw))throw Error('Authorization unavailable.');
    // Deliberately accept only our backend's exact official URL grammar, not a
    // general URL or a provider-supplied redirect. Decoding is query-only.
    const match=/^https:\/\/id\.twitch\.tv\/oauth2\/authorize\?([A-Za-z0-9_.~%+&=-]+)$/.exec(raw);
    if(!match)throw Error('Authorization unavailable.');
    const q=Object.create(null),keys=['client_id','redirect_uri','response_type','scope','state'];
    for(const part of match[1].split('&')){
      const pair=part.split('=');
      if(pair.length!==2||!keys.includes(pair[0])||Object.prototype.hasOwnProperty.call(q,pair[0]))throw Error('Authorization unavailable.');
      q[pair[0]]=decodeURIComponent(pair[1].replace(/\+/g,' '));
    }
    if(Object.keys(q).length!==keys.length||!/^[A-Za-z0-9_-]{1,256}$/.test(q.client_id)||q.response_type!=='code'||
       q.redirect_uri!==ORIGIN+'/auth/twitch/callback'||q.scope!=='user:read:chat'||
       !/^[A-Za-z0-9_-]{32,128}$/.test(q.state))throw Error('Authorization unavailable.');
    return raw;
  }

  const outcomes={accepted:'vote accepted',duplicate:'duplicate delivery ignored',stale_round:'closed round ignored',
    not_running:'mission not running — no vote',not_command:'non-command received — no vote',already_voted:'viewer already voted',rejected:'vote rejected'};
  const count=value=>Number.isInteger(value)&&value>=0?value:0;
  function preflight(game,available){
    if(!available)return 'Backend unavailable. Displayed state is stale; mission time is not paused. Start the server in your own Terminal, keep it open, then retry status.';
    if(!game)return 'Waiting for authoritative mission state.';
    if(game.status!=='ready')return game.status==='running'?'Voting is open for 7 seconds each round. Send one command per viewer; results apply at round close.':'Voting is closed. Prepare a new mission to try again.';
    if(game.transport_enabled&&!game.connected)return 'Live preflight: authorize and connect chat before deployment. Subscription alone does not prove message delivery.';
    return game.connected?'Ready: confirm viewers are watching, then deploy. The first 7-second round starts immediately; ask for !supply. A command before deployment tests delivery but cannot cast a vote.':'Simulated practice: deploy, then choose an action within 7 seconds. Vote supply early to keep the battery alive.';
  }
  function impact(decision){
    if(!decision)return 'No round resolved yet. The winning action changes the crossing and resources when the timer ends.';
    const reason={no_votes:'no votes → north default',tie:'tie → first listed option',most_votes:'most votes'}[decision.reason]||'round resolved';
    const sign=n=>(n>=0?'+':'')+n;
    const tally=decision.counts?' Tally '+['north','scan','supply'].map(action=>action+' '+count(decision.counts[action])).join(' / ')+'.':'';
    return 'Round '+decision.round+' · '+decision.action+' · '+reason+'.'+tally+' Battery '+sign(decision.battery_delta)+'%, oxygen '+sign(decision.oxygen_delta)+'s. Route '+decision.route_before+' → '+decision.route_after+' tiles. '+decision.effect;
  }
  function createControls(options){
    let status=null,csrf='',busy=false,externalAvailable=true,notice='',pending=null;
    const canonical=options.origin===ORIGIN;
    const active=()=>status&&(status.connected||status.transport_stopping||['connecting','reconnecting'].includes(status.transport_status));
    function recovery(){
      if(!canonical)return 'Open http://localhost:8000 to use protected read-only controls.';
      if(!externalAvailable||!status)return 'Backend unavailable. Start the server in your own Terminal and keep it open; then retry status. Displayed mission time is not paused.';
      if(!status.ready)return 'Live controls are disabled. Use --enable-twitch on localhost:8000, or play in simulated mode.';
      if(status.transport_stopping)return 'Stopping chat. Wait for the worker to finish before reconnecting.';
      if(status.transport_status==='authorization required')return 'Chat authorization failed or expired. Clear local authorization, authorize read-only chat again, then reconnect.';
      if(status.transport_status==='retry limit reached')return 'Automatic retries exhausted. Check your connection, then Connect chat to retry. Clear local authorization first if authorization was rejected.';
      if(status.transport_status==='reconnecting')return 'Chat interrupted: retry '+status.retry_count+'/'+status.retry_limit+' in '+status.retry_in_seconds+'s. Mission time keeps advancing; Disconnect stops retries.';
      if(status.connected&&status.validated_notifications===0)return 'Subscription connected; chat delivery is still unverified. Send a command from the actual channel to test receipt.';
      if(status.connected&&status.accepted_votes===0)return 'Chat delivery observed, but no accepted vote yet. Deploy, then send !supply during the open round.';
      return notice||'Only user:read:chat for balakrishnanayyanar. No posting, moderation or broadcast controls.';
    }
    function render(){
      const known=externalAvailable&&status!==null;
      options.view({canonical,known,ready:!!(known&&status.ready),authenticated:!!(known&&status.authenticated),
        connected:!!(known&&status.connected),transport_status:known?status.transport_status:'unavailable',note:recovery(),
        subscription_acks:known?status.subscription_acks:0,validated_notifications:known?status.validated_notifications:0,
        accepted_votes:known?status.accepted_votes:0,receipts:known?status.receipts:[],
        canAuthorize:!!(known&&canonical&&!busy&&status.ready&&!status.authenticated),
        canConnect:!!(known&&canonical&&!busy&&status.ready&&status.authenticated&&status.transport_enabled&&status.can_connect&&!active()),
        canDisconnect:!!(known&&canonical&&!busy&&active()),canLogout:!!(known&&canonical&&!busy&&status.authenticated)});
    }
    async function fetchBounded(path,init){
      const controller=typeof AbortController==='function'?new AbortController():null;
      const timer=controller?setTimeout(()=>controller.abort(),4000):null;
      try{const response=await options.fetch(path,{...init,...(controller?{signal:controller.signal}:{})});
        if(!response.ok)return {ok:false};
        const data=await response.json();return {ok:true,json:async()=>data};}
      finally{if(timer!==null)clearTimeout(timer);}
    }
    async function readStatus(){
      if(!canonical){status=null;csrf='';render();return;}
      const response=await fetchBounded('/api/twitch/status',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw Error('Status unavailable.');
      const data=await response.json();
      if(typeof data.csrf!=='string'||!/^[A-Za-z0-9_-]{32,128}$/.test(data.csrf))throw Error('Status unavailable.');
      csrf=data.csrf;
      status={ready:data.ready===true,authenticated:data.authenticated===true,connected:data.connected===true,
        transport_enabled:data.transport_enabled===true,transport_stopping:data.transport_stopping===true,
        can_connect:data.can_connect!==false,subscription_acks:count(data.subscription_acks),
        validated_notifications:count(data.validated_notifications),accepted_votes:count(data.accepted_votes),
        retry_count:count(data.retry_count),retry_limit:count(data.retry_limit),
        retry_in_seconds:typeof data.retry_in_seconds==='number'&&Number.isFinite(data.retry_in_seconds)?Math.max(0,data.retry_in_seconds):0,
        receipts:Array.isArray(data.receipts)?data.receipts.slice(-12).filter(r=>r&&outcomes[r.outcome]).map(r=>({
          outcome:r.outcome,action:['north','scan','supply'].includes(r.action)?r.action:null,round:count(r.round),mission:count(r.mission)})):[],
        transport_status:['disabled','connecting','connected','reconnecting','stopped','worker stopped','authorization required','retry limit reached'].includes(data.transport_status)?data.transport_status:'unavailable'};
      render();
    }
    async function refresh(){
      if(pending)return pending;
      pending=(async()=>{try{await readStatus();}catch(_){status=null;csrf='';render();}})();
      try{await pending;}finally{pending=null;}
    }
    async function perform(kind){
      if(busy||!canonical||!externalAvailable)return;
      busy=true;render();
      try{
        await readStatus();
        if(!status)throw Error();
        if(kind==='authorize'&&(!status.ready||status.authenticated))throw Error();
        if(kind==='connect'&&(!status.ready||!status.authenticated||!status.transport_enabled||!status.can_connect||active()))throw Error();
        if(kind==='disconnect'&&!active())throw Error();
        if(kind==='logout'&&!status.authenticated)throw Error();
        const paths={authorize:'/auth/twitch/start',connect:'/api/twitch/connect',disconnect:'/api/twitch/disconnect',logout:'/auth/twitch/disconnect'};
        const response=await fetchBounded(paths[kind],{method:'POST',credentials:'same-origin',cache:'no-store',
          headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}'});
        if(!response.ok)throw Error();
        const data=await response.json();
        if(kind==='authorize')options.navigate(authorizationURL(data.authorization_url));
        else notice=kind==='connect'?'Connection requested; wait for verified subscription acknowledgement.':kind==='logout'?'Local authorization cleared; no remote revocation performed.':'Chat disconnected; no messages were posted.';
      }catch(_){notice='Action did not complete. Retry status; if authorization expired, clear local authorization and authorize again.';}
      finally{busy=false;await refresh();}
    }
    return {refresh,authorize:()=>perform('authorize'),connect:()=>perform('connect'),disconnect:()=>perform('disconnect'),logout:()=>perform('logout'),
      setBackendAvailable(value){const changed=externalAvailable!==(value===true);externalAvailable=value===true;if(!externalAvailable){status=null;csrf='';}render();if(changed&&externalAvailable)refresh();}};
  }
  function mount(doc,win){
    const get=id=>doc.getElementById(id);
    const labels={'disabled':'Not connected','connecting':'Connecting — not verified yet','connected':'Verified subscription connected',
      'reconnecting':'Disconnected — retrying','stopped':'Disconnected','worker stopped':'Disconnected — retry available','authorization required':'Disconnected — authorize again',
      'retry limit reached':'Disconnected — retry limit reached','unavailable':'Status unavailable'};
    const controls=createControls({origin:win.location.origin,fetch:win.fetch.bind(win),navigate:url=>win.location.assign(url),view:model=>{
      get('twitchLocalLink').hidden=model.canonical;
      get('twitchOAuthStatus').textContent=!model.canonical?'Use localhost:8000':!model.known?'Status unavailable':model.authenticated?'Authorized for read-only chat':model.ready?'Ready — authorization required':'Disabled — start with --enable-twitch';
      get('twitchTransportStatus').textContent=model.connected?'Verified subscription connected':labels[model.transport_status]||'Not connected';
      get('twitchFeedback').textContent=model.note;
      for(const [id,key] of [['twitchAuthorize','canAuthorize'],['twitchConnect','canConnect'],['twitchDisconnect','canDisconnect'],['twitchLogout','canLogout']])get(id).disabled=!model[key];
      get('receiptAcks').textContent=model.known?String(model.subscription_acks):'—';
      get('receiptEvents').textContent=model.known?String(model.validated_notifications):'—';
      get('receiptVotes').textContent=model.known?String(model.accepted_votes):'—';
      const last=model.receipts.at(-1);
      get('receiptLast').textContent=last?'Mission '+last.mission+', round '+last.round+' · '+(last.action?'!'+last.action:'non-command')+' · '+outcomes[last.outcome]:model.known?'No validated chat notification received in this server process.':'Backend unavailable — evidence unknown.';
    }});
    for(const [id,action] of [['twitchAuthorize','authorize'],['twitchConnect','connect'],['twitchDisconnect','disconnect'],['twitchLogout','logout']])get(id).addEventListener('click',()=>controls[action]());
    get('twitchRefresh').addEventListener('click',()=>controls.refresh());
    controls.refresh();
    win.setInterval(()=>controls.refresh(),2000);
    return controls;
  }
  root.ChatTwitch={authorizationURL,createControls,mount,preflight,impact};
})(typeof window==='undefined'?globalThis:window);
