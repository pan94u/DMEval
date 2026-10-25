import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import store

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.patch=patch.object(store,'DB',Path(self.tmp.name)/'test.sqlite3')
        self.patch.start()
        store.initialize()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def task(self,**kwargs):
        return store.create_task(dict(name='test',sample_ids=['route-zh'],models=['clef'],**kwargs))

    def test_migration_idempotent(self):
        count=len(store.samples())
        store.initialize()
        self.assertEqual(len(store.samples()),count)

    def test_edit_and_delete_do_not_change_task_snapshot(self):
        tid=self.task()
        before=store.task_detail(tid)['samples']
        s=next(s for s in store.samples() if s['id']=='route-zh')
        s['case']['state']='new content'
        store.save_sample(s)
        store.archive_sample(s['id'])
        self.assertEqual(store.task_detail(tid)['samples'],before)
        self.assertFalse(any(s['id']=='route-zh' for s in store.samples()))

    def test_stale_editor_cannot_overwrite(self):
        s=store.samples()[0]
        store.save_sample(s)
        with self.assertRaises(ValueError):
            store.save_sample(s)

    def test_import_is_atomic_on_duplicate(self):
        cases=store.engine.load_cases(store.ROOT/'data/smoke.jsonl')
        fresh=copy.deepcopy(cases[0]);fresh['id']='new'
        with self.assertRaises(ValueError):
            store.import_samples([fresh,cases[0]])
        self.assertFalse(any(s['id']=='new' for s in store.samples()))

    def test_task_lifecycle_and_clone(self):
        tid=self.task()
        self.assertEqual(store.task_detail(tid)['status'],'draft')
        store.task_action(tid,'start')
        self.assertEqual(store.task_detail(tid)['status'],'queued')
        store.task_action(tid,'cancel')
        self.assertEqual(store.task_detail(tid)['status'],'cancelled')
        clone=store.task_action(tid,'clone')
        self.assertEqual(store.task_detail(clone)['samples'],store.task_detail(tid)['samples'])
        self.assertEqual(store.task_detail(clone)['status'],'draft')
        store.task_action(tid,'archive')
        self.assertFalse(any(t['id']==tid for t in store.tasks()))

    def test_invalid_model_and_missing_samples_rejected(self):
        for config in [dict(models=['invalid'],sample_ids=['route-zh']),dict(models=['clef'],sample_ids=[]),dict(models=['clef'],sample_ids=['missing'])]:
            with self.assertRaises(ValueError):
                store.create_task(dict(name='test',**config))

    def test_probability_threshold_boundary_is_positive(self):
        case={'questions':{'q':{'type':'noul'}},'expected':{'q':True}}
        row=store.engine.evaluate(case,{'answers':{'q':{'noul':.5}}})[0]
        self.assertEqual(row['correct'],1)

    def test_policy_persists_and_clone_inherits_without_changing_observations(self):
        tid=self.task()
        detail=store.task_detail(tid)
        rule=detail['samples'][0]['question_rules']['urgent']
        before=detail['samples']
        store.save_policy(tid,'clef',rule,.7314)
        detail=store.task_detail(tid)
        self.assertEqual(detail['decision_policy'][0]['threshold'],.7314)
        self.assertEqual(detail['samples'],before)
        self.assertEqual(detail['results'],[])
        clone=store.task_action(tid,'clone')
        self.assertEqual(store.task_detail(clone)['decision_policy'][0]['threshold'],.7314)

    def test_policy_rejects_invalid_scope_and_values(self):
        tid=self.task();rule=store.task_detail(tid)['samples'][0]['question_rules']['urgent']
        for value in (-.01,1.01,float('nan'),float('inf'),True,'0.5'):
            with self.assertRaises(ValueError):
                store.save_policy(tid,'clef',rule,value)
        for model,rid in [('clef-flash',rule),('clef','unknown')]:
            with self.assertRaises(ValueError):
                store.save_policy(tid,model,rid,.7)

    def test_removing_pre_task_records_preserves_task_results(self):
        tid=self.task()
        with store.connect() as db:
            for rid in (tid,'pre-task-record'):
                db.execute('INSERT INTO runs VALUES (?,?,?)',(rid,0,'{}'))
                db.execute('INSERT INTO results VALUES (?,?,?,?,?,?,?)',(rid,'clef','route-zh',0,'error',0,'{}'))
        self.assertEqual(store.remove_unassigned_records(),1)
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT id FROM runs').fetchall()[0][0],tid)
            self.assertEqual(db.execute('SELECT run FROM results').fetchall()[0][0],tid)

    def test_task_score_tolerance_is_explicit(self):
        tid=self.task(score_tolerance=.25)
        self.assertEqual(store.task_detail(tid)['config']['score_tolerance'],.25)
        with self.assertRaises(ValueError):
            self.task(score_tolerance=-1)

if __name__=='__main__':
    unittest.main()
