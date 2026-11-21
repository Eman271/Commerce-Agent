"""Policy retrieval: pure-python TF-IDF over policy.md sections.

The policy is split by '## ' headings (Phase 2 chunking). A query is scored
against every chunk with cosine similarity. If the best score is below the
gate, the question is treated as outside the policy and the agent must not
invent an answer (Phase 4 hallucination-gate finding).
"""
import math
import re
from collections import Counter
from pathlib import Path

GATE = 0.10

STOP = set("the a an is are do does of to in for on and or hai hain kya ka ki "
           "ke mein me se par pe aur ye yeh wo woh".split())


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


class PolicyRAG:
    def __init__(self, policy_path):
        text = Path(policy_path).read_text(encoding="utf-8-sig")
        self.chunks = []
        for section in re.split(r"\n(?=## )", text):
            section = section.strip()
            if not section:
                continue
            lines = [l for l in section.split("\n") if l.strip()]
            title = lines[0].lstrip("# ").strip() if lines else "Policy"
            self.chunks.append({"title": title, "text": section})
        self.n = len(self.chunks)
        df = Counter()
        self.tfs = []
        for ch in self.chunks:
            tf = Counter(_tokens(ch["text"]))
            self.tfs.append(tf)
            for w in tf:
                df[w] += 1
        self.idf = {w: math.log((self.n + 1) / (c + 1)) + 1 for w, c in df.items()}
        self.norms = []
        for tf in self.tfs:
            self.norms.append(math.sqrt(sum((cnt * self.idf[w]) ** 2
                                            for w, cnt in tf.items())) or 1.0)

    def retrieve(self, query, top_k=3):
        q = Counter(_tokens(query))
        if not q:
            return []
        qvec = {w: cnt * self.idf.get(w, math.log(self.n + 1) + 1)
                for w, cnt in q.items()}
        qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
        scored = []
        for i, tf in enumerate(self.tfs):
            dot = sum(qvec[w] * tf.get(w, 0) * self.idf.get(w, 1)
                      for w in qvec if w in tf)
            scored.append((dot / (qnorm * self.norms[i]), i))
        scored.sort(reverse=True)
        return [{"title": self.chunks[i]["title"], "text": self.chunks[i]["text"],
                 "score": round(s, 4)} for s, i in scored[:top_k] if s > 0]

    def best(self, query):
        r = self.retrieve(query, top_k=1)
        return r[0] if r else {"title": None, "text": "", "score": 0.0}

    def grounded_answer(self, query):
        """Return (answer_text, chunk) or (None, chunk) if below the gate."""
        chunk = self.best(query)
        if chunk["score"] < GATE:
            return None, chunk
        # answer with the chunk's bullet lines that share words with the query
        qwords = set(_tokens(query))
        lines = [l.strip("- ").strip() for l in chunk["text"].split("\n")
                 if l.strip().startswith("-")]
        picked = [l for l in lines if qwords & set(_tokens(l))]
        answer = " ".join(picked[:3]) if picked else " ".join(lines[:2])
        return (answer or chunk["text"][:400]), chunk
