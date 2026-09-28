# Personal AI Engineering edition

This private review page builds on the fork's X collector. It **does not send WhatsApp messages**. Each day it collects the upstream X list without model calls, then builds `personal/output/YYYY-MM-DD.html`. If collection fails, it labels the fallback to the last complete run.

```sh
uv run --no-cache personal/run.py
uv run --no-cache personal/run.py --from-latest  # render without collecting again
```

The command prints a `http://127.0.0.1:8765/YYYY-MM-DD.html` URL and starts a local review server. Open that URL to review the edition. Existing `file://` pages redirect there and migrate older browser feedback. Each `Good to post`, `Watch`, or `Skip` choice saves immediately; text is saved after a short typing pause. The dated record is `personal/feedback/YYYY-MM-DD.json` and is ignored by Git. Pending changes are also kept in browser storage until the local save succeeds. The page shows its save status beside the controls.

`Copy review for chat` copies decisions; `Download taste dataset` exports JSON. The page cannot publish to WhatsApp.

An exported JSON file can be imported with `uv run --no-cache personal/record_feedback.py /absolute/path/to/review.json`. This merges corrections by story ID into the local ignored `personal/feedback/YYYY-MM-DD.json` file. Decisions pasted into chat can be recorded in the same format.

Current coverage combines the upstream monitored X list with selected primary sources for search and retrieval. The public Reddit collector requires `REDDIT_SESSION`, and neither it nor the upstream summarizers can run fully here until their separate credentials are configured. The editorial JSON file for a date can group posts, add primary sources, and write `broken`, `fix`, and `evidence` claims with source links displayed inline. Raw runs and generated pages stay local.
