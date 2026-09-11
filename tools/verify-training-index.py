"""核對既有真實模型視圖的全部起點、抽樣及固定索引重跑結果。"""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dsp_dreamer.contract import atomic_save, file_info, require
from dsp_dreamer.training_index import TrainingIndex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, nargs="+", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    before = {str(p): file_info(p / "COMPLETED") for p in args.source}
    index = TrainingIndex.open(args.index, args.source)
    checks = []
    length = index.report["sequence_length"]
    for source in index.report["sources"]:
        view = index.views[source["artifact_id"]]
        expected, relevant, progress = [], [], []
        facts = {e["sequence_number"] for e in view.dataset.events if e.get("name") == "progress_fact"}
        if source["split"] is not None:
            for start in range(len(view) - length + 1):
                rows = view.rows[start:start + length]
                parts = [view.dataset.rows[r["start"]:r["stop"]] for r in rows]
                identities = {(p["episode_id"], p["attempt_id"]) for pair in parts for p in pair}
                legal = all(r["valid"] and len(pair) == 2 for r, pair in zip(rows, parts)) and len(identities) == 1
                legal &= all(not pair[0]["is_first"] for pair in parts[1:])
                if not legal:
                    continue
                expected.append(start)
                if any(r["node_completions"] for r in rows):
                    relevant.append(start)
                elif any(facts.intersection(r["event_refs"]) for r in rows):
                    progress.append(start)
        require((expected, relevant, progress) == (source["uniform"], source["relevant"], source["progress"]),
                "Index differs from exhaustive window verification")
        checks.append(dict(artifact_id=source["artifact_id"], legal_starts=len(expected),
                           relevant_starts=len(relevant), progress_starts=len(progress),
                           cross_task_starts=sum(any(r["task_switches"] for r in view.rows[s:s + length]) for s in expected)))
    loaded = 0
    for split, stats in index.report["splits"].items():
        if not stats["relevant_sequences"]:
            continue
        samples = index.sample_stage_two(split, 2, seed=19)
        require(samples == index.sample_stage_two(split, 2, seed=19), "Non-deterministic sampling")
        for sample in samples:
            batch = index.sequence(sample, burn_in=1)
            require(batch["valid_mask"].all() and not batch["loss_mask"][0], "Invalid masks")
            require(all(s["split_group_id"] == next(x["split_group_id"] for x in index.report["sources"]
                        if x["artifact_id"] == sample["artifact_id"]) for s in batch["source"]), "Sample crossed split group")
            for loss in ("dynamics", "policy", "reward"):
                enabled = (sample["pool"] == "uniform") == (loss == "dynamics")
                require((batch[f"{loss}_loss_mask"] == (batch["loss_mask"] & enabled)).all(), "Loss routing mismatch")
            loaded += 1
            del batch
    require(TrainingIndex(list(reversed(args.source)), index.report["registry"], length=length).report == index.report,
            "Corpus order changes index")
    require(before == {str(p): file_info(p / "COMPLETED") for p in args.source}, "Source changed")
    atomic_save(args.report, dict(status="passed", index=file_info(args.index), checks=checks,
                                 loaded_sequences=loaded, sources=before,
                                 verification_script=file_info(Path(__file__))))
    print("全部合法起點、重跑一致性與抽樣 masks 核對通過。")


if __name__ == "__main__":
    main()
