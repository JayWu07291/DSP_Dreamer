"""Conservative material provenance from recorded transfers and machine cycles."""
from .contract import require

# product -> (building, input items, counts, batch size)
RECIPES = {1101: (2302, [1001], [1], 1), 1102: (2302, [1001], [1], 1),
           1104: (2302, [1002], [1], 1), 1202: (2303, [1102, 1104], [2, 1], 2),
           1301: (2303, [1101, 1104], [2, 1], 2), 6001: (2901, [1202, 1301], [1, 1], 1)}


class Production:
    def __init__(self, done):
        self.done = done
        self.machines: dict[str, dict] = {}
        self.stock: dict[tuple[str, int], int] = {}
        self.manual: dict[str, int] = {}
        self.automatic: dict[str, int] = {}

    def apply(self, e):
        kind = e["kind"]
        key = e.get("target", "")
        if kind == "machine_config":
            old = self.machines.get(key)
            recipe = RECIPES.get(e["product"])
            allowed = bool(recipe and (e["proto_id"], e["requires"], e["counts"], e["batch_size"]) == recipe)
            self.machines[key] = dict(product=e["product"], recipe_id=e["recipe_id"], requires=e["requires"],
                                      counts=e["counts"], batch=e["batch_size"], inputs={}, pending=False,
                                      fixed=allowed and (old is None or old["fixed"] and old["recipe_id"] == e["recipe_id"]),
                                      manual_lab=bool(old and old["manual_lab"]), delivered=set(), pending_manual=False)
            self.manual.pop(key, None)
            self.automatic.pop(key, None)
            self.stock = {k: v for k, v in self.stock.items() if k[0] != key}
        elif kind == "flow_reset":
            self.machines.pop(key, None)
            self.manual.pop(key, None)
            self.automatic.pop(key, None)
            self.stock = {k: v for k, v in self.stock.items() if k[0] != key}
        elif kind == "flow_transfer":
            item, count, source = e["item_id"], e["count"], e["source"]
            stock_key = source, item
            trusted = min(self.stock.get(stock_key, 0), e["source_before"])
            moved = max(0, count - max(0, e["source_before"] - trusted))
            # Mixed stacks have no per-item identity. Keep only the provable lower bound.
            self.stock[stock_key] = max(0, trusted - count)
            if item in (1001, 1002) and source.startswith("m:") and key.startswith("s:"):
                moved = 0  # Automatic smelting requires a belt between miner and sorter.
            if key.startswith("m:"):
                machine = self.machines.get(key)
                if machine and item in machine["requires"]:
                    credit = moved if source.startswith("s:") else 0
                    machine["inputs"][item] = machine["inputs"].get(item, 0) + credit
                    if credit:
                        machine["delivered"].add(item)
                    if machine["product"] == 6001 and credit < count:
                        machine["manual_lab"] = True
                    if machine["product"] == 6001 and machine["fixed"] and not machine["manual_lab"] and \
                            machine["delivered"] >= {1202, 1301}:
                        self.done[15] = 1
            else:
                self.stock[key, item] = self.stock.get((key, item), 0) + moved
        elif kind == "miner_stock":
            valid = (e["item_id"] in (1001, 1002) and e["item_id"] == e["vein_item_id"]
                     and e["power"] >= 0.1 and e["network_id"] > 0 and e["proto_id"] == 2301)
            self.stock[key, e["item_id"]] = e["count"] if valid else 0
        elif kind == "machine_manual":
            machine = self.machines.get(key)
            if machine:
                machine["inputs"].clear()
                if machine["product"] == 6001 and e["inserted"]:
                    machine["manual_lab"] = True
        elif kind == "machine_step":
            require(key in self.machines, "Machine step lacks configuration")
            m = self.machines[key]
            require(len(e["before"]) == len(m["requires"]), "Machine input width differs")
            product = m["product"]
            stock_key = key, product
            self.stock[stock_key] = min(self.stock.get(stock_key, 0), e["output_before"])
            if e["cycles"] > 0:
                if m["fixed"] and m["pending_manual"] and product in (1101, 1102, 1104) and not e["auto_input"]:
                    self.manual[key] = product
                    if set(self.manual.values()) >= {1101, 1102, 1104}:
                        self.done[9] = 1
                if m["fixed"] and m["pending"] and not m["manual_lab"]:
                    self.stock[stock_key] += e["cycles"] * m["batch"]
                    if product in (1101, 1102, 1104):
                        self.automatic[key] = product
                        if set(self.automatic.values()) >= {1101, 1102, 1104}:
                            self.done[11] = 1
                    elif product in (1202, 1301):
                        self.done[13 if product == 1202 else 14] = 1
                    elif product == 6001:
                        self.done[22] = 1
                m["pending"] = False
                m["pending_manual"] = False
            # The native update finishes an old batch before consuming the next batch.
            if any(a < b for a, b in zip(e["after"], e["before"])):
                eligible = m["fixed"] and not m["manual_lab"]
                for item, need, before, after in zip(m["requires"], m["counts"], e["before"], e["after"]):
                    credit = min(m["inputs"].get(item, 0), before)
                    eligible &= before - after == need and credit == before
                    m["inputs"][item] = max(0, credit - (before - after))
                m["pending"] = eligible
                m["pending_manual"] = not e["auto_input"]
            else:
                for item, before in zip(m["requires"], e["before"]):
                    m["inputs"][item] = min(m["inputs"].get(item, 0), before)
