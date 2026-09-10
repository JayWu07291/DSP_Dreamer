from pathlib import Path
import json
import subprocess

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset, InvalidRecording
from dsp_dreamer.contract import file_info


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def test_early_progress_is_reconstructed_from_evidence(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata["progress_version"] = 1
        recording.metadata["progress_tech_ids"] = [1001, 1002, 1003, 1004, 1005]
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial",
                                     mecha_seed=1, camera_seed=2, policy_seed=3))
        episode_id = recording.episode["episode_id"]
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for ticks in (50, 100, 150, 200, 250):
            if ticks == 100:
                recording.event(60, "progress_fact", episode_id=episode_id, kind="lander_work", work_ticks=1)
                recording.event(70, "progress_fact", episode_id=episode_id, kind="research_queue",
                                tech_ids=[1001, 1002, 1003, 1004, 1005])
            if ticks == 150:
                recording.event(110, "progress_fact", episode_id=episode_id, kind="lander_removed")
                recording.event(120, "progress_fact", episode_id=episode_id, kind="craft_queued",
                                item_ids=[1202, 1301], item_counts=[10, 10])
                recording.event(130, "progress_fact", episode_id=episode_id, kind="item_received",
                                origin="lander", item_id=1801, count=3)
                recording.event(140, "progress_fact", episode_id=episode_id, kind="fuel_inserted", item_id=1801, count=1, reactor_count=1)
            if ticks == 200:
                recording.event(150, "progress_fact", episode_id=episode_id, kind="item_received",
                                origin="manual", item_id=1002, count=4)
            request = recording.request(ticks, 1, 1)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.end_episode(260, reason="stopped")
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert [dataset[i]["task_id"] for i in range(4)] == [0, 16, 4, 16]
    assert [dataset[i]["next_task_id"] for i in range(4)] == [16, 4, 16, 16]
    assert [dataset[i]["reward"] for i in range(4)] == [1, 0, 1, 0]
    assert dataset[0]["reward_vector"] == [1, 1] + [0] * 14
    assert dataset[1]["reward_vector"] == [0, 0, 1, 1] + [0] * 12
    assert dataset[2]["reward_vector"] == [0] * 4 + [1] + [0] * 11
    assert dataset[2]["milestone_completed"] == [1] + [0] * 6
    assert len(dataset[0]["task_condition"]) == 17
    assert dataset.sequence_starts(4) == [0]
    assert "progress_fact" not in dataset[0]  # 特權事實只保留在 evidence/event table。


def test_missing_capture_preserves_scheduler_boundary_and_validates_loader(tmp_path):
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=[1, 2, 3, 4, 5])
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        episode = recording.episode["episode_id"]
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        first = recording.request(50, 1, 1)
        recording.complete(first, np.zeros((360, 640, 4), dtype=np.uint8))
        recording.event(50, "progress_observation", episode_id=episode, capture_id=0)
        recording.event(60, "progress_fact", episode_id=episode, kind="lander_work", work_ticks=1)
        # 這個擷取要求丟失；它已啟用 queue_research，下一張有效畫面不可改寫歷史。
        recording.event(100, "progress_observation", episode_id=episode, capture_id=1)
        recording.event(110, "progress_fact", episode_id=episode, kind="lander_removed")
        for ticks in (150, 200):
            request = recording.request(ticks, 2, 2)
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
            recording.frames[-1]["capture_id"] += 1
            recording.event(ticks, "progress_observation", episode_id=episode, capture_id=recording.frames[-1]["capture_id"])
        recording.end_episode(220, reason="stopped")
    evidence = recording.publish(tmp_path / "evidence")
    dataset_path = compile_recording(evidence, tmp_path / "dataset", FFMPEG)
    dataset = open_dataset(dataset_path)
    assert dataset[0]["next_task_id"] == 1
    assert dataset[0]["reward"] == 1 and not dataset[0]["valid"]
    assert dataset[1]["task_id"] == 1 and dataset[1]["reward"] == 0
    assert dataset.sequence_starts(1) == [1]
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = pq.read_table(dataset_path / "transitions.parquet").to_pylist()
    rows[1]["reward"] = 1
    pq.write_table(pa.Table.from_pylist(rows), dataset_path / "transitions.parquet")
    completed = json.loads((dataset_path / "COMPLETED").read_text())
    completed["files"]["transitions.parquet"] = file_info(dataset_path / "transitions.parquet")
    (dataset_path / "COMPLETED").write_text(json.dumps(completed))
    with pytest.raises(InvalidRecording, match="scalar reward"):
        open_dataset(dataset_path)


