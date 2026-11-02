import React from 'react';
import {AbsoluteFill, Audio, Composition, OffthreadVideo, Sequence, interpolate, registerRoot, staticFile, useCurrentFrame} from 'remotion';
import {CHAPTERS, FPS, SECONDS, validateProps} from './protocol.mjs';
const h=React.createElement;
const ink='#edf9f5', muted='#a4b8c6', mint='#71f5bd';
const base={backgroundColor:'#081321',color:ink,fontFamily:'system-ui, sans-serif'};
const copy={
 hook:['VERIFIED RESULT','Crew delivered · 25.0 seconds','Coordinator-observed result, not recreated gameplay'],
 explain:['COMMUNITY CONTROL','!north  /  !scan  /  !supply','Read-only Twitch chat · seven-second voting rounds'],
 vote:['ACTUAL LIVE EVIDENCE','2 validated notifications · 1 accepted vote','Ready-state supply: not_running → fresh round-one supply: accepted'],
 rescue:['ONE SUPPLY RESOLUTION','+22 battery · −6 oxygen · route recalculated','Won carrying crew · final battery 12 / oxygen 34'],
 limits:['VALIDATED IMPLEMENTATION','100 full tests passed · no skips','98 separate socket-free · compile passed · desktop screenshots checked'],
 codex:['Built with Codex','One persistent session · gpt-6.1-sol / medium','Later timestamp-fix review / tests / actual /status; not historical build footage'],
 recap:['CHAT MISSION CONTROL','One rover. A stranded crew. Chat chooses the way home.','Read chat only · Python-authoritative game · vanilla canvas'],
};
function Chapter({chapter,draft,props}) {
 const frame=useCurrentFrame();
 const opacity=chapter.id==='vote'?1:interpolate(frame,[0,12],[0,1],{extrapolateRight:'clamp'});
 const lines=copy[chapter.id];
 const footage=chapter.id!=='limits';
 const clip=chapter.id==='codex'?props.codex:props.gameChat;
 return h(AbsoluteFill,{style:{...base,padding:'76px 90px',opacity}},
   h('div',{style:{fontSize:22,letterSpacing:5,color:mint}},`CHAT MISSION CONTROL  /  ${lines[0]}`),
   h('h1',{style:{fontSize:57,margin:'22px 0 30px',lineHeight:1.12}},chapter.title),
   footage && !draft ? h('div',{style:{height:650,background:'#030a12',border:'1px solid #365569',borderRadius:18,overflow:'hidden'}},
     h(OffthreadVideo,{src:staticFile(clip.file),startFrom:Math.round(props.starts[chapter.id]*FPS),muted:true,style:{width:'100%',height:'100%',objectFit:'contain'}})) :
     h('div',{style:{height:600,border:'2px solid #365569',borderRadius:24,padding:60,display:'flex',flexDirection:'column',justifyContent:'center',background:'linear-gradient(130deg,#112b3a,#0a182b)'}},
       h('div',{style:{color:mint,fontSize:40,fontWeight:700}},lines[1]),
       h('p',{style:{color:muted,fontSize:31,lineHeight:1.5,maxWidth:1450}},lines[2]),
       h('p',{style:{fontSize:26,lineHeight:1.5,color:footage?'#ffc88c':muted}},footage?'MISSING FOOTAGE — genuine local recording not supplied. This card is evidence graphics, not gameplay or chat footage.':'Python-authoritative state · BFS path planning · one vote per viewer per round · strict timestamp parsing and regression coverage.')),
   h('div',{style:{position:'absolute',bottom:76,left:90,right:90,fontSize:23,color:muted}},!draft&&footage?`${lines[1]}${chapter.id==='codex'?' · Later same-session follow-up':''}`:'Coordinator-curated live evidence · 2026-11-02 14:31:30 UTC'),
   h('div',{style:{position:'absolute',bottom:46,left:90,right:90,height:4,background:'#243e4d'}},h('div',{style:{height:4,width:`${100*(chapter.start+frame/FPS)/SECONDS}%`,background:mint}})));
}
function Demo({draft,...props}) {
 validateProps(props,!draft);
 return h(AbsoluteFill,{style:base},
   ...CHAPTERS.map(chapter=>h(Sequence,{key:chapter.id,from:chapter.start*FPS,durationInFrames:(chapter.end-chapter.start)*FPS},h(Chapter,{chapter,draft,props}))),
   props.narration?h(Audio,{src:staticFile(props.narration),volume:1}):null,
   draft?h('div',{style:{position:'absolute',right:36,top:20,padding:'12px 22px',background:'#6c2b18',border:'2px solid #ffb17c',color:'#fff',fontSize:23,fontWeight:800,zIndex:100}},'DRAFT · GENUINE FOOTAGE PENDING'):null);
}
function Root(){return h(React.Fragment,null,
 h(Composition,{id:'Draft',component:props=>h(Demo,{...props,draft:true}),durationInFrames:FPS*SECONDS,fps:FPS,width:1920,height:1080,defaultProps:{}}),
 h(Composition,{id:'Final',component:props=>h(Demo,{...props,draft:false}),durationInFrames:FPS*SECONDS,fps:FPS,width:1920,height:1080,defaultProps:{}}));}
registerRoot(Root);
