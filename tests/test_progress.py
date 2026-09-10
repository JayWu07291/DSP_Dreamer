from pathlib import Path
import json
import subprocess

import numpy as np
import pytest

from dsp_dreamer import Recording, compile_recording, open_dataset, InvalidRecording
from dsp_dreamer.contract import file_info


FFMPEG = Path(r"E:\SubtitleEdit-Windows-x64\SpeechToText\Purfview-Faster-Whisper-XXL\ffmpeg.exe")


def compile_progress_fixture(tmp_path, batches, success=False):
    project = Path(__file__).parent / "ProgressReplay" / "ProgressReplay.csproj"
    subprocess.run(["dotnet", "build", str(project), "-c", "Release", "--nologo", "--no-restore"], check=True)
    runner = project.parent / "bin" / "Release" / "net472" / "ProgressReplay.exe"
    techs = [1001, 1002, 1003, 1004, 1005]
    with Recording.synthetic(tmp_path / "source", FFMPEG) as recording:
        recording.metadata.update(progress_version=2, progress_tech_ids=techs)
        recording.begin_attempt(dict(manifest_id="trial", split_group_id="trial", mecha_seed=1, camera_seed=2, policy_seed=3))
        episode = recording.episode["episode_id"]
        recording.input(0, held=[], down=[], up=[], delta=[0, 0], wheel=0)
        for index, batch in enumerate([[]] + batches):
            ticks = (index + 1) * 50
            for fact in batch:
                recording.event(ticks - 1, "progress_fact", episode_id=episode, **fact)
            if success and index == len(batches):
                recording.end_episode(ticks, outcome="success")
            request = recording.request(ticks, 1, 1)
            recording.event(ticks, "progress_observation", episode_id=episode, capture_id=request["capture_id"])
            recording.complete(request, np.zeros((360, 640, 4), dtype=np.uint8))
        if not success:
            recording.end_episode(ticks + 1, reason="stopped")
        events = [e for e in recording.events if e.get("name", "").startswith("progress_")]
        result = subprocess.run([str(runner)], input=json.dumps(dict(tech_ids=techs, version=2)) + "\n" +
                                "\n".join(map(json.dumps, events)) + "\n", capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True)
        claims = {e["capture_id"]: e for e in map(json.loads, result.stdout.splitlines())}
        for event in events:
            if event["name"] == "progress_observation":
                event.update(claims[event["capture_id"]])
    evidence = recording.publish(tmp_path / "evidence")
    return open_dataset(compile_recording(evidence, tmp_path / "dataset", FFMPEG))


def test_research_requires_all_remaining_materials_and_latches_after_takeback(tmp_path):
    def supply(points):
        return dict(kind="research_supply", tech_id=1002, remaining_hash=10,
                    item_ids=[1202, 1301], item_points=[2, 3], buffered_points=points)

    dataset = compile_progress_fixture(tmp_path, [
        [supply([20, 29])], [supply([20, 30])], [supply([0, 0])],
        [dict(kind="tech_state", tech_id=i, unlocked=True) for i in range(1001, 1006)],
        [dict(kind="tech_state", tech_id=1002, unlocked=False)],
    ])
    assert dataset[0]["node_completions"] == []
    assert dataset[1]["node_completions"] == [5] and dataset[1]["reward"] == 0
    assert dataset[2]["microtask_completed"][5] == 1 and dataset[2]["node_completions"] == []
    assert dataset[3]["node_completions"] == [17, 18, 19, 20, 21]
    assert dataset[4]["milestone_completed"] == [0, 1, 1, 1, 1, 1, 0]


def machine(product, entity):
    proto, requires, counts, batch = {
        1101: (2302, [1001], [1], 1), 1102: (2302, [1001], [1], 1),
        1104: (2302, [1002], [1], 1), 1202: (2303, [1102, 1104], [2, 1], 2),
        1301: (2303, [1101, 1104], [2, 1], 2), 6001: (2901, [1202, 1301], [1, 1], 1),
    }[product]
    return dict(kind="machine_config", target=f"m:0:{entity}", product=product, proto_id=proto,
                recipe_id=product, requires=requires, counts=counts, batch_size=batch)


def step(entity, before, after, cycles=0, output_before=0, auto_input=True):
    return dict(kind="machine_step", target=f"m:0:{entity}", before=before, after=after,
                cycles=cycles, output_before=output_before, auto_input=auto_input)


def transfer(source, target, item, count, before=None):
    return dict(kind="flow_transfer", source=source, target=target, item_id=item,
                count=count, source_before=count if before is None else before)


