# Manual recording — planned, no footage recorded

Coordinator verified actual Twitch vote/rescue and desktop screenshots, but no video exists. Screenshot.app and QuickTime.app are installed. The coordinator-checked [Apple recording guide](https://support.apple.com/en-gb/102618) supports selected-portion capture and QuickTime. Available CUA captures screenshots only; screencapture help lists video flags but **safe automated video capture has not been verified**. Terminal UI control was denied; do not retry it or change permissions.

1. User presses **Shift–Command–5**, chooses **Record Selected Portion**, and selects only the safe game canvas/operator counters and actual channel content. Arrange/crop out browser chrome, private tabs, unrelated chat, account details, auth/login/callback UI, developer tools, credentials, network panels and logs. If isolation is unsafe, stop and leave recording pending. Microphone is optional only with existing permission; do not request/change permission.
2. Choose a user-owned local save folder in Options, then Record. Preserve PID2191 and the completed mission. Record its result honestly; arrange any later new live round deliberately rather than silently resetting it. Follow the [2:50 storyboard](DEMO_SCRIPT.md), including uninterrupted real command → accepted tally → round consequence. Never substitute simulation or screenshots for video evidence. Recovery is unverified live: discuss limits instead of claiming it works from footage not captured.
3. Stop with **Command–Control–Esc**. Keep the local `.mov` in the chosen user folder, outside the source package. Review the whole clip for private UI/audio before any separately approved export/share. No upload/publication is authorized.

## Genuine existing-session Codex segment

After this turn finishes and the session is idle, the user may resume **only the original session** in a separate Terminal from the still-running game server:

```sh
cd /Users/balakrishnanayyanar/Documents/Codex/2026-10-30/task
codex -m gpt-6.1-sol -c 'model_reasoning_effort="medium"' -s workspace-write -a never resume 01a18a9f-83b7-7dc2-9144-78711c379fd4
```

No additional Codex CLI writer/session should remain active at handoff. Do not start a parallel writer. Invoke **`/status`** and record its actual supported session/model/reasoning output; never fabricate missing fields. Crop private paths/account data. Ask the same session to review the actual timestamp fix and, if wanted, run the genuine fake-data tests while recording. Clearly label this **later same-session follow-up review/testing**, not footage from the original implementation. No historical footage is known. Example future test command (not run by this packaging turn): `.venv/bin/python -m unittest discover -s tests -v`. Do not open private storage, provider logs or auth screens for proof.

Repository destination is https://github.com/Balakrishnan-Ayyanar/twitch-game (coordinator commit/push approved, publication pending). Accessible **public or unlisted YouTube** URL remains pending. Logs/session IDs/screenshots alone do not fulfill the planned video evidence. No automated recording, permission change or publishing was performed here. Local Remotion Draft source is now prepared in video/; it is not genuine recorded footage.
