# Twitch operations and boundaries

**Verified live milestone — 2026-11-02 14:31:30 UTC:** coordinator observed user-owned **PID 2191**, connected with **1 subscription acknowledgement, 2 validated notifications and 1 accepted vote**. In mission 1 / round 1, a real `!supply` first produced `not_running`, then a fresh command was accepted. Exactly one supply resolution applied **+22 battery / −6 oxygen** and recalculated the route; rounds 2 and 3 defaulted north without votes. The mission **won at 25.0s**, carrying the crew, with **12 battery / 34 oxygen**. [Curated sanitized evidence](evidence/live-vote-verified.json) retains this result, but **not the exact Round 1 route lengths or intermediate resource snapshots**. Earlier simulation route 9→11 is not live evidence. Preserve the running server and completed mission; no reset/restart is needed for this documentation update.
## Foreground operation

Preserve current PID2191 and its completed mission. For a later fresh startup only, manually use your own Terminal in this workspace:

```sh
.venv/bin/python server.py --enable-twitch --port 8000
```

Keep it open; visit **http://localhost:8000/**. No Terminal automation, launchctl/persistence job, TCC workaround, broader bind or firewall change is installed or permitted by this work. The prior launchctl attempt was denied Documents/venv access and removed. If startup fails, report the error without private values; do not bypass restrictions. This coding turn launched nothing.

Use the operator panel in order: status → read-only authorization → clean callback return → chat connect → verified subscription → actual ready-state command receipt → deploy → **new** command in the seven-second round → accepted receipt/tally → round impact. A ready-state command proves delivery but casts no vote. Do not conflate the three evidence counters. Current process counters reset on exit, remain across restart/reconnect, and are not historic submission evidence on their own. See README for exact mission behavior.

Only `user:read:chat` is requested/accepted. No chat posting, moderation, email or broadcast permissions. WebSocket subscriptions require a USER token; the app-token bot permissions path is not used.

## Credentials, OAuth and local routes

- Existing operator-owned app: **Chat Mission Control**, **Confidential / Game Integration**, exact redirect **http://localhost:8000/auth/twitch/callback**. Do not create a duplicate. Private credentials were provisioned by the user; do not open/reveal them through Codex, logs, chat or footage.
- Storage is only `.twitch-local/credentials.json`; JSON version/client ID/secret and conservative owner-only validation are documented in README. No environment discovery. Default startup reads nothing; `--check-twitch-config` and `--load-twitch-config` are storage-only. Only `--enable-twitch` wires enabled OAuth HTTP and approved socket/Helix factories; it does not itself connect or grant. Another live port is rejected before storage reads.
- Binding stays **127.0.0.1**. Live Host/Origin is exactly **localhost:8000**; default mode also permits the 127 alias at its listening port. No wildcard CORS, DNS-rebinding hostname, duplicate Host or foreign Origin. Alias cookies are not shared.
- `GET /api/twitch/status` creates/reads a bounded 30-minute local session. `cmc_session` is random, host-only, HttpOnly, SameSite=Lax. The HTTP loopback cookie is not a public-hosting design. Status returns sanitized fields and a session CSRF token, never provider credentials/tokens.
- Only intentional same-origin JSON `POST /auth/twitch/start` with session/CSRF initiates confidential authorization-code flow. Five-minute single-use state binds session, origin, configuration, exact redirect and scope. Replacement/expiry/replay/provider denial are handled; no PKCE support is assumed.
- Callback identity validation checks exact client/account, numeric user ID, expiry and exactly `user:read:chat`. Provider errors are never reflected; query logging is suppressed. HTML callbacks 303 to a fixed clean local URL. JSON clients get sanitized status/local links. UI allowlists the exact official authorization URL/fields, and keeps only CSRF/status in closure memory.
- `POST /api/twitch/connect`, `/api/twitch/disconnect`, `/auth/twitch/disconnect` use the same session/Origin/CSRF guards. Only the owning session controls an active worker. Connect and authorization are separate. Clear-local also stops the worker, removes in-memory tokens and pending attempts; it does not remotely revoke the grant. Automatic refresh and persisted tokens are not implemented.

A publicly distributed application needs a separate **public device-code, no shared secret, no callback** design. The current confidential flow is operator-owned local software, not a distributable shared-secret scheme.

## Transport and evidence safety

`eventsub.py` uses approved **websocket-client 1.9.0**, coordinator-installed from official PyPI in Python **3.9.6** `.venv`. Pins/hash are in requirements files. No new dependency/install. Stdlib handles OAuth/Helix HTTP. The worker validates the channel through Helix, opens TLS/hostname-verified `wss://eventsub.wss.twitch.tv/ws` without bearer headers/query, and requires welcome + matching HTTP 202 `channel.chat.message` v1 acknowledgement before connected status.

Protocol ping/pong is library-owned. A welcome deadline and EventSub keepalive watchdog detect loss. Official reconnect retains the old socket until a candidate welcome and transfers subscriptions without duplicate POST. Reconnect URLs accept only exact host/path/protocol, default/443 port, one reconnect parameter and no credentials/fragment/other query fields. Unexpected loss opens a fresh session and re-subscribes, with capped cancelable backoff. Authorization loss/expiry/revocation stops; UI directs reauthorization, prevents restart while stopping, and exposes only safe retry counters.

Notifications are validated for type/version/channel/subscription user, stable chatter ID/text shape, freshness and bounded dedup before voting. Tick/capture/dispatch uses the game lock and original ingress round token. Dedup survives mission restart/reconnect. The latest 12 sanitized receipts expose only action/outcome/local mission/round/age; no raw text, provider IDs or URLs. Only validated notifications increment delivery; only successfully cast votes increment acceptance. A duplicate may count as another delivery, never another accepted vote. This is runtime observability, not independent attestation or a claim mocked fixtures were real.

All credential/provider/socket checks and no-message-write behavior remain intact. No browser notification ingestion endpoint exists. Prior implementation tests used synthetic fixtures only; this docs/package turn reran none. Coordinator verified actual notification delivery, accepted voting and the completed mission in the curated evidence above. Desktop screenshots verified layout/counters/preflight; full responsive coverage and actual live disconnect recovery remain unverified. No footage was recorded, and no upload/publication/submission occurred.
