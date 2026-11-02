export const FPS = 30;
export const SECONDS = 170;
export const CHAPTERS = [
  [0,15,'One rover. A community. A rescue.','hook'],
  [15,30,'Three choices. Seven seconds.','explain'],
  [30,70,'Real chat → accepted vote → consequence','vote'],
  [70,100,'A choice that changes the journey','rescue'],
  [100,120,'What is proven. What remains.','limits'],
  [120,155,'Built in one persistent Codex session','codex'],
  [155,170,'Chat Mission Control','recap'],
].map(([start,end,title,id])=>({start,end,title,id}));
export const GAME_CHAPTERS = ['hook','explain','vote','rescue','recap'];
export function localMedia(value, extension) {
  if (typeof value !== 'string' || !new RegExp(`^media/[a-zA-Z0-9_-]+\\.${extension}$`).test(value)) {
    throw new Error('Only reviewed local media filenames are allowed.');
  }
  return value;
}
export function validateProps(props={}, final=false) {
  if (props.narration !== undefined) {
    localMedia(props.narration,'mp3');
    if (!Number.isFinite(props.narrationSeconds) || props.narrationSeconds<=0 || props.narrationSeconds>SECONDS) throw new Error('Review measured narration duration, at most 170 seconds.');
  }
  if (!final) return props;
  if (props.reviewed !== true) throw new Error('Final requires explicit human media review.');
  for (const key of ['gameChat','codex']) {
    const clip=props[key];
    if (!clip || clip.reviewed !== true) throw new Error('Final requires both reviewed genuine game/chat and same-session Codex clips.');
    localMedia(clip.file,'(?:mp4|mov)');
    if (!Number.isFinite(clip.durationSeconds) || clip.durationSeconds<=0) throw new Error('Measured clip duration required.');
  }
  if (props.gameChat.genuineLiveChat !== true || props.codex.sameOriginalSession !== true || props.codex.laterFollowup !== true) {
    throw new Error('Genuine live chat and original-session later follow-up attestations required.');
  }
  for (const chapter of CHAPTERS.filter(c=>c.id!=='limits')) {
    const clip=chapter.id==='codex'?props.codex:props.gameChat;
    const start=props.starts?.[chapter.id];
    if (!Number.isFinite(start) || start<0 || Math.round(start*FPS)!==start*FPS || start+chapter.end-chapter.start>clip.durationSeconds) {
      throw new Error(`Missing or out-of-bounds reviewed source offset: ${chapter.id}`);
    }
  }
  return props;
}
