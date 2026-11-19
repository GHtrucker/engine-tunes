#!/usr/bin/env python3
# SPDX-License-Identifier: MIT (see LICENSE)
"""compare_outputs.py - where do each arm's answers split from base's? Reads a turing_ab.py results folder.

  python compare_outputs.py                     the newest folder under results\\ next to this script
  python compare_outputs.py <results folder>    a specific run

Prints, per lane and arm, how many answers match base's byte for byte, by request. For every answer that differs it
shows where the split happens (character offset and roughly which output token) and the text on both sides of it.
The same report is written to diff_report.txt in the results folder.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

CONTEXT = 70


def newest(results: Path) -> Path | None:
    runs = [d for d in results.iterdir() if d.is_dir() and (d / "outputs.jsonl").is_file()]
    return max(runs, key=lambda d: d.stat().st_mtime) if runs else None


def flat(s: str) -> str:
    return s.replace("\r", "").replace("\n", " \\n ")


def split_at(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results"
    folder = arg if (arg / "outputs.jsonl").is_file() else (newest(arg) if arg.is_dir() else None)
    if folder is None:
        print(f"no outputs.jsonl under {arg}")
        return 1
    recs = []
    with open(folder / "outputs.jsonl", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                if "content" in r and r.get("status") in ("completed", "truncated"):
                    recs.append(r)
    idx = {(r["lane"], r["round"], r["arm"], r["req"]): r for r in recs}
    arms: list[str] = []
    reqs: list[str] = []
    for r in recs:
        if r["arm"] not in arms:
            arms.append(r["arm"])
        if r["req"] not in reqs:
            reqs.append(r["req"])

    out: list[str] = [f"answers compared with base, from {folder.name}", ""]
    details: list[str] = []
    for lane in ("identity", "speed"):
        bases = {(rnd, req): r for (ln, rnd, a, req), r in idx.items() if ln == lane and a == "base"}
        if not bases:
            continue
        out.append(f"== {lane} lane")
        for arm in arms:
            if arm == "base":
                continue
            per_req: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
            for (rnd, req), b in sorted(bases.items()):
                o = idx.get((lane, rnd, arm, req))
                if o is None:
                    continue
                per_req[req][1] += 1
                if o["content"] == b["content"]:
                    per_req[req][0] += 1
                    continue
                bt, ot = b["content"], o["content"]
                i = split_at(bt, ot)
                toks = (b.get("usage") or {}).get("completion_tokens")
                where = f"~token {round(i / max(len(bt), 1) * toks)} of {toks}" if toks else f"char {i} of {len(bt)}"
                details += [
                    f"-- {lane} r{rnd} {req}, {arm} vs base: split at char {i} ({where})",
                    f"   shared: ...{flat(bt[max(0, i - CONTEXT):i])}",
                    f"   base:   {flat(bt[i:i + CONTEXT])}...",
                    f"   {arm + ':':7s} {flat(ot[i:i + CONTEXT])}...",
                    "",
                ]
            same = sum(v[0] for v in per_req.values())
            total = sum(v[1] for v in per_req.values())
            by_req = ", ".join(f"{q} {per_req[q][0]}/{per_req[q][1]}" for q in reqs if q in per_req)
            out.append(f"  {arm:8s} {same} of {total} identical   ({by_req})")
        out.append("")
    text = "\n".join(out + (["== where the answers split", ""] + details if details else []))
    print(text)
    (folder / "diff_report.txt").write_text(text + "\n", encoding="utf-8")
    print(f"(also written to {folder / 'diff_report.txt'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