def feed(source, entity, item, count, before=None):
    return [transfer(source, f"s:0:{entity}", item, count, before),
            transfer(f"s:0:{entity}", f"m:0:{entity}", item, count)]


def production_batches(lab_manual=False):
    batches = [[machine(p, i) for p, i in ((1101, 1), (1102, 2), (1104, 3), (1202, 4), (1301, 5), (6001, 6))]]
    # Three fixed smelters produce manually first; no automatic line is complete.
    batches.append([event for i in (1, 2, 3) for event in
                    (step(i, [1], [0], auto_input=False), step(i, [0], [0], cycles=1, auto_input=False))])
    for entity, ore in ((1, 1001), (2, 1001), (3, 1002)):
        batch = [dict(kind="miner_stock", target="m:0:10", item_id=ore, count=2,
                      vein_item_id=ore, power=1.0, network_id=1, proto_id=2301),
                 transfer("m:0:10", f"c:0:{entity}", ore, 2)]
        batch += feed(f"c:0:{entity}", entity, ore, 2)
        batch += [step(entity, [2], [1]), step(entity, [1], [0], cycles=1),
                  step(entity, [0], [0], cycles=1, output_before=1)]
        batches.append(batch)
    batches.append(feed("m:0:2", 4, 1102, 2) + feed("m:0:3", 4, 1104, 1, 2) +
                   [step(4, [2, 1], [0, 0]), step(4, [0, 0], [0, 0], cycles=1)])
    batches.append(feed("m:0:1", 5, 1101, 2) + feed("m:0:3", 5, 1104, 1) +
                   [step(5, [2, 1], [0, 0]), step(5, [0, 0], [0, 0], cycles=1)])
    if lab_manual:
        batches.append([dict(kind="machine_manual", target="m:0:6", inserted=True)])
    batches.append(feed("m:0:4", 6, 1202, 1, 2) + feed("m:0:5", 6, 1301, 1, 2))
    batches.append([step(6, [1, 1], [0, 0])])
    batches.append([step(6, [0, 0], [0, 0], cycles=1)])
    return batches


@pytest.mark.parametrize("lab_manual", [False, True])
def test_full_production_requires_proven_materials_and_actual_lab_output(tmp_path, lab_manual):
    batches = production_batches(lab_manual)
    dataset = compile_progress_fixture(tmp_path, batches)
    assert dataset[1]["node_completions"] == [9]
    assert dataset[4]["node_completions"] == [11]
    assert dataset[5]["node_completions"] == [13]
    assert dataset[6]["node_completions"] == [14]
    assert dataset[len(dataset) - 3]["node_completions"] == ([] if lab_manual else [15])
    assert dataset[len(dataset) - 2]["node_completions"] == []
    assert dataset[len(dataset) - 1]["node_completions"] == ([] if lab_manual else [22])
    assert all(dataset[i]["reward"] == 0 and dataset[i]["task_id"] == 0 for i in range(len(dataset)))


@pytest.mark.parametrize("inventory", [[0, 0], [1, 0]])
def test_selecting_lab_recipe_is_not_manual_material_insertion(tmp_path, inventory):
    batches = production_batches()
    # Native OnItemButtonClick can select a recipe, allocating empty input slots.
    batches[0].append(dict(kind="manual_inventory", target="m:0:6", before=[], after=inventory))
    dataset = compile_progress_fixture(tmp_path, batches)
    assert (22 in dataset[len(dataset) - 1]["node_completions"]) == (inventory == [0, 0])


@pytest.mark.parametrize("fault", ["unpowered", "manual_belt", "no_belt", "recipe_switch", "mixed_stock", "manual_lab_reset"])
def test_unproven_sources_and_recipe_reuse_cannot_finish(tmp_path, fault):
    batches = production_batches(fault == "manual_lab_reset")
    if fault == "manual_lab_reset":
        batches[7].append(machine(6001, 6))
    for batch in batches:
        for fact in batch:
            if fault == "unpowered" and fact["kind"] == "miner_stock":
                fact["power"] = 0
            elif fault == "manual_belt" and fact.get("source") == "m:0:10":
                fact["source"] = "unknown"
            elif fault == "mixed_stock" and fact.get("source") == "m:0:3":
                fact["source_before"] += 1
            elif fault == "no_belt" and fact.get("target", "").startswith("c:"):
                fact["target"] = "discard"
            if fault == "no_belt" and fact.get("source", "").startswith("c:"):
                fact["source"] = "m:0:10"
            if fault == "recipe_switch":
                for field in ("source", "target"):
                    if fact.get(field) == "m:0:5":
                        fact[field] = "m:0:4"
    dataset = compile_progress_fixture(tmp_path, batches)
    assert not any(22 in row["node_completions"] for row in dataset.rows)


