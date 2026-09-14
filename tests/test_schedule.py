import json

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

from dsp_dreamer import InvalidRecording, open_dataset
from dsp_dreamer.contract import file_info, load
from dsp_dreamer.dataset import table_contract
from dsp_dreamer.reschedule import reschedule_dataset
from dsp_dreamer.progress import reschedule_rows
from dsp_dreamer.training_index import TrainingIndex
from test_progress import compile_progress_fixture


def batches():
    def miner(item):
        return dict(kind='miner_output', item_id=item, vein_item_id=item, entity_id=item,
                    factory_index=0, proto_id=2301, power=1., network_id=1, count=1)
    return [
        [dict(kind='lander_work', work_ticks=1)],
        [dict(kind='research_queue', tech_ids=[1001,1002,1003,1004,1005])],
        [dict(kind='lander_removed')],
        [dict(kind='craft_queued', item_ids=[1202,1301], item_counts=[10,10])],
        [dict(kind='item_received', origin='lander', item_id=1801, count=1),
         dict(kind='fuel_inserted', item_id=1801, count=1, reactor_count=1)],
        [dict(kind='item_received', origin='manual', item_id=1002, count=4)],
        [dict(kind='tech_state', tech_id=1001, unlocked=True)],
        [miner(1001)],
        [dict(kind='research_supply', tech_id=1002, remaining_hash=1,
              item_ids=[1202], item_points=[1], buffered_points=[1]),
         dict(kind='tech_state', tech_id=1002, unlocked=True)],
        [miner(1002)],
    ]


def test_schedule_restarts_at_episode_boundary_without_cross_episode_reward():
    def row(episode, following, done, completed):
        return dict(episode_id=episode,next_episode_id=following,
            microtask_completed=[int(i in done) for i in range(16)],milestone_completed=[0]*7,
            node_completions=completed,reward_vector=[int(i in completed) for i in range(16)])
    rows=[row('a','a',[],[0]),row('a','b',[0],[]),row('b','b',[],[0])]
    result=reschedule_rows(rows,4)
    assert [r['task_id'] for r in result]==[0,1,0]
    assert [r['next_task_id'] for r in result]==[1,0,1]
    assert [r['reward'] for r in result]==[1,0,1]


@pytest.mark.parametrize('version', [3,4])
def test_native_compiler_schedule_and_parallel_completion(tmp_path, version):
    data=compile_progress_fixture(tmp_path, batches(), version=version)
    assert data.rows[6]['next_task_id'] == (6 if version==4 else 5)
    assert data.rows[7]['node_completions']==[6]
    assert data.rows[7]['reward'] == (1 if version==4 else 0)
    assert data.rows[8]['node_completions']==[5,18]
    assert data.rows[8]['next_task_id']==7  # Research cannot preempt copper; early supply is retained.
    assert data.rows[9]['reward']==1 and data.rows[9]['next_task_id']==8


def test_derivative_preserves_source_rejects_mixed_schedules_and_tampering(tmp_path):
    source=compile_progress_fixture(tmp_path/'old', batches(), version=3)
    before=file_info(source.path/'COMPLETED')
    with pytest.raises(InvalidRecording, match='overlap'):
        reschedule_dataset(source.path,source.path/'nested-derivative')
    assert not (source.path/'nested-derivative').exists()
    output=reschedule_dataset(source.path,tmp_path/'new')
    new=open_dataset(output)
    assert new.metadata['progress_version']==4
    assert new.metadata['source_artifact_id']==source.metadata['source_artifact_id']
    assert new.metadata['rescheduled_from']['completed']==before
    assert file_info(source.path/'COMPLETED')==before
    assert file_info(output/'events.parquet')==file_info(source.path/'events.parquet')
    assert new.metadata['rgb_sha256']==source.metadata['rgb_sha256']
    changed={'task_id','next_task_id','task_condition','reward'}
    for old,row in zip(source.rows,new.rows):
        assert {k:v for k,v in old.items() if k not in changed}=={k:v for k,v in row.items() if k not in changed}
    registry={'schema':'dsp-split-registry/1','manifests':[{'manifest_id':'trial','split_group_id':'trial','purpose':'demonstration'}]}
    with pytest.raises(InvalidRecording, match='mix'):
        TrainingIndex([source.path,output],registry)
    with pytest.raises(InvalidRecording, match='overwrite'):
        reschedule_dataset(source.path,output)
    # A self-consistent scalar/condition plus fresh file hashes cannot conceal the old priority.
    new.rows[7].update(task_id=5,task_condition=[int(i==5) for i in range(17)],reward=0)
    pq.write_table(pa.Table.from_pylist(new.rows),output/'transitions.parquet',compression='zstd',row_group_size=1024)
    metadata=load(output/'dataset.json')
    metadata['tables']['transitions.parquet']=table_contract(output/'transitions.parquet')
    (output/'dataset.json').write_text(json.dumps(metadata))
    completed=load(output/'COMPLETED')
    for name in ['dataset.json','transitions.parquet']:completed['files'][name]=file_info(output/name)
    (output/'COMPLETED').write_text(json.dumps(completed))
    with pytest.raises(InvalidRecording, match='schedule mismatch'):
        open_dataset(output)
