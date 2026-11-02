# Local submission readiness — November 2, 2026

| Milestone | Evidence / remaining work |
| --- | --- |
| Actual read-only Twitch delivery and vote | Coordinator 14:31:30 UTC: PID2191, ack1 / validated2 / accepted1; ready-state supply not_running then fresh round1 supply accepted |
| Actual community consequence and rescue | Exactly one supply resolution +22 battery / −6 oxygen, route recalculated; rounds2/3 no-vote north; won25.0s carrying=true, final12 battery /34 oxygen |
| Evidence precision | [Curated JSON](../evidence/live-vote-verified.json); exact Round1 route lengths/intermediate resources not retained. Never substitute simulation9→11 |
| Tests | Latest100 full/no skips; separate98 socket-free; compile passed. Earlier95/93 retained as history; no rerun for packaging |
| Visual QA | Current desktop screenshots verified layout/counters/preflight; no full responsive or actual live disconnect recovery claim |
| Recording | **Not performed**; genuine Twitch and same-session Codex footage still required |
| Distribution | Old ZIP stale; repository destination https://github.com/Balakrishnan-Ayyanar/twitch-game approved for coordinator push, publication pending; demo URL pending |

Preserve the user-owned running server and completed mission. No restart/reset or token-expiry assumption is made. For clean reviewer reproduction, extract the ZIP into a new folder and run `python3 server.py` with Python3.9+; simulation is stdlib-only and needs no credentials. All local runtime modules and four static assets are listed in [SOURCE_MANIFEST.txt](SOURCE_MANIFEST.txt). Optional live dependency setup uses `pip install --require-hashes --only-binary=:all: -r requirements.lock` inside a reviewer-owned venv; see README. macOS native JavaScriptCore tests skip elsewhere. Real transport/recovery failure paths have mocked coverage, not verified live recovery footage.

## Source package review

The previous32-file ZIP contains **only its then-current explicit manifest entries**, including the empty template, fake-data tests, manual recording guide and curated sanitized live evidence. Runtime imports/static references/requirements were reviewed for completeness. Packaging rejects symlinks, hardlinks, nonregular files and unsafe paths; directories are never recursively added. That old archive passed entry/hash/integrity checks but is **stale after video-source changes**. Coordinator-created video/package-lock.json now exists; rebuild remains pending coordinator review, do not claim it includes the new source. The separate package report records the actual list/hash/size.

`tools/check_source.py` scans its fixed18 public-source/docs allowlist only, reports rule/line without matched values and never opens private configuration/env/logs. It is a narrow heuristic, not a secret-free guarantee. New recording prose and curated JSON receive explicit public-scope review. No `.twitch-local`, env, `.venv`, `.git`, caches, private/raw CLI/provider logs, callback exports or footage are packaged. Never read real secrets to compare them. No archive review authorizes external sharing.

## Rules and remaining human steps

Coordinator verified [official rules](https://twitchcon-codex.devpost.com/rules): equally weighted **Innovation/Idea, Potential Impact, Technological implementation, Design**; English materials, complete source/assets/setup, concrete Codex use and main-session `/status` proof. Official deadline **Nov2 14:00 PST =22:00 UTC / Nov3 06:00 Malaysia**; resources FAQ21UTC conflicts. Submitted materials freeze after deadline.

Follow [RECORDING.md](RECORDING.md) and the planned [2:50 storyboard](DEMO_SCRIPT.md). Resume only the existing idle session, capture actual `/status` and genuine later timestamp-fix review/test work; do not present it as historical footage. No old footage is known. Accessible **public OR unlisted YouTube** is allowed, but no YouTube/Devpost upload/submission is authorized. Reviewed-source commit/push to the specified public GitHub repository is approved for coordinator only. Private repo access for **testing@devpost.com** requires separate explicit approval. Repository destination is known; successful source publication and demo URL remain pending.


## Video preparation update

Coordinator installed the pinned npm packages with lifecycle scripts disabled; video/package-lock.json exists. Narration, render and genuine footage are **still pending**. Polished narration dry-run:314words/2084characters, no key/network. Coordinator private inspect found eleven_multilingual_v2 and21premade voices; no generation. Persistent-watermark Draft is evidence graphics with explicit missing-footage cards, not submission-ready video. Final requires reviewed genuine local game/chat and same-original-session later-follow-up Codex clips. Recording remains pending. See video/README.md and [STAGING.md](STAGING.md); current source manifest has44entries including video/package-lock.json; coordinator reviews/stages it. No new game test claims: the prior100/98 results remain historical; prior preparation ran helper/Node checks; this small polish reruns only the8Node tests/syntax and key-free narration dry-run.
