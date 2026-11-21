# IncuBrix Growth Option 3: evidence tracker foundation

This is working local tracker code, not a completed assessment. It currently contains 56 imported source-derived question candidates after a relevance review of 69 collected strings. Four assistant answers for one question are saved as a pilot, but are not imported as verified market measurements. The source brief requires 100 real questions, Google plus at least four AI assistants, two observation days, and the US plus at least two other markets. That is a minimum 3,000 checks if the full question/surface/market/day grid is used. Collecting those checks remains real work; this software does not invent or automatically supply them.

## Start here (Windows)

Install Python 3.10+ only if it is not already available. No pip packages, API subscription, or key is needed for the default run. Open PowerShell in this folder and run:

```powershell
python tracker.py run
```

This one command refreshes `visibility.csv`, `exports/questions.jsonl`, `exports/checks.jsonl`, `reports/weekly.md` and `reports/coverage_gaps.json`. It is safe to repeat. Without imported data it truthfully produces a header-only CSV and a zero-coverage report. By default it runs no network request or external command. `python -m unittest -v test_tracker` runs the offline tests; all synthetic observations live inside temporary test directories and are never exported as submission evidence.

## Add real questions, then observations

1. Save actual source-derived questions as UTF-8 JSON Lines: one JSON object per line. Do not use an AI-generated list as source evidence. Copy the source wording, URL and relevant source excerpt. Record when you actually saw it.
2. Import them: `python tracker.py import-questions --file intake/questions.jsonl`.
3. Inspect `python tracker.py run` outputs to find the generated question IDs (or assign stable IDs when importing).
4. Collect actual observations. Ask the unmodified question, not a prompt mentioning IncuBrix. Use a fresh conversation and record the actual mode. Verify location settings in the tool. A market label is not proof of geolocation, and adding “in the US” to a prompt is not the same as configuring US search location. Record unavailable settings honestly; do not count an unverified location as valid market coverage.
5. Copy screenshots and other local evidence under `evidence/`. Save observations as JSONL, then run `python tracker.py import-checks --file intake/checks.jsonl`.
6. Run `python tracker.py run`. Repeat collection on another actual date; never change timestamps to simulate day two. For AI variability, retain independent attempts, not just the best response.

The `intake/` folder is not created automatically. You may create it or pass another input path. Evidence files referenced by an imported observation must already exist inside this tracker folder. Question/observation inputs are local files, not an automatic consumer-assistant integration. Missing observations are blank in the CSV, not “no mention.”

### Question JSONL contract

Required strings: `question`, `intent`, `source_type`, `source_url`, `source_captured_at`, `source_excerpt`.

- `source_url`: actual http(s) page, suggestion or community source URL.
- `source_captured_at`: ISO timestamp with actual UTC offset, such as the format `YYYY-MM-DDTHH:MM:SS+05:30`; replace with the true time.
- `source_excerpt`: exact relevant source text proving the question exists.
- Optional `question_id`, `priority`, `notes` are retained. IDs must be unique.

Whitespace, case, Unicode compatibility and trailing sentence punctuation are normalized for question deduplication. Additional source records for the same normalized question are merged. This is deliberately conservative: semantic near-duplicates still need human review. The source's reality/relevance requires human verification; accepting a URL is not proof of its contents.

### Observation JSONL contract

Required nonempty strings:

`question_id`, `observed_at`, `timezone`, `market`, `actual_location`, `location_setting`, `tool`, `surface`, `model`, `mode`, `prompt`, `collection_method`, `status`.

