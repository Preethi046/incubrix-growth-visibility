"""Evidence-first visibility tracker. Standard library only; Python 3.10+."""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, sqlite3, subprocess, sys, time, unicodedata
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
HEADERS = 'question_id question intent source_type source_url market google_position answer_box_or_ai_overview quoted_source_url chatgpt gemini perplexity claude_or_copilot competitors_named check_date_day1 check_date_day2 changed_on_day2 raw_answers_url priority notes duplicate_check completeness_check'.split()
REQUIRED = 'question intent source_type source_url market google_position answer_box_or_ai_overview chatgpt gemini perplexity claude_or_copilot check_date_day1 check_date_day2 raw_answers_url'.split()

def canonical(s):
    return ' '.join(unicodedata.normalize('NFKC', s).casefold().split()).rstrip(' ?.!')

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError('timestamp must contain actual UTC offset')
    return dt

def web_url(value):
    return urlparse(value).scheme in ('https', 'http') and bool(urlparse(value).netloc)

def read_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path, encoding='utf-8-sig') as f:
        return [json.loads(line) for line in f if line.strip()]

class Tracker:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        for name in ('data', 'evidence/raw', 'exports', 'reports', 'briefs', 'logs'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / 'data/tracker.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS questions (id TEXT PRIMARY KEY, canonical TEXT UNIQUE, body TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS checks (id TEXT PRIMARY KEY, question_id TEXT NOT NULL, body TEXT NOT NULL)')
        self.db.commit()

    def log(self, event, **details):
        with (self.root / 'logs/events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), event=event, **details)) + '\n')

    def questions(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM questions ORDER BY id')]

    def checks(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT body FROM checks ORDER BY id')]

    def add_question(self, item):
        q = dict(item)
        for key in ('question', 'intent', 'source_type', 'source_url', 'source_captured_at', 'source_excerpt'):
            if not isinstance(q.get(key), str) or not q[key].strip():
                raise ValueError('question missing ' + key)
        if not web_url(q['source_url']):
            raise ValueError('question source_url must be a real source URL')
        timestamp(q['source_captured_at'])
        norm = canonical(q['question'])
        existing = self.db.execute('SELECT id, body FROM questions WHERE canonical=?', (norm,)).fetchone()
        source = {k: q[k] for k in ('source_type', 'source_url', 'source_captured_at', 'source_excerpt')}
        if existing:
            prior = json.loads(existing[1])
            if source not in prior['sources']:
                prior['sources'].append(source)
                self.db.execute('UPDATE questions SET body=? WHERE id=?', (json.dumps(prior), existing[0]))
                self.db.commit()
            return existing[0], False
        qid = q.get('question_id') or 'q-' + digest(norm)[:12]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', qid):
            raise ValueError('question_id must be 1-100 letters, digits, underscores or hyphens')
        q.update(question_id=qid, sources=[source])
        self.db.execute('INSERT INTO questions VALUES (?, ?, ?)', (qid, norm, json.dumps(q)))
        self.db.commit()
        return qid, True

    def local_evidence(self, path):
        p = (self.root / path).resolve()
        if not p.is_relative_to(self.root) or not p.is_file():
            raise ValueError('evidence path must exist inside tracker folder: ' + str(path))
        return p

    def add_check(self, item):
        c = dict(item)
        for key in ('question_id', 'observed_at', 'timezone', 'market', 'actual_location', 'location_setting', 'tool', 'surface', 'model', 'mode', 'prompt', 'collection_method', 'status'):
            if not isinstance(c.get(key), str) or not c[key].strip():
                raise ValueError('check missing ' + key)
        dt = timestamp(c['observed_at'])
        if c['surface'] not in ('google_search', 'consumer_assistant', 'model_api'):
            raise ValueError('surface must distinguish search, consumer assistant and model API')
        if c['collection_method'] not in ('manual', 'command', 'http_json'):
            raise ValueError('unsupported collection_method')
        qrow = self.db.execute('SELECT body FROM questions WHERE id=?', (c['question_id'],)).fetchone()
        if not qrow:
            raise ValueError('unknown question_id')
        q = json.loads(qrow[0])
        if c['prompt'].strip() != q['question'].strip():
            raise ValueError('baseline prompt must exactly equal source question; no brand-forcing additions')
        if c['status'] not in ('ok', 'unavailable', 'error'):
            raise ValueError('status must be ok/unavailable/error')
        raw = c.get('raw_answer', '')
        paths = c.get('screenshot_paths', []) + c.get('evidence_paths', [])
        for path in paths:
            self.local_evidence(path)
        if not raw.strip() and not paths:
            raise ValueError('every check requires raw answer or local evidence')
        if c['status'] != 'ok' and not c.get('error'):
            raise ValueError('unavailable/error checks require error description')
        if 'cost' in c:
            cost = c['cost']
            if not isinstance(cost, dict) or type(cost.get('amount')) not in (int, float) or cost['amount'] < 0 or not cost.get('currency') or not cost.get('basis'):
                raise ValueError('cost requires nonnegative amount, currency and basis; omit when unknown')
        if c['status'] == 'ok':
            for key in ('citations', 'competitors_named'):
                if not isinstance(c.get(key), list):
                    raise ValueError(key + ' must be an explicitly reviewed list')
            if any(not web_url(url) for url in c['citations']):
                raise ValueError('citation entries must be actual URLs')
            if c['surface'] == 'google_search':
                for key in ('google_position', 'answer_box_or_ai_overview', 'quoted_source_urls', 'search_depth'):
                    if key not in c:
                        raise ValueError('Google check missing ' + key)
                pos = c['google_position']
                if pos is not None and (type(pos) is not int or pos < 1):
                    raise ValueError('position must be positive integer or null (not found within search_depth)')
                if type(c['search_depth']) is not int or c['search_depth'] < 1:
                    raise ValueError('search_depth must be positive')
                if pos is not None and pos > c['search_depth']:
                    raise ValueError('position exceeds observed search depth')
                if not isinstance(c['quoted_source_urls'], list) or any(not web_url(u) for u in c['quoted_source_urls']):
                    raise ValueError('quoted_source_urls must be a reviewed list of actual URLs')
                if c['answer_box_or_ai_overview'] not in ('none', 'answer_box', 'ai_overview', 'both'):
                    raise ValueError('answer box status must be explicitly observed')
            elif type(c.get('mention')) is not bool:
                raise ValueError('assistant mention must be explicitly reviewed boolean, never inferred from missing data')
        # Keep independent attempts, but same imported evidence/observation is idempotent.
        identity = {k: v for k, v in c.items() if k not in ('check_id', 'raw_answer_path')}
        cid = 'c-' + digest(identity)[:24]
        if self.db.execute('SELECT 1 FROM checks WHERE id=?', (cid,)).fetchone():
            return cid, False
        c['check_id'] = cid
        c['local_date'] = dt.date().isoformat()
        if raw:
            rp = Path('evidence/raw') / (cid + '.txt')
            (self.root / rp).write_text(raw, encoding='utf-8')
            c['raw_answer_path'] = rp.as_posix()
        if c.get('raw_answer_path'):
            paths = paths + [c['raw_answer_path']]
        c['evidence_sha256'] = {path: hashlib.sha256(self.local_evidence(path).read_bytes()).hexdigest() for path in paths}
        self.db.execute('INSERT INTO checks VALUES (?, ?, ?)', (cid, c['question_id'], json.dumps(c)))
        self.db.commit()
        return cid, True

    def import_file(self, kind, path):
        counts = dict(added=0, duplicate=0, errors=0)
        with Path(path).open(encoding='utf-8-sig') as f:
            lines = list(f)
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                _, added = self.add_question(row) if kind == 'questions' else self.add_check(row)
                counts['added' if added else 'duplicate'] += 1
            except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                counts['errors'] += 1
                self.log('import_error', kind=kind, file=str(path), line=n, error=str(exc))
        self.log('import', kind=kind, **counts)
        return counts

    def collect(self, config, day):
        """Only explicitly enabled, user-controlled integrations. No hidden browser scraping."""
        result = dict(collected=0, skipped=0, errors=0)
        if not config.get('allow_external_collection', False):
            self.log('collection_disabled', reason='Import-only mode; no network/commands executed')
            return result
        for q in self.questions():
            for target in config.get('targets', []):
                if not target.get('enabled', False):
                    continue
                for market in config['markets']:
                    # Do not rerun successful same-day same configuration; --day selects observation day, not falsified timestamp.
                    signature = digest({'target': target, 'market': market})
                    if any(c['question_id'] == q['question_id'] and c['local_date'] == day and c.get('target_signature') == signature and c['status'] == 'ok' for c in self.checks()):
                        result['skipped'] += 1
                        continue
                    payload = dict(question_id=q['question_id'], question=q['question'], prompt=q['question'], requested_day=day, market=market, target=target)
                    attempts = max(1, min(5, int(target.get('attempts', 2))))
                    for attempt in range(1, attempts + 1):
                        started = time.monotonic()
                        try:
                            adapter = target['adapter']
                            if adapter == 'command':
                                command = target['command']
                                if not isinstance(command, list) or not command:
                                    raise ValueError('command must be a JSON argument list; shell never enabled')
                                run = subprocess.run(command, input=json.dumps(payload), text=True, capture_output=True, timeout=target.get('timeout_seconds', 90), cwd=self.root, check=True, shell=False)
                                c = json.loads(run.stdout)
                            elif adapter == 'http_json':
                                endpoint = os.environ[target['endpoint_env']]
                                if urlparse(endpoint).scheme != 'https':
                                    raise ValueError('collector endpoint must use HTTPS')
                                headers = {'Content-Type': 'application/json'}
                                if target.get('token_env'):
                                    headers['Authorization'] = 'Bearer ' + os.environ[target['token_env']]
                                req = Request(endpoint, json.dumps(payload).encode(), headers=headers, method='POST')
                                with urlopen(req, timeout=target.get('timeout_seconds', 90)) as response:
                                    c = json.load(response)
                            else:
                                raise ValueError('unknown adapter')
                            if c['question_id'] != q['question_id'] or c['market'] != market:
                                raise ValueError('collector returned wrong question/market')
                            if timestamp(c['observed_at']).date().isoformat() != day:
                                raise ValueError('collector date differs from requested actual day')
                            if c['surface'] != target['surface'] or c['tool'] != target['tool']:
                                raise ValueError('collector returned wrong tool or surface')
                            c.update(collection_method=adapter, target_signature=signature)
                            self.add_check(c)
                            result['collected'] += 1
                            self.log('collection_ok', question_id=q['question_id'], target=target['id'], market=market, attempt=attempt, runtime_seconds=round(time.monotonic()-started, 3), cost=c.get('cost', 'unknown'))
                            break
                        except Exception as exc:
                            # Do not log stdout, endpoint or exception text: third-party failures may contain credentials.
                            self.log('collection_error', question_id=q['question_id'], target=target.get('id'), market=market, attempt=attempt, error_type=type(exc).__name__, runtime_seconds=round(time.monotonic()-started, 3))
                            if attempt == attempts:
                                result['errors'] += 1
                            else:
                                time.sleep(min(8, target.get('retry_delay_seconds', 1) * 2 ** (attempt-1)))
        return result

    def export(self):
        qs, checks = self.questions(), self.checks()
        for name, records in [('questions', qs), ('checks', checks)]:
            (self.root / 'exports' / (name + '.jsonl')).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in records), encoding='utf-8')
        rows = []
        for q in qs:
            cs = sorted([c for c in checks if c['question_id'] == q['question_id'] and c['status'] == 'ok'], key=lambda x:x['observed_at'])
            dates = sorted({c['local_date'] for c in cs})
            row = {h: '' for h in HEADERS}
            for key in ('question_id', 'question', 'intent', 'source_type', 'source_url', 'priority', 'notes'):
                row[key] = q.get(key, '')
            row['market'] = '; '.join(sorted({c['market'] for c in cs}))
            googles = [c for c in cs if c['surface'] == 'google_search']
            def label(c):
                return c['local_date'] + '/' + c['market']
            row['google_position'] = '; '.join(label(c) + '=' + (str(c['google_position']) if c['google_position'] is not None else 'not found in top ' + str(c['search_depth'])) for c in googles)
            row['answer_box_or_ai_overview'] = '; '.join(label(c) + '=' + c['answer_box_or_ai_overview'] for c in googles)
            row['quoted_source_url'] = '; '.join(sorted({u for c in googles for u in c['quoted_source_urls']}))
            for field, tools in [('chatgpt', ['chatgpt']), ('gemini', ['gemini']), ('perplexity', ['perplexity']), ('claude_or_copilot', ['claude', 'copilot'])]:
                relevant = [c for c in cs if c['surface'] == 'consumer_assistant' and c['tool'].casefold() in tools]
                row[field] = '; '.join(label(c) + '/' + c['tool'] + '=' + ('mention' if c['mention'] else 'no mention') + ',' + ('cited' if brand_cited(c) else 'not cited') for c in relevant)
            row['competitors_named'] = '; '.join(sorted({v for c in cs for v in c['competitors_named']}))
            row['check_date_day1'] = dates[0] if dates else ''
            row['check_date_day2'] = dates[1] if len(dates) > 1 else ''
            row['changed_on_day2'] = compare_days(cs, dates[:2])
            row['raw_answers_url'] = 'exports/checks.jsonl#question_id=' + q['question_id'] if cs else ''
            row['notes'] = (str(row['notes']) + ' | Multi-check summaries; audit checks.jsonl. CSV completeness is workbook nonblank test, not assessment pass.').strip(' |')
            row['duplicate_check'] = 'UNIQUE'
            row['completeness_check'] = 'COMPLETE' if all(str(row[k]).strip() for k in REQUIRED) else 'MISSING FIELDS'
            rows.append(row)
        with (self.root / 'visibility.csv').open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=HEADERS)
            w.writeheader(); w.writerows(rows)
        return rows

    def report(self, end_day, config):
        end = datetime.fromisoformat(end_day).date()
        start = end - timedelta(days=6)
        cs = [c for c in self.checks() if start.isoformat() <= c['local_date'] <= end.isoformat()]
        groups = defaultdict(list)
        for c in cs:
            groups[(c['surface'], c['tool'], c['market'])].append(c)
        lines = ['# Weekly visibility report', '', f'Window: {start} to {end} (recorded observation-local dates).', 'No baseline measurements are invented. Rates exclude failed/unavailable checks. Unknown cost is not zero.', '', '| Surface | Tool | Market | Successful | Failed/unavailable | Mention rate | Citation rate |', '|---|---|---|---:|---:|---:|---:|']
        for (surface, tool, market), items in sorted(groups.items()):
            ok = [c for c in items if c['status'] == 'ok']
            ai = [c for c in ok if c['surface'] != 'google_search']
            rate = lambda n: f'{n / len(ai):.1%}' if ai else 'N/A'
            lines.append(f'| {surface} | {tool} | {market} | {len(ok)} | {len(items)-len(ok)} | {rate(sum(c["mention"] for c in ai))} | {rate(sum(brand_cited(c) for c in ai))} |')
        lines += ['', '## Google observations', '| Market | Successful | Ranked within depth | Mean found position | Answer-feature presence | IncuBrix quoted share |', '|---|---:|---:|---:|---:|---:|']
        for market in sorted({c['market'] for c in cs if c['surface']=='google_search'}):
            gs = [c for c in cs if c['market']==market and c['surface']=='google_search' and c['status']=='ok']
            positions = [c['google_position'] for c in gs if c['google_position'] is not None]
            avg = f'{sum(positions)/len(positions):.2f}' if positions else 'N/A'
            feature = sum(c['answer_box_or_ai_overview']!='none' for c in gs)
            quoted = sum(any((urlparse(u).hostname or '').lower() in ('incubrix.com','www.incubrix.com') for u in c['quoted_source_urls']) for c in gs)
            fr = f'{feature/len(gs):.1%}' if gs else 'N/A'
            qr = f'{quoted/len(gs):.1%}' if gs else 'N/A'
            lines.append(f'| {market} | {len(gs)} | {len(positions)} | {avg} | {fr} | {qr} |')
        lines += ['Mean position excludes not-found checks; always interpret it with ranked-within-depth count. Quoted share uses all successful Google checks as denominator, not only checks with answer features.']
        qs = self.questions()
        markets = config.get('markets', ['US', 'GB', 'IN'])
        lines += ['', '## Coverage gaps (strict grid)', f'Questions with source records: {len(qs)} / 100 required.', 'Each sourced question needs Google plus four named consumer assistants in each market on at least two distinct dates, with explicit location_verified=true. This is a recorded reviewer assertion, not independent location proof. Model APIs are shown separately and never satisfy consumer-assistant coverage.']
        complete = 0
        targets = ['Google', 'ChatGPT', 'Gemini', 'Perplexity', config.get('fourth_assistant', 'Claude')]
        missing = []
        for q in qs:
            gaps = []
            for m in markets:
                for tool in targets:
                    dates = {c['local_date'] for c in self.checks() if c['question_id']==q['question_id'] and c['market']==m and c['tool'].casefold()==tool.casefold() and c['status']=='ok' and c.get('location_verified') is True and c['surface']==('google_search' if tool=='Google' else 'consumer_assistant')}
                    if len(dates) < 2:
                        gaps.append(f'{m}/{tool}: {len(dates)}/2 days')
            if not gaps:
                complete += 1
            else:
                missing.append({'question_id': q['question_id'], 'gaps': gaps})
        lines += [f'Questions meeting full configured coverage grid: {complete}.', f'Markets: {", ".join(markets)}.', f'Week checks: {len(cs)}. Runtime and attempts: logs/events.jsonl.', '', 'This report is not proof of 85% independent audit reproducibility. The reviewer must sample actual evidence.']
        costs = defaultdict(float)
        unknown_cost = 0
        for c in cs:
            if 'cost' in c:
                costs[c['cost']['currency']] += c['cost']['amount']
            else:
                unknown_cost += 1
        events = [e for e in read_jsonl(self.root/'logs/events.jsonl') if start.isoformat() <= e.get('at','')[:10] <= end.isoformat()]
        runtimes = [e['runtime_seconds'] for e in events if e['event'] in ('collection_ok','collection_error')]
        baseline_checks = max(100, len(qs)) * len(markets) * 5 * 2
        lines += ['', '## Runtime and cost', f'Configured minimum baseline size: {baseline_checks} checks (questions x markets x five surfaces x two days).', f'Known recorded check costs by currency: {dict(costs)}; checks with unknown cost: {unknown_cost}.', 'No unmeasured subscription allocation or manual labor is treated as free.']
        if runtimes:
            average = sum(runtimes)/len(runtimes)
            lines += [f'Collector attempts logged in UTC report window: {len(runtimes)}; measured attempt time: {sum(runtimes):.3f}s; mean {average:.3f}s.', f'Illustrative serial time for {baseline_checks} attempts at that observed mean: {baseline_checks*average/3600:.2f} hours, excluding manual work, queueing and additional retries. Not an SLA.']
        else:
            lines += ['No external collection runtime measured; no scale-speed claim is supported.']
        (self.root / 'reports/weekly.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        (self.root / 'reports/coverage_gaps.json').write_text(json.dumps(missing, indent=2), encoding='utf-8')
        return dict(questions=len(qs), full_coverage=complete, week_checks=len(cs))

    def brief(self, qid):
        q = next((x for x in self.questions() if x['question_id']==qid), None)
        if not q:
            raise ValueError('unknown question_id')
        cs = [c for c in self.checks() if c['question_id']==qid and c['status']=='ok']
        urls = sorted({u for c in cs for u in c.get('citations', []) + c.get('quoted_source_urls', [])})
        text = '\n'.join(['# Evidence-grounded page brief (not publish-ready content)', '', 'Question: '+q['question'], 'Intent: '+q['intent'], 'Question source: '+q['source_url'], '', '## Observed citation leads (verify before citing)', *(urls or ['No observed citations collected.']), '', '## Required drafting work', '- Answer the real question in the first two sentences; do not force the brand.', '- Verify every IncuBrix feature claim in the product; absent evidence means omit it.', '- Add original steps, accurate sources, relevant internal links and appropriate validated structured data.', '- Record author/review date and validation evidence.', '', 'Evidence: exports/checks.jsonl; source excerpts: exports/questions.jsonl.', 'This template is not one of the ten completed publish-ready pages.'])
        path = self.root / 'briefs' / (qid + '.md')
        path.write_text(text+'\n', encoding='utf-8')
        return str(path)

def brand_cited(c):
    return any((urlparse(u).hostname or '').lower() in ('incubrix.com', 'www.incubrix.com') for u in c.get('citations', []))

def compare_days(checks, days):
    if len(days)<2:
        return ''
    def snapshot(day):
        out = defaultdict(set)
        for c in checks:
            if c['local_date']==day:
                key = (c['market'],c['tool'],c['surface'],c['model'],c['mode'])
                out[key].add(json.dumps({k:c.get(k) for k in ('google_position','answer_box_or_ai_overview','quoted_source_urls','mention','citations','competitors_named')},sort_keys=True))
        return out
    a,b = map(snapshot,days)
    if set(a)!=set(b):
        return 'NOT COMPARABLE: coverage differs'
    return 'YES' if a != b else 'NO'

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run','import-questions','import-checks','brief'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--file', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--day', default=datetime.now().astimezone().date().isoformat())
    parser.add_argument('--question-id')
    args = parser.parse_args(argv)
    t = Tracker(args.root)
    config_path = args.config or t.root/'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    started = time.monotonic()
    if args.action.startswith('import-'):
        if not args.file:
            parser.error('--file required')
        result = t.import_file(args.action.removeprefix('import-'), args.file)
    elif args.action=='brief':
        result = {'brief':t.brief(args.question_id)}
    else:
        result = {'collection':t.collect(config,args.day)}
        result['csv_rows'] = len(t.export())
        result['report'] = t.report(args.day,config)
    t.log('run_end', action=args.action, runtime_seconds=round(time.monotonic()-started,3))
    print(json.dumps(result, indent=2))
    return 2 if result.get('errors',0) or result.get('collection',{}).get('errors',0) else 0

if __name__=='__main__':
    sys.exit(main())
