# Chat Mission Control

One rover, one floodplain, three chat choices. A Python-authoritative rescue/delivery game with a responsive vanilla canvas map, visible routing, seven-second votes and explainable community impact. The default mode is clearly labeled simulated. Optional Twitch integration reads chat only (`user:read:chat`), never posts, moderates or controls a broadcast.

**Verified live milestone — 2026-11-02 14:31:30 UTC:** coordinator observed user-owned **PID 2191**, connected with **1 subscription acknowledgement, 2 validated notifications and 1 accepted vote**. In mission 1 / round 1, a real `!supply` first produced `not_running`, then a fresh command was accepted. Exactly one supply resolution applied **+22 battery / −6 oxygen** and recalculated the route; rounds 2 and 3 defaulted north without votes. The mission **won at 25.0s**, carrying the crew, with **12 battery / 34 oxygen**. [Curated sanitized evidence](evidence/live-vote-verified.json) retains this result, but **not the exact Round 1 route lengths or intermediate resource snapshots**. Earlier simulation route 9→11 is not live evidence. Preserve the running server and completed mission; no reset/restart is needed for this documentation update.
## Start it yourself in a foreground Terminal

The current operator server/finished mission must remain untouched. For a later fresh operator startup only, manually open your own Terminal and keep that process running throughout play/capture:

```sh
cd /Users/balakrishnanayyanar/Documents/Codex/2026-10-30/task
.venv/bin/python server.py --enable-twitch --port 8000
```

Open **http://localhost:8000/**. Binding stays **127.0.0.1**; live mode requires the exact localhost:8000 browser origin. This is a normal foreground process, with no persistence service. Close it with Ctrl+C when finished. Do not close the Terminal mid-demo. On a permission error, stop and report it; do not bypass TCC or change firewall/network exposure.

For a **clean reviewer**, extract the source ZIP into a new folder, use Python 3.9+ and run `python3 server.py`; open **http://localhost:8000/**. Simulation uses only stdlib, reads no credentials and makes no provider calls. Use a separate machine or wait until port 8000 is free; do not replace the operator's running process. All canvas/static assets are included; no asset downloads are required.

