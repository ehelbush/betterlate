## Git protocol (one source of truth)

Eric is not a developer. This section prevents the failure where work sits on a side branch, unpushed, or uncommitted, and the next session reads stale state from `main` (it happened in the Firtop repo in September 2026).

1. **Session start, always:** run the unmerged-work check before reading any state.
   ```
   git fetch -q && git status --short --branch && git branch -r --no-merged main
   ```
   If any branch besides `main` shows up, or `main` is ahead of or behind `origin/main`, say so in the first reply and read state from wherever the newest work is.
2. **Branches are only for paths with a publish step.** This repo is published by being public on GitHub; the token-gated `deploy/` bundle is built and deployed by each user from their own machine and is not part of this repo. So this repo has none: never create a branch or PR here. Everything commits straight to `main`.
3. **Session end, always:** commit and push before the last reply. If the session created a PR, the last reply asks Eric to merge it now and says what stays unmerged until he does.
4. **PRs older than a day are a bug.** When the start-of-session check finds one, offer to fold it in or close it before other work.
5. **Generated views follow canonical files.** The demo dashboard image in `docs/` and any sample report are rendered from the synthetic data in `sample/` by the build scripts in `code/`. After any merge that changed the dashboard build or the sample data, regenerate them so the README matches the code.