def test_game_engine_and_offline_replay_agree_across_nonactive_completion_and_retry(tmp_path):
    project = Path(__file__).parent / "ProgressReplay" / "ProgressReplay.csproj"
    subprocess.run(["dotnet", "build", str(project), "-c", "Release", "--nologo", "--no-restore"], check=True)
    runner = project.parent / "bin" / "Release" / "net472" / "ProgressReplay.exe"
    techs = [1001, 1002, 1003, 1004, 1005]
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata.update(progress_version=1, progress_tech_ids=techs)
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for attempt, offset in enumerate((0, 1000)):
            recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
            episode = recording.episode["episode_id"]

            def fact(ticks, kind, **fields):
                recording.event(offset + ticks, "progress_fact", episode_id=episode, kind=kind, **fields)

            def observe(ticks):
                request = recording.request(offset + ticks, 1, 1)
                recording.event(offset + ticks, "progress_observation", episode_id=episode, capture_id=request["capture_id"])
                recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))

            observe(50)
            # 排程依賴不代替事實；非 active 完成不搶占 start_dismantle。
            fact(60, "research_queue", tech_ids=techs)
            fact(70, "tech_state", tech_id=techs[0], unlocked=True)
            fact(80, "craft_queued", item_ids=[1202, 1301], item_counts=[10, 10])  # 拆完前不計。
            fact(90, "item_received", origin="manual", item_id=1002, count=4)
            observe(100)
            fact(110, "lander_work", work_ticks=1)
            fact(120, "lander_removed")
            observe(150)
            # 正確礦種、實際產出及有效供電缺一不可。
            miner = dict(item_id=1001, count=1, vein_item_id=1001, network_id=1,
                         entity_id=10, factory_index=0, proto_id=2301, power=1.0)
            fact(160, "miner_output", **dict(miner, power=0))
            fact(170, "miner_output", **dict(miner, vein_item_id=1002))
            fact(180, "miner_output", **dict(miner, network_id=0))
            fact(190, "miner_output", **dict(miner, count=0))
            observe(200)
            fact(210, "craft_queued", item_ids=[1202, 1301], item_counts=[9, 10])
            fact(220, "item_received", origin="other", item_id=1002, count=100)
            fact(222, "item_received", origin="lander", item_id=1801, count=3)
            fact(223, "item_received", origin="other", item_id=1801, count=1)
            fact(224, "foreign_fuel_produced", count=1)
            fact(230, "fuel_inserted", item_id=1801, count=1, reactor_count=1)
            fact(240, "fuel_inserted", item_id=1801, count=1, reactor_count=1)  # 同一外來燃料反覆取放不算登陸艙來源。
            observe(250)
            fact(260, "craft_queued", item_ids=[1202], item_counts=[1])
            fact(280, "fuel_inserted", item_id=1801, count=2, reactor_count=3)
            fact(290, "item_received", origin="manual", item_id=1002, count=3)
            observe(300)
            fact(310, "item_received", origin="manual", item_id=1002, count=1)
            fact(320, "miner_output", **miner)
            fact(330, "miner_output", **dict(miner, item_id=1002, vein_item_id=1002, entity_id=11))
            observe(350)
            fact(360, "miner_output", **miner)
            fact(370, "tech_state", tech_id=techs[0], unlocked=False)
            fact(380, "tech_state", tech_id=techs[1], unlocked=True)  # 後期 predicate 尚未實作。
            recording.end_episode(offset + 390, reason="stopped")
            observe(400)
        ordered = sorted([e for e in recording.events if e.get("name", "").startswith("progress_")],
                         key=lambda e: (e["ticks"], e["name"] == "progress_fact", e["sequence_number"]))
        result = subprocess.run([str(runner)], input=json.dumps(techs) + "\n" + "\n".join(map(json.dumps, ordered)) + "\n",
                                capture_output=True, text=True, check=True)
        claims = {e["capture_id"]: e for e in map(json.loads, result.stdout.splitlines())}
        for event in recording.events:
            if event.get("name") == "progress_observation":
                event.update(claims[event["capture_id"]])
        for frame in recording.frames:
            claim = claims[frame["capture_id"]]
            frame.update(task_id=claim["task_id"], node_completed=claim["node_completed"])
    evidence = recording.publish(tmp_path / "evidence")
    dataset = open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))
    assert [dataset[i]["task_id"] for i in range(7)] == [0, 0, 2, 2, 2, 4, 5]
    assert [dataset[i]["reward"] for i in range(7)] == [0, 1, 0, 0, 1, 1, 0]
    assert dataset[0]["node_completions"] == [1, 17]
    assert dataset[5]["node_completions"] == [4, 6, 7]
    assert dataset[4]["microtask_completed"][3] == 0
    assert dataset[6]["milestone_completed"] == [1, 1, 0, 0, 0, 0, 0]
    assert dataset[7]["reward"] == 0 and not dataset[7]["valid"]  # 跨回合沒有 reward。
    assert dataset[8]["task_id"] == 0 and dataset[8]["microtask_completed"] == [0] * 16
    assert dataset.sequence_starts(6) == [0, 8]
    # 重新編譯相同證據，語意保持一致。
    again = open_dataset(compile_recording(evidence, tmp_path / "again", FFMPEG))
    assert dataset.rows == again.rows
    # 即使 checksum 被重算，錯誤的遊戲端進度宣告仍會被離線重播拒絕。
    path = evidence / "events.ndjson"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    next(e for e in rows if e.get("name") == "progress_observation")["task_id"] = 16
    path.write_text("\n".join(map(json.dumps, rows)) + "\n")
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["events.ndjson"] = file_info(path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidRecording, match="progress mismatch"):
        compile_recording(evidence, tmp_path / "rejected", FFMPEG)