- `observed_at` must have the true timezone offset. `timezone` records its human-readable zone (for example Asia/Kolkata). The software enforces offset presence, not the truth of the supplied clock or zone name.
- `actual_location` describes where the collector really is. `location_setting` states exactly what the product was configured to use, including unknown/unavailable settings. `market` is the intended ISO country code, not independent verification of a market. Add `location_verified`: true only when you have verified the intended market setting in the actual tool and retained that evidence. The strict coverage grid excludes records without this explicit true flag; this is still a reviewer assertion, not automatic geolocation proof.
- `surface`: `google_search`, `consumer_assistant` or `model_api`. A model API is NOT ChatGPT/Gemini/Claude's consumer interface. API data stays visible in normalized exports/report but cannot silently satisfy consumer-assistant columns or coverage.
- Consumer tool names for workbook mapping: `ChatGPT`, `Gemini`, `Perplexity`, `Claude` or `Copilot`. Google tool name: `Google`. Record exact model if exposed, otherwise `not exposed`; never guess it. In `mode` record search/web grounding on/off, conversation state and relevant settings.
- `prompt` must exactly equal the source question (apart from outside whitespace). Brand-forcing prompts are rejected.
- `collection_method`: `manual`, `command` or `http_json`.
- `status`: `ok`, `unavailable` or `error`. Non-ok observations require an `error` description and raw text or local evidence. They never become measured negatives.
- Every check needs nonempty `raw_answer` OR at least one existing file in `screenshot_paths`/`evidence_paths` (arrays of local relative paths). Use exact copied answers, not a rewritten summary. Raw answers are persisted separately in `evidence/raw/`.
- Every successful observation needs explicit `citations` (actual URL list) and `competitors_named` (reviewed name list). Empty lists mean a collector explicitly observed none, not missing information.
- Successful assistant observations need `mention`: a reviewed true/false boolean. IncuBrix citation is independently scored from citation URLs whose exact host is incubrix.com or www.incubrix.com. A mention without a citation is not a citation.
- Successful Google observations additionally need `google_position` (positive integer, or null if not found), `search_depth` (positive integer), `answer_box_or_ai_overview` (`none`, `answer_box`, `ai_overview` or `both`), and `quoted_source_urls` (actual reviewed URL list). Null position means “not found within recorded depth,” never universal absence. Record both features' source URLs if both appear.
- Optional `cost`: object with numeric nonnegative `amount`, `currency` and `basis`. Omit it when unknown. Zero is valid only when genuinely justified. Subscription costs/manual labor are not silently assigned zero.
- Extra provenance fields, such as `run_id`, `attempt`, `browser_version`, `account_state`, `language`, `search_url`, `session_url`, `location_verification`, and `reviewer_notes`, are preserved.

No private account information or credentials belong in raw evidence. Redact them before importing; preserve the visible answer, time, tool, settings and source references needed for audit.

## Real collection adapters: configurable, not pretended automation

Two working transport adapters are provided. Neither is a ready-made Google/ChatGPT/Gemini/Perplexity/Claude browser driver. They need an authorized actual collector. No live collector was invoked during implementation.

Keep `allow_external_collection` false until access, platform terms, spend and data handling have been checked. Never enable a paid backend without approval. Targets are empty by default. A configured target has:

- `id`: stable label; `enabled`: true/false.
- `tool`: actual product; `surface`: one of the three explicit values above.
- `adapter`: `command` or `http_json`.
- `attempts`: 1–5 (default 2); `timeout_seconds`: default 90; `retry_delay_seconds`: default 1, exponential backoff capped at eight seconds.

For `command`, set `command` to an argument array, such as a Python executable and your authorized collector script. It receives one JSON object on stdin and must return exactly one observation JSON object on stdout. stderr is not persisted to avoid credential leaks. `shell=False` is enforced. Only run code you trust.

For `http_json`, set `endpoint_env` to the name of an environment variable containing your own authorized HTTPS collector URL. Optionally set `token_env` to the name of its bearer-token variable. Secrets stay in environment variables, never config files. The tracker POSTs the request JSON and expects one observation JSON response. No service-specific endpoints or hidden scraping are built in.

Request keys: `question_id`, `question`, `prompt` (unaltered), `requested_day`, `market`, `target`. Collector response follows the complete observation contract above. It must supply true observation time and actual location/settings; the request's intended market alone is insufficient. The response's question, market, date, tool and surface are checked against the request. The adapter supplies collection method and a config fingerprint. It never manufactures model, mode, location or answers.

A target that fails is retried and logged. Failed attempts are in `logs/events.jsonl` with error class, target, market, attempt number and runtime. Raw server errors are deliberately omitted because they may contain credentials. The final CLI exit code is 2 if any collection target exhausted retries. Resolve the integration problem and run again; successful same-day target/config/question/market combinations are skipped, failed ones are retried. To intentionally collect another independent same-day sample, change the target ID or import the actual observation manually with its distinct timestamp/attempt. Do not overwrite earlier evidence.

