"""Replay early game facts. Scheduling dependencies never establish predicates."""
import math

from .contract import require
from .production import Production

TASKS = ["start_dismantle", "queue_research", "queue_crafting", "fuel_mecha", "mine_copper",
         "supply_metallurgy", "place_iron_miner", "place_copper_miner", "supply_logistics",
         "manual_smelting", "supply_manufacturing", "connect_smelters", "supply_matrix_tech",
         "setup_coil_line", "setup_board_line", "setup_lab", "wait_for_progress"]
MILESTONES = ["lander_done", "electromagnetism_done", "metallurgy_done", "logistics_done",
              "manufacturing_done", "matrix_tech_done", "matrix_done"]
# Milestone indices follow the 16 action nodes, not the waiting task ID.
DEPENDENCIES = [[], [0], [16], [16], [16], [17], [17], [17], [18], [18, 6, 4],
                [19], [9, 19, 6, 7], [20], [11, 20], [11, 20], [13, 14, 21]]
FIELDS = ("task_id", "next_task_id", "task_condition", "reward_vector", "reward",
          "microtask_completed", "milestone_completed", "node_completions", "progress_available")


def validate_fact(event):
    require(isinstance(event.get("episode_id"), str) and bool(event["episode_id"]), "Missing progress episode")
    kind = event.get("kind")
    integers = {
        "lander_work": ["work_ticks"], "lander_removed": [], "research_queue": [],
        "craft_queued": [], "item_received": ["item_id", "count"],
        "fuel_inserted": ["item_id", "count", "reactor_count"], "foreign_fuel_produced": ["count"], "tech_state": ["tech_id"],
        "miner_output": ["item_id", "count", "vein_item_id", "network_id", "entity_id", "factory_index", "proto_id"],
        "research_supply": ["tech_id", "remaining_hash"],
        "machine_config": ["product", "proto_id", "recipe_id", "batch_size"],
        "flow_reset": [], "flow_transfer": ["item_id", "count", "source_before"],
        "miner_stock": ["item_id", "count", "vein_item_id", "network_id", "proto_id"], "machine_manual": [],
        "machine_step": ["output_before", "cycles"],
        "manual_inventory": [], "line_state": [],
    }
    require(kind in integers, "Unknown progress fact")
    for field in integers[kind]:
        require(type(event.get(field)) is int and 0 <= event[field] <= 2147483647, f"Invalid progress {field}")
    for field in {"research_queue": ["tech_ids"], "craft_queued": ["item_ids", "item_counts"],
                  "research_supply": ["item_ids", "item_points", "buffered_points"],
                  "machine_config": ["requires", "counts"], "machine_step": ["before", "after"],
                  "manual_inventory": ["before", "after"], "line_state": ["items", "belts"]}.get(kind, []):
        require(isinstance(event.get(field), list) and all(type(x) is int and 0 <= x <= 2147483647 for x in event[field]),
                f"Invalid progress {field}")
    if kind == "craft_queued":
        require(len(event["item_ids"]) == len(event["item_counts"]), "Craft arrays differ")
    if kind == "research_supply":
        require(0 < len(event["item_ids"]) == len(event["item_points"]) == len(event["buffered_points"])
                and len(set(event["item_ids"])) == len(event["item_ids"])
                and all(x > 0 for x in event["item_ids"] + event["item_points"]), "Invalid research arrays")
    if kind in ("machine_config", "flow_reset", "flow_transfer", "miner_stock", "machine_manual", "machine_step", "manual_inventory", "line_state"):
        for field in (["source", "target"] if kind == "flow_transfer" else ["target"]):
            require(isinstance(event.get(field), str) and 0 < len(event[field]) <= 100
                    and event[field].split(":")[0] in ("m", "s", "c", "unknown", "discard"), "Invalid flow identity")
    if kind == "flow_transfer":
        require(event["source_before"] >= event["count"] > 0, "Invalid transfer count")
    if kind == "machine_config":
        require(len(event["requires"]) == len(event["counts"]) and len(event["requires"]) <= 6,
                "Invalid machine recipe arrays")
    if kind == "machine_step":
        require(len(event["before"]) == len(event["after"]) <= 6 and event["cycles"] in (0, 1)
                and all(a <= b for a, b in zip(event["after"], event["before"])), "Invalid machine step")
    if kind == "manual_inventory":
        require(max(len(event["before"]), len(event["after"])) <= 6, "Invalid manual inventory width")
    if kind == "line_state":
        require(type(event.get("powered")) is bool and isinstance(event.get("sources"), list)
                and len(event["sources"]) == len(event["items"]) == len(event["belts"]) <= 256
                and all(isinstance(s, str) and s.startswith("m:") and len(s) <= 100 for s in event["sources"])
                and all(b in (0, 1) for b in event["belts"]), "Invalid line connections")
    for fact_kind, field in (("machine_manual", "inserted"), ("machine_step", "auto_input")):
        if kind == fact_kind:
            require(type(event.get(field)) is bool, "Invalid production flag")
    if kind == "item_received":
        require(event.get("origin") in ("lander", "manual", "other"), "Unknown item origin")
    if kind == "tech_state":
        require(type(event.get("unlocked")) is bool, "Invalid tech state")
    if kind in ("miner_output", "miner_stock"):
        require(type(event.get("power")) in (int, float) and math.isfinite(event["power"])
                and event["power"] >= 0, "Invalid miner power")