def test_progress_hooks_bind_to_supported_game_assemblies():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["dotnet", "build", str(root / "src/DSPDreamer.Recorder/DSPDreamer.Recorder.csproj"),
                    "--no-restore", "-c", "Release"], check=True)
    subprocess.run(["dotnet", "build", str(root / "tests/ProgressReplay/ProgressReplay.csproj"),
                    "--no-restore", "-c", "Release"], check=True)
    result = subprocess.run([str(root / "tests/ProgressReplay/bin/Release/net472/ProgressReplay.exe"),
                             r"E:\Steam\steamapps\common\Dyson Sphere Program",
                             str(root / "src/DSPDreamer.Recorder/bin/Release/DSPDreamer.Recorder.dll")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    assert "ProgressManualLabPatch" in result.stdout and "ProgressMinerPatch" in result.stdout


def test_every_task_prompt_advances_to_a_terminal_matrix_output(tmp_path):
    def tech(index):
        return [dict(kind="tech_state", tech_id=1001 + index, unlocked=True)]

    def supply(index):
        return [dict(kind="research_supply", tech_id=1001 + index, remaining_hash=1,
                     item_ids=[1202], item_points=[1], buffered_points=[1])]

    def miner(item, entity):
        return [dict(kind="miner_output", item_id=item, vein_item_id=item, entity_id=entity,
                     factory_index=0, proto_id=2301, power=1.0, network_id=1, count=1)]

    production = production_batches()
    batches = [
        [dict(kind="lander_work", work_ticks=1)],
        [dict(kind="research_queue", tech_ids=[1001, 1002, 1003, 1004, 1005])],
        [dict(kind="lander_removed")],
        [dict(kind="craft_queued", item_ids=[1202, 1301], item_counts=[10, 10])],
        [dict(kind="item_received", origin="lander", item_id=1801, count=3),
         dict(kind="fuel_inserted", item_id=1801, count=1, reactor_count=1)],
        [dict(kind="item_received", origin="manual", item_id=1002, count=4)],
        tech(0), supply(1), miner(1001, 10), miner(1002, 11), tech(1), supply(2),
        production[0], production[1], tech(2), supply(3), *production[2:5],
        tech(3), supply(4), production[5], production[6], tech(4), *production[7:],
    ]
    dataset = compile_progress_fixture(tmp_path, batches, success=True)
    prompts = [dataset[0]["task_id"]] + [dataset[i]["next_task_id"] for i in range(len(dataset))]
    assert prompts == [0, 1, 16, 2, 3, 4, 16, 5, 6, 7, 16, 8, 9, 9, 16,
                       10, 11, 11, 11, 16, 12, 13, 14, 16, 15, 16, 16, 16]
    assert sum(row["reward"] for row in dataset.rows) == 16
    assert sorted(n for row in dataset.rows for n in row["node_completions"]) == list(range(23))
    last = dataset[len(dataset) - 1]
    assert last["episode_outcome"] == "success" and last["is_terminal"] and last["bootstrap_mask"] == 0


def test_rebuilt_single_smelter_does_not_stand_in_for_three_furnaces(tmp_path):
    batches = []
    for product in (1101, 1102, 1104):
        batches.append([dict(kind="flow_reset", target="m:0:1"), machine(product, 1),
                        step(1, [1], [0], auto_input=False), step(1, [0], [0], cycles=1, auto_input=False)])
    dataset = compile_progress_fixture(tmp_path, batches)
    assert all(row["node_completions"] == [] for row in dataset.rows)


def test_production_facts_reject_legacy_version_and_inconsistent_input_width(tmp_path):
    compile_progress_fixture(tmp_path, [[machine(1101, 1)], [step(1, [0], [0])]])
    evidence = tmp_path / "evidence"
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["progress_version"] = 1
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidRecording, match="require progress version 2"):
        compile_recording(evidence, tmp_path / "legacy", FFMPEG)
    manifest["progress_version"] = 2
    events_path = evidence / "events.ndjson"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    event = next(e for e in events if e.get("kind") == "machine_step")
    event.update(before=[0, 0], after=[0, 0])
    events_path.write_text("\n".join(map(json.dumps, events)) + "\n")
    manifest["files"]["events.ndjson"] = file_info(events_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InvalidRecording, match="Machine input width differs"):
        compile_recording(evidence, tmp_path / "bad-width", FFMPEG)


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
