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

if __name__=='__main__':
    unittest.main()
