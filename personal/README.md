# Personal AI Engineering edition

This private review page builds on the fork's X collector. It **does not send WhatsApp messages**. Each day it collects the upstream X list without model calls, then builds `personal/output/YYYY-MM-DD.html`. If collection fails, it labels the fallback to the last complete run.

```sh
python3 personal/run.py
python3 personal/run.py --from-latest  # render without collecting again
```

The page has `Good to post`, `Watch`, and `Skip` controls plus an optional reason. Choices stay in that browser's local storage. `Copy review for chat` copies the decisions so they can be pasted into the Codex chat; `Download taste dataset` exports JSON for a future training and ranking loop. The page deliberately asks for judgments but cannot publish.

An exported JSON file can be imported with `uv run --no-cache personal/record_feedback.py /absolute/path/to/review.json`. This merges corrections by story ID into the local ignored `personal/feedback/YYYY-MM-DD.json` file. Decisions pasted into chat can be recorded in the same format.

Current coverage is the upstream monitored X list. The public Reddit collector requires `REDDIT_SESSION`, and neither it nor the upstream summarizers can run fully here until their separate credentials are configured. The editorial JSON file for a date can group individual posts into better story candidates and add a human-written angle. Raw runs and generated pages stay local.
