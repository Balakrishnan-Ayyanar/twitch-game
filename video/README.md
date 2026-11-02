# Local demo project — draft, not submission-ready

1920×1080,30fps,5100frames (**170seconds**), seven chapters matching `submission/DEMO_SCRIPT.md`. JavaScript/React source only. Exact pins: **remotion + @remotion/cli4.0.540**, **react + react-dom19.3.1**. No fonts, music, remote assets or additional packages. Native system font and code-native evidence cards only. Node runtime supplied by coordinator:24.22.2; npm11.19.1. No npm install/provider call/render occurred in this coding turn.

## Coordinator install / local preview / render

Coordinator completed the pinned official-npm install with lifecycle scripts disabled; `package-lock.json` now exists and is in the explicit source manifest. The supplied runtime is `/tmp/chat-mission-video-runtime/node-v24.22.2-darwin-arm64/bin` on PATH. Run from `video/`. Review exact dependency resolutions and generated **package-lock.json** before committing; all installed Remotion packages must match4.0.540. Lockfile/source staging review remains coordinator-owned. Do not let npm pick `latest` or add dependencies. Package install/browser provisioning is coordinator work; if the renderer needs a browser, stop for coordinator review rather than silently adding a package or changing permissions.

After coordinator review of the installed dependencies:

```sh
npm test
node --check src/index.js
npm run studio
npm run render:draft
```

Use only the Draft composition for the preview. `out/draft.mp4` carries a persistent **DRAFT · GENUINE FOOTAGE PENDING** watermark and explicit missing-footage cards. Narration does not turn this into real footage. Result cards describe the curated live observation; they do not recreate chat/gameplay. No actual render is verified until coordinator runs it.

## ElevenLabs — intentional operator operations only

Public script: `narration.txt` (**314words /2084characters**, max4000). Review wording and the account's current terms/licence first. The helper offers only existing `premade` voices and TTS-capable models; it does not certify licensing, clone/create voices or create keys. Prefer `eleven_multilingual_v2` only if offered. No credit limit is imposed beyond this one modest text-size cap.

From the workspace root, using the operator's ordinary interactive shell where the existing key is already available:

```sh
.venv/bin/python tools/elevenlabs_narration.py --dry-run
.venv/bin/python tools/elevenlabs_narration.py --inspect
```

Dry-run/default never reads the key or accesses the network. Inspect intentionally reads only `ELEVENLABS_API_KEY` from that process environment; prints offered safe model/voice IDs and allowlisted usage counters, not the key or raw catalog. No shell files are read by the helper. Do not print/dump env, paste the key, pass it as an argument, source shell files through Codex or expose it to a browser/video. Current executor key absence must not be worked around by reading private files.

Coordinator privately inspected the provider: `eleven_multilingual_v2` is offered and21premade voices are available. No narration has been generated. After coordinator reviews the polished script, selects an offered **existing premade voice licensed for this use**, and confirms the offered model, run once (replace only the public voice ID):

```sh
.venv/bin/python tools/elevenlabs_narration.py --generate --approve-generation --voice-id REVIEWED_VOICE_ID --model-id eleven_multilingual_v2
```

HTTPS is restricted to `api.elevenlabs.io`, verified TLS, no redirects, no automatic POST retries or reflected provider errors. Generation performs catalog/subscription GETs, **one POST**, then an optional usage GET. Files are ignored `public/media/narration.mp3` and `narration-receipt.json`; receipt includes requested characters and before/after account character_count/delta if available, not a billing guarantee. Existing outputs are refused before provider access. On an uncertain POST failure, stop and check account usage manually; do not blindly repeat. No narration has been generated yet.

## Final composition — reviewed genuine clips required

Follow `../submission/RECORDING.md`; recording remains pending. Preserve PID2191 and its completed mission. Do not reset Twitch/game or stage a simulated vote as a real one. Same-session Codex clip must show the original session and genuine **later** timestamp-fix review/tests and `/status`, not pretend to be historical build footage.

Human-review/crop local clips to exclude private UI, auth, credentials and logs. Put only those reviewed clips in ignored `public/media/game-chat.mp4` and `public/media/codex.mp4` (MOV also allowed). Copy `reviewed-props.example.json` to ignored `reviewed-props.json`. Replace measured durations and per-chapter source offsets in seconds, aligned to1/30second; set attestations true **only after review**. Never infer timestamps from the old live check. The40-second vote chapter uses one continuous clip, with no internal cuts, speed change or fade. The game/chat clip must actually contain the complete command→accepted vote→round consequence chain. Other offsets may reuse genuine result footage, honestly.

The limits chapter uses truthful evidence graphics, not staged recovery. For optional narration add `"narration":"media/narration.mp3"` and measured `"narrationSeconds"` no greater than170. Listen/review timing, silent gaps and chapter alignment; no automatic stretching or fabricated sync. Clip audio is muted so only the optional reviewed narration plays. The product narration contains no spoken production instructions; Draft watermark/cards and readiness docs retain the missing-footage/verification disclosures. The planned Codex footage caption remains **genuine later same-session follow-up**, never recreated historical footage.

```sh
npm run render:final -- reviewed-props.json
```

Final refuses absent/unreviewed/unsafe local clips, missing duration/offsets or attestations; local wrapper verifies both files before invoking Remotion. Direct Final composition also validates props and fails on missing media. Human attestations are a review gate, **not automated proof of authenticity**. No final footage exists yet. Generated media, receipts, review props, output and node_modules are excluded from Git/source archive. No YouTube/Devpost upload/submission is authorized.