The basic transport interface can be wired to an approved browser workflow or an official API. An API result must use `model_api`, not `consumer_assistant`. A Google Custom Search API response is not automatically a Google SERP/AI Overview observation. Only count features actually seen in the surface being assessed.

## Outputs and calculation rules

- `data/tracker.sqlite3`: durable normalized source of truth; questions and checks are separate tables. Same imported observation is idempotent; different days/markets/attempts are preserved. The content hash includes all original observation fields, so changing a note creates a new record rather than silently rewriting evidence. Work from a single writer; close the process before copying the database.
- `exports/questions.jsonl`, `exports/checks.jsonl`: portable full records. Screenshot evidence paths have SHA-256 fingerprints taken at import. Raw text lives in `evidence/raw/`. Keep the entire folder together; relative links are not public share URLs.
- `visibility.csv`: exactly the 22 official `02_QUESTIONS` headers, in workbook order, one row per unique source question. Days/markets are labeled inside summary cells. Only Google and named consumer assistants map to their respective workbook columns. API-only observations do not substitute for them. The row's raw-answer reference points to the normalized export and question ID. Convert it to a real shared-folder evidence URL when submitting the workbook.
- `duplicate_check`: `UNIQUE` because canonical duplicates are merged before export.
- `completeness_check`: the workbook's exact required-nonblank-fields test, calculated as static text for CSV. “COMPLETE” is NOT a claim of full assessment validity. The stricter question/market/surface/two-day grid appears in the weekly report and coverage-gap JSON.
- `changed_on_day2`: compares the first two observed local dates, using sets of result attributes per identical market/tool/surface/model/mode. Missing matching coverage means `NOT COMPARABLE`. It is an observed difference, not statistical significance or causal effect.
- `reports/weekly.md`: seven-day window ending on `--day` (defaults to today's local date). Mention and exact-host citation rates are separate fractions of successful assistant checks, grouped by surface/tool/market. Failed/unavailable checks are counted, not included in success denominators. Repeated attempts all count; this is an attempt-level rate, not question-weighted share. Coverage gaps are cumulative across all dates, not limited to that week. Known check costs, unknown cost counts and measured external-collector attempt runtime are included. Runtime extrapolation is illustrative, not a performance guarantee.
- `logs/events.jsonl`: import, retry, success and runtime records. For import errors, line number and validation message are logged. Do not import secrets in any fields. Malformed JSON lines are rejected individually; exit code 2 signals import errors.
- `python tracker.py brief --question-id YOUR_REAL_ID`: creates an evidence-grounded draft brief from the real question and observed citation URLs. It is a task template, not finished content or a verified product claim.

`--day YYYY-MM-DD` chooses the report end date and checks expected from enabled collectors. It never assigns historical dates to real answers. Use `--root PATH` for an isolated copy/test workspace and `--config PATH` for an alternative approved configuration.

## What is and isn't verified

Offline tests exercise deduplication, exact CSV shape and computed checks, two-day/market retention, real-evidence requirements, prompt integrity, mention/citation distinction, unavailable/error handling, model API separation, complete coverage calculation, retries/recovery, repeated refresh, reports and brief generation. The supplied workbook was inspected through the spreadsheet helper only; no input or formula cells were edited and no workbook was pushed.

Not completed by this code: the full 100-question sourced dataset; real search/assistant baseline; actual consumer-assistant integrations; scheduled weekly execution; alerts; independent audit reproduction; product audit; 20 validated fixes; 10 publish-ready pages; 30 citation targets; launch kit; completed workbook; repository sharing; videos. Manual import is supported and must be disclosed. The code does not verify the source's existence or truth of recorded model/location/answer claims, visually inspect screenshots, or bypass restrictions. Human review is still essential.

AI assistance disclosure: an AI companion drafted and offline-tested this tracker and README. Synthetic fixtures are tests only. The candidate must understand, review and be able to explain every submitted component.
