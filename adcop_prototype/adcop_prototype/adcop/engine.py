"""Diagnostic engine: exact-in-the-limit Bayesian inference over mastery states
consistent with the prerequisite DAG, via weighted Monte Carlo particles.
Each particle = one full mastery vector sampled from the structural prior
(a child is likely mastered only if all its parents are). Responses reweight
particles by slip/guess likelihood, so evidence flows up AND down the graph
with no hand-tuned propagation constants."""
import json
from pathlib import Path
import numpy as np
D = Path(__file__).parent

class Graph:
    def __init__(self, path=D/"graph.json"):
        nodes = json.load(open(path))["nodes"]   # must be topologically ordered
        self.nodes = {n["id"]: n for n in nodes}
        self.ids = [n["id"] for n in nodes]
        self.idx = {k: i for i, k in enumerate(self.ids)}
        self.parents = {k: self.nodes[k]["parents"] for k in self.ids}
        for k in self.ids:
            assert all(self.idx[p] < self.idx[k] for p in self.parents[k]), f"order: {k}"

def load_items(path=D/"items.json"):
    return {i["id"]: i for i in json.load(open(path))["items"]}

class Engine:
    # p_root: P(master a root skill); p_ok: P(master | all parents mastered); p_leak: P(master | a parent missing)
    def __init__(self, graph, items, n=20000, p_root=0.6, p_ok=0.85, p_leak=0.10, seed=0):
        self.g, self.items = graph, items
        rng = np.random.default_rng(seed)
        self.M = np.zeros((n, len(graph.ids)), bool)
        for i, k in enumerate(graph.ids):
            ps = [graph.idx[p] for p in graph.parents[k]]
            p = np.where(self.M[:, ps].all(1), p_ok, p_leak) if ps else p_root
            self.M[:, i] = rng.random(n) < p

    def loglik(self, item_id, correct):
        it = self.items[item_id]; m = self.M[:, self.g.idx[it["node"]]]
        s, g = it["slip"], it["guess"]
        return np.log(np.where(m, 1 - s if correct else s, g if correct else 1 - g))

    def marginals(self, logw):
        w = np.exp(logw - logw.max()); w /= w.sum()
        return w @ self.M                       # P(mastered) per node

    def posterior(self, responses):             # responses: [(item_id, correct)]
        lw = np.zeros(len(self.M))
        for iid, ok in responses: lw += self.loglik(iid, ok)
        return lw

    def next_item(self, marg, asked):
        """Ask about the node we are least sure of (max p(1-p))."""
        cands = [i for i in self.items.values() if i["id"] not in asked]
        if not cands: return None
        return max(cands, key=lambda i: marg[self.g.idx[i["node"]]] * (1 - marg[self.g.idx[i["node"]]]))["id"]

    def root_causes(self, marg, lo=0.4):
        """Unmastered nodes none of whose prerequisites are also unmastered (the 'frontier')."""
        un = {k for k in self.g.ids if marg[self.g.idx[k]] < lo}
        out = [k for k in un if not any(p in un for p in self.g.parents[k])]
        return sorted(out, key=lambda k: marg[self.g.idx[k]])
