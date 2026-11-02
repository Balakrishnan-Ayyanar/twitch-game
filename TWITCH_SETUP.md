# Optional read-only Twitch setup

Default `python3 server.py` is simulated and reads no private storage. Live operation is an operator-owned local confidential app targeting **balakrishnanayyanar**, not a hosted service or distributed shared-secret application.

## Private configuration

Use a confidential **Game Integration** Twitch application with exact registered redirect **http://localhost:8000/auth/twitch/callback**. The owner must meet Twitch registration requirements (verified email and 2FA). Use the existing owner app where applicable; never publish or share its secret.

If the directory already exists, preserve it and its contents; do not overwrite existing credentials. For new storage, use the empty public template, then enter the owner's app values privately in a local editor:

```sh
mkdir -m 700 .twitch-local
cp -n twitch-config.example.json .twitch-local/credentials.json
chmod 600 .twitch-local/credentials.json
```

Supported UTF-8 JSON has only `schema_version` (integer 1), `client_id` and `client_secret`. Client ID is ASCII alphanumeric, 1–256 characters; secret is visible ASCII without whitespace, 1–1024 characters. Maximum 4096 bytes. The empty template does not pass validation until filled. Never paste values into chat, logs, browser storage or source.

Directory must be current-owner with mode 0700; file mode 0600 (or 0400), regular and single-linked. Symlinks, extended ACLs, insecure modes/ownership and unsupported safety checks fail closed. No env discovery, browser upload or credential fallback. `.twitch-local/` is ignored.

```sh
.venv/bin/python server.py --check-twitch-config
.venv/bin/python server.py --enable-twitch --port 8000
```

The validator exits without binding/network. `--load-twitch-config` is storage-only and leaves OAuth disabled. Modes are mutually exclusive. Only explicit `--enable-twitch` enables the provider factories; startup itself does not authorize or connect. Keep the server foreground. Binding stays 127.0.0.1; live port is exactly 8000. Open **http://localhost:8000/** consistently, not the 127 alias.

## Authorization and chat

In the operator panel, intentionally authorize the expected account with **only `user:read:chat`**, return through the clean callback, then Connect chat. No posting, moderation, email or broadcast scope. WebSocket EventSub uses a USER token; app-token bot permissions are not used.

A verified subscription is not message delivery. A ready-state command can produce a sanitized `not_running` receipt but no vote. After deployment, a fresh command during the seven-second round can produce an accepted receipt/tally and a later round consequence. Simulated voting is disabled after live activation. Diagnostics expose safe action/outcome/counts only, not raw messages, provider IDs or tokens.

## Security boundaries

- Exact Host/Origin checks, no wildcard CORS, foreign origins or DNS-rebinding hostnames. Live origin is localhost:8000; alias cookies are not shared.
- Host-only HttpOnly SameSite=Lax session cookie, bounded 30-minute session. Intentional same-origin POSTs require session CSRF for auth start/connect/disconnect.
- Confidential authorization-code flow; single-use five-minute state bound to session/configuration/redirect/scope. No PKCE support is assumed. Callback validates client/account/numeric user ID/expiry/exact scope; queries and provider error bodies are not logged or reflected.
- Tokens stay backend memory only. Clear-local authorization stops the worker and removes tokens; it does not remotely revoke the grant. Automatic refresh/persistent tokens are not implemented; restart requires reauthorization.
- TLS/hostname-verified `wss://eventsub.wss.twitch.tv/ws`, no token in socket headers/query. Welcome plus matching HTTP 202 channel.chat.message v1 subscription acknowledgement precede connected status. Helix verifies the expected channel.
- Keepalive watchdog, official reconnect handover and capped cancelable retry handle transport loss. Authorization expiry/revocation stops retries. Exact reconnect URL allowlist rejects other hosts/protocols/paths/query fields.
- Strict RFC3339 timestamp parsing supports nanoseconds on Python 3.9, with full fractional freshness precision. Envelope/channel/user shape, bounded dedup and original ingress mission/round token are validated under the game lock. No browser notification-ingestion endpoint.

The optional transport uses pinned **websocket-client 1.9.0** (`requirements.txt`, hash-locked `requirements.lock`); OAuth/Helix HTTP uses stdlib. No Node dependency is needed. [README](README.md) contains architecture, demo and curated verification. Full responsive/live disconnect recovery remain unverified; mocked tests are not production-load proof. A public distributed app would require a separately designed public device-code/no-shared-secret flow.
