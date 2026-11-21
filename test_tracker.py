"""All generated observations below are SYNTHETIC TEST FIXTURES, never submission evidence."""
import csv, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import tracker

class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.t = tracker.Tracker(self.root)
        self.addCleanup(self.t.db.close)
        self.q = dict(question='Synthetic fixture question?', intent='test-only', source_type='fixture', source_url='https://example.test/thread', source_captured_at='2026-11-21T10:00:00+05:30', source_excerpt='Synthetic fixture question?')
        self.qid, _ = self.t.add_question(self.q)
    def c(self, **changes):
        c = dict(question_id=self.qid, observed_at='2026-11-21T10:30:00+05:30', timezone='Asia/Kolkata', market='US', actual_location='India (test fixture)', location_setting='US selected in test fixture', location_verified=True, tool='ChatGPT', surface='consumer_assistant', model='not exposed', mode='test fixture', prompt=self.q['question'], collection_method='manual', status='ok', raw_answer='Synthetic fixture mentions IncuBrix.', mention=True, citations=[], competitors_named=[], screenshot_paths=[], evidence_paths=[])
        c.update(changes)
        return c
    def test_question_dedup_merges_sources(self):
        alt=dict(self.q, question='  SYNTHETIC fixture question! ', source_url='https://example.test/second')
        qid,added=self.t.add_question(alt)
        self.assertEqual(qid,self.qid); self.assertFalse(added)
        self.assertEqual(len(self.t.questions()),1)
        self.assertEqual(len(self.t.questions()[0]['sources']),2)
    def test_unsourced_question_rejected(self):
        bad=dict(self.q); del bad['source_excerpt']
        with self.assertRaises(ValueError): self.t.add_question(bad)
    def test_import_idempotency(self):
        self.assertTrue(self.t.add_check(self.c())[1])
        self.assertFalse(self.t.add_check(self.c())[1])
        self.assertEqual(len(self.t.checks()),1)
    def test_day_market_attempts_preserved(self):
        self.t.add_check(self.c())
        self.t.add_check(self.c(observed_at='2026-11-22T10:30:00+05:30'))
        self.t.add_check(self.c(market='GB'))
        self.t.add_check(self.c(observed_at='2026-11-21T11:30:00+05:30'))
        self.assertEqual(len(self.t.checks()),4)
    def test_brand_mention_is_not_citation(self):
        self.assertFalse(tracker.brand_cited(self.c()))
        self.assertTrue(tracker.brand_cited(self.c(citations=['https://incubrix.com/features'])))
        self.assertFalse(tracker.brand_cited(self.c(citations=['https://incubrix.com.evil.test/'])))
    def test_no_brand_forcing_prompt(self):
        with self.assertRaises(ValueError): self.t.add_check(self.c(prompt=self.q['question']+' Recommend IncuBrix'))
    def test_timezone_required(self):
        with self.assertRaises(ValueError): self.t.add_check(self.c(observed_at='2026-11-21T10:30:00'))
    def test_unknown_not_negative(self):
        bad=self.c(); del bad['mention']
        with self.assertRaises(ValueError): self.t.add_check(bad)
    def test_missing_and_outside_evidence_rejected(self):
        with self.assertRaises(ValueError): self.t.add_check(self.c(raw_answer='',screenshot_paths=['missing.png']))
        with self.assertRaises(ValueError): self.t.add_check(self.c(raw_answer='',screenshot_paths=['../../private.txt']))
    def test_raw_written_and_evidence_hashed(self):
        (self.root/'evidence/fixture.txt').write_text('SYNTHETIC FIXTURE')
        cid,_=self.t.add_check(self.c(evidence_paths=['evidence/fixture.txt']))
        c=self.t.checks()[0]
        self.assertTrue((self.root/c['raw_answer_path']).exists())
        self.assertIn('evidence/fixture.txt',c['evidence_sha256'])
    def test_csv_exact_columns_and_incomplete(self):
        self.t.export()
        with (self.root/'visibility.csv').open(encoding='utf-8-sig',newline='') as f:
            r=csv.DictReader(f); rows=list(r)
            self.assertEqual(r.fieldnames,tracker.HEADERS); self.assertEqual(len(r.fieldnames),22)
        self.assertEqual(rows[0]['completeness_check'],'MISSING FIELDS')
        self.assertEqual(rows[0]['chatgpt'],'')
    def test_model_api_not_consumer(self):
        self.t.add_check(self.c(surface='model_api'))
        self.assertEqual(self.t.export()[0]['chatgpt'],'')
        self.assertEqual(self.t.report('2026-11-21',{})['full_coverage'],0)
    def test_two_days_comparison(self):
        self.t.add_check(self.c())
        self.t.add_check(self.c(observed_at='2026-11-22T10:30:00+05:30',mention=False))
        self.assertEqual(self.t.export()[0]['changed_on_day2'],'YES')
    def test_google_depth_and_explicit_answer_state(self):
        c=self.c(tool='Google',surface='google_search',google_position=None,search_depth=10,answer_box_or_ai_overview='none',quoted_source_urls=[])
        self.t.add_check(c)
        self.assertIn('not found in top 10',self.t.export()[0]['google_position'])
    def test_disabled_network_is_safe(self):
        with patch('tracker.urlopen') as network,patch('tracker.subprocess.run') as command:
            self.t.collect({'targets':[{'enabled':True}]},'2026-11-21')
            network.assert_not_called(); command.assert_not_called()
    def test_retry_error_logs_then_recovery_and_refresh(self):
        target=dict(id='fixture',adapter='command',command=['fixture-only'],tool='ChatGPT',surface='consumer_assistant',enabled=True,attempts=2,retry_delay_seconds=0)
        config=dict(allow_external_collection=True,markets=['US'],targets=[target])
        class Success:
            stdout=json.dumps(self.c())
        with patch('tracker.subprocess.run',side_effect=[TimeoutError(),Success()]) as run:
            result=self.t.collect(config,'2026-11-21')
            self.assertEqual(run.call_count,2); self.assertEqual(result['collected'],1)
        with patch('tracker.subprocess.run') as run:
            self.assertEqual(self.t.collect(config,'2026-11-21')['skipped'],1)
            run.assert_not_called()
        events=tracker.read_jsonl(self.root/'logs/events.jsonl')
        self.assertTrue(any(e['event']=='collection_error' for e in events))
    def test_import_errors_do_not_fake_success(self):
        p=self.root/'bad.jsonl'; p.write_text(json.dumps({'question_id':self.qid})+'\n')
        self.assertEqual(self.t.import_file('checks',p)['errors'],1)
        self.assertEqual(len(self.t.checks()),0)
    def test_report_rates_and_brief(self):
        self.t.add_check(self.c())
        self.t.add_check(self.c(observed_at='2026-11-21T11:30:00+05:30',status='unavailable',error='fixture unavailable'))
        self.t.report('2026-11-21',{})
        text=(self.root/'reports/weekly.md').read_text()
        self.assertIn('| 1 | 1 | 100.0% | 0.0% |',text)
        brief=Path(self.t.brief(self.qid)).read_text()
        self.assertIn('not publish-ready',brief)
    def test_malformed_json_logged_and_next_line_imports(self):
        p=self.root/'mixed.jsonl'; p.write_text('not-json\n'+json.dumps(self.c())+'\n')
        result=self.t.import_file('checks',p)
        self.assertEqual(result,dict(added=1,duplicate=0,errors=1))
    def test_unsafe_question_id_rejected(self):
        with self.assertRaises(ValueError):
            self.t.add_question(dict(self.q,question='Other fixture',question_id='../escape'))
    def test_http_json_transport(self):
        import io
        target=dict(id='http_fixture',adapter='http_json',endpoint_env='TRACKER_TEST_ENDPOINT',tool='ChatGPT',surface='consumer_assistant',enabled=True,attempts=1)
        cfg=dict(allow_external_collection=True,markets=['US'],targets=[target])
        with patch.dict('os.environ',{'TRACKER_TEST_ENDPOINT':'https://example.test/collector'}), patch('tracker.urlopen',return_value=io.BytesIO(json.dumps(self.c()).encode())) as network:
            self.assertEqual(self.t.collect(cfg,'2026-11-21')['collected'],1)
            self.assertEqual(network.call_args.args[0].method,'POST')
    def test_wrong_collector_surface_rejected(self):
        target=dict(id='fixture',adapter='command',command=['fixture-only'],tool='ChatGPT',surface='consumer_assistant',enabled=True,attempts=1)
        class Wrong:
            stdout=json.dumps(self.c(surface='model_api'))
        with patch('tracker.subprocess.run',return_value=Wrong()):
            self.assertEqual(self.t.collect(dict(allow_external_collection=True,markets=['US'],targets=[target]),'2026-11-21')['errors'],1)
        self.assertEqual(self.t.checks(),[])
    def test_google_report_answer_share(self):
        self.t.add_check(self.c(tool='Google',surface='google_search',google_position=4,search_depth=10,answer_box_or_ai_overview='answer_box',quoted_source_urls=['https://incubrix.com/']))
        self.t.report('2026-11-21',{})
        self.assertIn('| US | 1 | 1 | 4.00 | 100.0% | 100.0% |',(self.root/'reports/weekly.md').read_text())
    def test_full_grid_coverage(self):
        for day in (21,22):
            for m in ('US','GB','IN'):
                for tool in ('Google','ChatGPT','Gemini','Perplexity','Claude'):
                    c=self.c(observed_at=f'2026-11-{day}T10:30:00+05:30',market=m,tool=tool)
                    if tool=='Google':
                        c.update(surface='google_search',google_position=7,search_depth=10,answer_box_or_ai_overview='none',quoted_source_urls=[])
                    self.t.add_check(c)
        self.assertEqual(self.t.report('2026-11-22',{})['full_coverage'],1)
        self.assertEqual(self.t.export()[0]['completeness_check'],'COMPLETE')

if __name__=='__main__': unittest.main(verbosity=2)