def validate_progress_row(row, available):
    require(all(field in row for field in FIELDS), "Missing progress field")
    require(type(row["progress_available"]) is bool and row["progress_available"] == available, "Invalid progress availability")
    for field in ("task_id", "next_task_id"):
        require(type(row[field]) is int and 0 <= row[field] < 17, "Invalid task ID")
    for field, width in (("task_condition", 17), ("reward_vector", 16), ("microtask_completed", 16), ("milestone_completed", 7)):
        require(isinstance(row[field], list) and len(row[field]) == width
                and all(type(x) is int and x in (0, 1) for x in row[field]), "Invalid progress vector")
    require(row["task_condition"] == [int(i == row["task_id"]) for i in range(17)], "Invalid task condition")
    expected = row["reward_vector"][row["task_id"]] if row["task_id"] < 16 else 0
    require(type(row["reward"]) is int and row["reward"] == expected, "Invalid scalar reward")
    nodes = row["node_completions"]
    require(isinstance(nodes, list) and all(type(i) is int and 0 <= i < 23 for i in nodes)
            and nodes == sorted(set(nodes)), "Invalid node completions")
    require([int(i in nodes) for i in range(16)] == row["reward_vector"], "Invalid reward completions")
    if not available:
        require(row["task_id"] == row["next_task_id"] == 16 and not nodes and
                not any(row["microtask_completed"] + row["milestone_completed"]), "Legacy evidence cannot claim progress")


class Progress:
    def __init__(self, tech_ids, version=1):
        self.tech_ids = tech_ids
        self.version = version
        self.done = [0] * 23
        self.production = Production(self.done, version)
        self.active = 0
        self.coils = self.boards = self.copper = self.lander_fuel = self.foreign_fuel = 0

    def apply(self, event):
        kind = event["kind"]
        if self.version >= 2:
            self.production.apply(event)
        if kind == "lander_work" and event["work_ticks"] > 0:
            self.done[0] = 1
        elif kind == "lander_removed":
            self.done[16] = 1
        elif kind == "research_queue" and event["tech_ids"][:5] == self.tech_ids:
            self.done[1] = 1
        elif kind == "craft_queued" and self.done[16]:
            for item, count in zip(event["item_ids"], event["item_counts"]):
                if item == 1202:
                    self.coils += count
                elif item == 1301:
                    self.boards += count
            self.done[2] = int(self.coils >= 10 and self.boards >= 10)
        elif kind == "item_received":
            if event["origin"] == "lander" and event["item_id"] == 1801:
                self.lander_fuel += event["count"]
            if event["origin"] != "lander" and event["item_id"] == 1801:
                self.foreign_fuel += event["count"]
            if event["origin"] == "manual" and event["item_id"] == 1002 and self.done[16]:
                self.copper += event["count"]
                self.done[4] = int(self.copper >= 4)
        elif kind == "fuel_inserted" and self.done[16] and event["item_id"] == 1801:
            if self.lander_fuel > 0 and event["count"] > 0 and event["reactor_count"] > self.foreign_fuel:
                self.done[3] = 1
        elif kind == "foreign_fuel_produced":
            self.foreign_fuel += event["count"]
        elif kind == "tech_state" and event["tech_id"] in self.tech_ids and event["unlocked"]:
            index = self.tech_ids.index(event["tech_id"])
            if index == 0 or self.version >= 2:
                self.done[17 + index] = 1
        elif self.version >= 2 and kind == "research_supply" and event["tech_id"] in self.tech_ids[1:]:
            if event["remaining_hash"] > 0 and all(b >= event["remaining_hash"] * p
                                                  for b, p in zip(event["buffered_points"], event["item_points"])):
                self.done[[0, 5, 8, 10, 12][self.tech_ids.index(event["tech_id"])]] = 1
        elif kind == "miner_output":
            if (event["item_id"] in (1001, 1002) and event["item_id"] == event["vein_item_id"]
                    and event["count"] > 0 and event["power"] >= 0.1 and event["network_id"] > 0
                    and event["entity_id"] > 0 and event["proto_id"] == 2301):
                self.done[6 if event["item_id"] == 1001 else 7] = 1

    def observe(self):
        if self.active == 16 or self.done[self.active]:
            self.active = next((i for i, deps in enumerate(DEPENDENCIES)
                                if not self.done[i] and all(self.done[d] for d in deps)), 16)
        return self.active, self.done.copy()