Optional dependency setup for a separately approved live installation (not needed for simulation):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
```

This installs only pinned **websocket-client 1.9.0** using the coordinator-verified official PyPI wheel hash. It does not provision credentials or authorize Twitch. The existing operator `.venv` needs no installation. Executor-owned servers were not durable; denied launchctl/Terminal automation will not be retried. No persistence service or permission bypass is used.

## Live preflight and demo

1. **Retry status** if needed. Authorize **only user:read:chat**, using `balakrishnanayyanar`. OAuth readiness/authorization and chat connection are displayed separately. The callback returns to a clean local URL; never record the login, callback/network details or private storage.
2. Click **Connect chat** and wait for verified subscription status. An acknowledgement proves a subscription, not message delivery. No connection happens merely from starting the process or loading the page.
3. Have a real viewer send `!supply` in the actual channel while the mission is ready. The validated-events counter and sanitized receipt should increase, but accepted votes should stay zero with “mission not running.” This checks delivery without spending mission time. **Coordinator verified this ready-state receipt, followed by a fresh accepted live vote; footage is still pending.**
4. Confirm viewers are ready, then **Deploy rover**. The first seven-second round starts immediately. Ask for a **fresh** `!supply` during the round. An accepted receipt, incremented tally and accepted-live-votes counter establish vote processing; subscription alone does not. Live-mode UI waits for chat connection before enabling deployment; core mission rules are unchanged.
5. At round close, **Community impact** explains the winner/default/tie, actual resource delta (including battery cap) and route length before/after. Rescue the northeast crew, then reach the southeast shelter. After real subscription activation, simulated viewer buttons remain disabled, including across reconnect/mission restart.

Diagnostics show only safe action/outcome/mission/round/counts. No raw provider text, names, user/message IDs, tokens or URLs are exposed. Counters are **current-process only**, retained across mission restart/reconnect, cleared on server exit. Duplicate delivery can increase the validated-event count, but never accepted votes.

## Rules and recovery

The rover moves automatically every 1.25 seconds, using 2.6 battery per tile. Start with 42 battery and 65 seconds of oxygen. Choose supply early; ignoring supplies loses to battery depletion. Deliver with resources remaining to win. Restart returns to 42/65, round 1, ready.

| Command | Consequence at round close |
| --- | --- |
| `!north` | Open north crossing; no resource cost |
| `!scan` | Open central crossing; +8s oxygen, −4 battery |
| `!supply` | Open south crossing; +22 battery capped at 100, −6s oxygen |

One immutable vote per normalized viewer ID per round. Most votes wins; ties use north → scan → supply order; no votes defaults north. Other crossings close, except underneath the rover until it leaves. Seven-second rounds, paths and resources remain backend-owned.

When the backend is unavailable, all gameplay/auth/chat actions are disabled and timers are marked stale. Start the foreground process and retry status; the browser never restarts it or auto-authorizes/connects. If a server is still running, mission time is **not paused** by browser/network loss. Polls have deadlines and bounded recovery delays.

Transport loss retries at 1/2/4/8/16 seconds, at most five per intentional start. Recovery status shows the retry. Wait for stopping workers to finish before reconnecting. For expired/rejected authorization, **Clear local authorization**, authorize again, then reconnect. Disconnect keeps local authorization; clearing it deletes local tokens without remote revocation. Restarting the server always requires fresh local authorization. No persistent tokens are stored.

## Private configuration

The registered app is **Chat Mission Control**, **Confidential / Game Integration**, with redirect **http://localhost:8000/auth/twitch/callback**. The user privately provisioned credentials and the coordinator previously validated storage; **this coding turn never read existing credentials or env/secret files**. Do not regenerate/overwrite them.

The sole supported storage path is `.twitch-local/credentials.json`, excluded from Git. Strict UTF-8 JSON accepts only `schema_version` integer 1, `client_id` (ASCII alphanumeric, 1–256), `client_secret` (visible ASCII without whitespace, 1–1024), at most 4096 bytes. Empty public template: `twitch-config.example.json`. Private directory must be current-owner 0700; file 0600 or 0400, regular and single-linked. Insecure ownership/modes, extended ACLs, symlinks and unsupported safety checks fail closed. No env fallback or browser upload.

`--check-twitch-config` validates and exits without binding or network; `--load-twitch-config` loads **disabled** OAuth memory; `--enable-twitch` is the separate explicit live capability flag. Modes are mutually exclusive. Default import/startup reads no secrets. See [TWITCH_SETUP.md](TWITCH_SETUP.md) for protocol/security boundaries.

## Verify and prepare submission

```sh
PYTHONPATH=tests .venv/bin/python -m unittest test_game test_twitch_adapter test_oauth test_eventsub test_local_config test_live_activation test_twitch_ui test_demo_readiness test_http.HandlerSmokeTests -v
PYTHONPYCACHEPREFIX=/tmp/chat-mission-control-pycache .venv/bin/python -m py_compile game.py server.py oauth.py eventsub.py twitch_adapter.py local_config.py tools/check_source.py
.venv/bin/python tools/check_source.py
```

Latest coordinator verification: **100 full tests passed, no skips** (`evidence/timestamp-fix-full-tests.txt`); the separate socket-free run passed **98**, and compilation passed. Earlier 95-full/93-socket-free results are historical. No tests were rerun for this docs/package update. Tests use fake provider/socket/OAuth data and new temporary credentials. Native JavaScriptCore UI tests run on macOS and skip elsewhere; socket tests require loopback permission. Full reviewer command: `python3 -m unittest discover -s tests -v`.

Coordinator desktop screenshots verified current layout/counters/preflight after unlock. Full responsive coverage and actual live disconnect recovery are **not verified**. The Python 3.9 nanosecond timestamp fix is now supported by the subsequent real delivery/vote evidence, not merely subscription status. Workspace-only `evidence/VALIDATION.md` keeps earlier results separate; raw test logs/history are intentionally excluded from the reviewer ZIP. The packaged curated JSON and readiness summary report the verified evidence.

[Readiness](submission/READINESS.md), [planned 2:50 demo](submission/DEMO_SCRIPT.md), [manual recording workflow](submission/RECORDING.md) and [unsubmitted draft](submission/DRAFT.md) describe remaining work. The source ZIP uses only [explicit manifest entries](submission/SOURCE_MANIFEST.txt). No video has been recorded; the repository destination is https://github.com/Balakrishnan-Ayyanar/twitch-game (source publication pending); demo URL remains pending. Public **or unlisted** YouTube is allowed. User now approved reviewed-source commit/push to https://github.com/Balakrishnan-Ayyanar/twitch-game; **coordinator only**, publication pending. No YouTube/Devpost upload/submission is authorized or performed. Logs/screenshots do not replace genuine Twitch and same-session Codex footage.

Coordinator-supplied working deadline: **November 2, 2026, 22:00 UTC** (**November 3, 06:00 Malaysia**). Parent verified the [official rules](https://twitchcon-codex.devpost.com/rules): Nov2 14:00 PST =22:00 UTC; the resources FAQ21:00 UTC conflicts. See submission/READINESS.md for equal criteria, required English/source/Codex proof, sharing approvals and deadline freeze. This update did not browse.

## Local video source — draft only

[video/README.md](video/README.md) prepares a1920×1080,30fps,170s Remotion demo with exact4.0.540 Remotion/CLI and19.3.1 React pins. It includes an explicitly watermarked draft, missing-footage cards, fail-closed reviewed-clip Final mode and a stdlib ElevenLabs helper with fake-only tests. Coordinator installed the pinned npm dependencies with lifecycle scripts disabled; package-lock.json is now in the manifest. Private provider inspection succeeded; narration generation and render remain pending after review of the public314-word script. No provider/install/render occurred in this coding turn. Genuine game/chat and same-session Codex footage remain unrecorded.

The old32-file ZIP is **stale**; rebuild is pending coordinator lockfile/manifest review; installation is complete. [STAGING.md](submission/STAGING.md) is the exact-source staging checklist; only coordinator performs approved git writes/push. No YouTube/Devpost upload/submission.