def replay_progress(manifest, frames, events):
    version = manifest.get("progress_version")
    require(version is None or type(version) is int and version in (1, 2, 3), "Unknown progress version")
    facts = [e for e in events if e.get("name") in ("progress_fact", "progress_observation")]
    require(version is not None or not facts, "Progress facts lack version")
    tech_ids = manifest.get("progress_tech_ids", [])
    if version:
        require(isinstance(tech_ids, list) and len(tech_ids) == 5
                and all(type(x) is int and 0 < x <= 2147483647 for x in tech_ids)
                and len(set(tech_ids)) == 5, "Invalid progress tech IDs")
    episodes = {e["episode_id"]: e for e in manifest.get("episodes", [])}
    states = {key: Progress(tech_ids, version) for key in episodes}
    boundaries = [e for e in facts if e.get("name") == "progress_observation"]
    if version and not boundaries:
        require(manifest["source_kind"] == "synthetic", "Missing live progress observations")
        boundaries = [dict(name="progress_observation", ticks=f["requested_ticks"],
                           capture_id=f["capture_id"], episode_id=f.get("episode_id")) for f in frames]
        facts += boundaries
    # At equal ticks the observation precedes facts, matching [start, end).
    facts.sort(key=lambda e: (e["ticks"], e["name"] == "progress_fact", e.get("sequence_number", -1)))
    captures = {}
    observed = {key: (0, [0] * 23) for key in states}
    for event in facts:
        key = event.get("episode_id")
        require(key in episodes, "Unknown progress episode")
        if event["name"] == "progress_fact":
            validate_fact(event)
            require(event["kind"] != "line_state" or version == 3, "Line connections require progress version 3")
            require(version >= 2 or event["kind"] in ("lander_work", "lander_removed", "research_queue",
                    "craft_queued", "item_received", "fuel_inserted", "foreign_fuel_produced", "tech_state", "miner_output"),
                    "Production facts require progress version 2")
            episode = episodes[key]
            require(episode["start_ticks"] is not None and event["ticks"] >= episode["start_ticks"]
                    and (episode["end_ticks"] is None or event["ticks"] <= episode["end_ticks"]),
                    "Progress fact outside episode")
            states[key].apply(event)
        else:
            require(type(event.get("capture_id")) is int and event["capture_id"] >= 0, "Invalid progress capture ID")
            previous_task, previous_done = observed[key]
            snapshot = states[key].observe()
            if "task_id" in event or manifest["source_kind"] == "live":
                require(event.get("task_id") == snapshot[0] and event.get("node_completed") == snapshot[1],
                        "Live/offline progress mismatch")
            if "reward" in event or manifest["source_kind"] == "live":
                completed = [int(b > a) for a, b in zip(previous_done, snapshot[1])]
                require(event.get("previous_task_id") == previous_task and event.get("reward_vector") == completed[:16]
                        and event.get("reward") == (completed[previous_task] if previous_task < 16 else 0)
                        and event.get("node_completions") == [i for i, value in enumerate(completed) if value],
                        "Live/offline reward mismatch")
            observed[key] = snapshot
            require(event["capture_id"] not in captures, "Duplicate progress observation")
            captures[event["capture_id"]] = (key, event["ticks"], snapshot)
    snapshots = []
    for frame in frames:
        snapshot = (16, [0] * 23)
        if version:
            require(frame["capture_id"] in captures, "Missing progress observation")
            key, ticks, snapshot = captures[frame["capture_id"]]
            require(key == frame.get("episode_id") and ticks == frame["requested_ticks"], "Progress observation identity mismatch")
        if version and ("task_id" in frame or manifest["source_kind"] == "live"):
            require(frame.get("task_id") == snapshot[0] and frame.get("node_completed") == snapshot[1],
                    "Live/offline progress mismatch")
        snapshots.append(snapshot)
    rows = []
    for index, (first, second) in enumerate(zip(frames, frames[1:])):
        task, before = snapshots[index]
        next_task, after = snapshots[index + 1]
        same = first.get("episode_id") == second.get("episode_id")
        completed = [int(b > a) for a, b in zip(before, after)] if same else [0] * 23
        rows.append(dict(task_id=task, next_task_id=next_task, task_condition=[int(i == task) for i in range(17)],
                         reward_vector=completed[:16], reward=completed[task] if task < 16 else 0,
                         microtask_completed=before[:16], milestone_completed=before[16:],
                         node_completions=[i for i, value in enumerate(completed) if value], progress_available=version in (1, 2, 3)))
    return rows
