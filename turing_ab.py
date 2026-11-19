#!/usr/bin/env python3
# SPDX-License-Identifier: MIT (see LICENSE)
"""turing_ab.py - A/B Strata's opt-in Turing (sm_75) kernels on one card: are they faster, and are the answers unchanged?

Strata ships a set of Turing kernels that their authors measured on an RTX 2080 Ti and describe as bitwise equal to
the kernels they replace. The maintainers have no sm_75 card, so the set stays off until someone confirms it
(docs/DETAILS.md, "RTX 20 (Turing, sm_75) kernels"; engine/include/strata/core/sm75_series.hpp). This script
measures it on your card and writes the evidence a report needs.

Arms (every arm runs on a freshly started server; the order flips every round):
  base     the config as setup wrote it
  base2    the same again: the noise arm. A "gain" smaller than base vs base2 is noise.
  sm75     STRATA_SM75_PERF=1                         claimed bitwise: answers must equal base's
  sm75_tc  sm75 + STRATA_BF16_TC=1 STRATA_SELECT_SIMT=1  changes rounding: answers may differ, measured for speed

Lanes:
  identity  one start per arm with the expert tier frozen (--adapt-every 0 --pcie-frac 0). Greedy answers are
            compared byte for byte with base's. base2 shows whether this setup is deterministic at all.
  speed     --rounds starts per arm with the config's own settings. Prompt and decode rates are the engine's own
            timings (llama.cpp's `timings` in each answer), never client estimates.

Usage (Windows; any folder outside the Strata checkout):
  C:\\Strata\\terminal\\.venv\\Scripts\\python.exe turing_ab.py --strata C:\\Strata --dry-run
  C:\\Strata\\terminal\\.venv\\Scripts\\python.exe turing_ab.py --strata C:\\Strata
Options: --rounds N (default 5), --arms base base2 sm75, --arm "name:STRATA_X=1,STRATA_Y=0" (repeatable),
         --config FILE, --skip-identity, --skip-speed, --port 8090, --gpu 0, --out DIR.

Standard library only. Nothing in the Strata folder is changed: every config used is a copy in the output folder.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.1"
WIN = os.name == "nt"

BUILTIN_ARMS: dict[str, dict[str, str]] = {
    "base": {},
    "base2": {},
    "sm75": {"STRATA_SM75_PERF": "1"},
    "sm75_tc": {"STRATA_SM75_PERF": "1", "STRATA_BF16_TC": "1", "STRATA_SELECT_SIMT": "1"},
}
# What the identity lane should show against base. Custom arms have no expectation.
EXPECT_SAME = {"base2": True, "sm75": True, "sm75_tc": False}

# Turing switches removed from the config's env and from this process's env, so that "base" really is the default.
SCRUB_EXACT = {
    "STRATA_BF16_TC", "STRATA_SELECT_SIMT", "STRATA_XN_F16", "STRATA_PA_V2T", "STRATA_PF_FUSED", "STRATA_PF_FUSED_SM75",
    "STRATA_GR_UP75", "STRATA_GR_DOWN_TG", "STRATA_SCORES_HALVE", "STRATA_TOPK_SPLIT", "STRATA_TOPK_SAMPLE",
    "STRATA_ATTN_V3", "STRATA_Q2_WARP", "STRATA_FUSE_WAIT", "STRATA_QIL", "STRATA_TC_SM75", "STRATA_PA_V1_PREFETCH",
    "STRATA_SCORES_THREAD", "STRATA_EMULATE_CC",
}
SCRUB_PREFIX = ("STRATA_SM75",)
# Config keys dropped from the copies: a learned expert profile would carry state from one start to the next.
DROP_KEYS = ("expert_profile_save", "expert_profile_save_every")
# What the identity lane switches off. "frozen" holds both moving parts still; the other modes leave one of them on, so a
# difference that appears there points at that part. "none" runs setup's config unchanged.
IDENTITY_MODES = {
    "frozen": (["--adapt-every", "0", "--pcie-frac", "0"], "expert tier frozen, no PCIe-streamed experts"),
    "adapt-off": (["--adapt-every", "0"], "expert tier frozen, PCIe-streamed experts on (setup's share)"),
    "pcie-off": (["--pcie-frac", "0"], "no PCIe-streamed experts, expert tier adaptive"),
    "none": ([], "setup's config unchanged"),
}

CHAT = [
    "Write a Python function that merges two sorted lists into one sorted list, with a docstring and two tests.",
    "Explain in two paragraphs how a refrigerator moves heat from inside to outside.",
    "List ten practical tips for learning a new language as an adult, one sentence each.",
]
IDENTITY_EXTRA = [
    "What is the time complexity of building a binary heap, and why? Answer in three sentences.",
    "Translate 'The server is down and we are investigating' into German, French and Spanish, one line each.",
    "Return only a JSON object with keys project (the string Orion) and build (the integer 17).",
    "A train leaves at 14:35 and arrives at 18:10. How long is the trip? Show the arithmetic.",
    "Write a C function that reverses a null-terminated string in place.",
]
SUSTAINED = ("Write a detailed technical explanation, about 900 words with headings, of how a mixture-of-experts "
             "language model routes each token to a few experts and why that saves compute.")
RECORDS_4K, RECORDS_16K = 211, 858      # the standard protocol's record counts for ~4,096 and ~16,384 prompt tokens

REASON_BITS = {
    0x1: "gpu_idle", 0x2: "app_clocks", 0x4: "sw_power_cap", 0x8: "hw_slowdown", 0x10: "sync_boost",
    0x20: "sw_thermal", 0x40: "hw_thermal", 0x80: "hw_power_brake", 0x100: "display_clocks",
}
BENIGN_REASONS = 0x1 | 0x2 | 0x100      # idle, application clocks, display clocks: not throttling

REQ_FIELDS = ["lane", "round", "arm", "pos", "req", "status", "error", "finish_reason", "prompt_tokens", "cached_tokens",
              "prompt_n", "prompt_ms", "prompt_tps", "predicted_n", "predicted_ms", "decode_tps", "completion_tokens",
              "wall_s", "sha256", "engine_version"]


# ----------------------------------------------------------------------------------------------------------- helpers

def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def say(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: list[str], timeout: float = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def ps_json(command: str):
    """A PowerShell query as parsed JSON (Windows), or None."""
    if not WIN:
        return None
    out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command + " | ConvertTo-Json -Compress"], 60)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def records_prompt(n: int, tag: str) -> str:
    lines = [f"record{i:06d}: alpha beta gamma delta epsilon zeta eta theta." for i in range(1, n + 1)]
    return (f"[{tag}]\n" + "\n".join(lines) +
            "\nSummarize the structure of these records and explain how to look up a record by its ID.")


def num(v):
    if v is None:
        return None
    s = str(v).strip().strip("[]")
    if not s or s.upper() in ("N/A", "NOT SUPPORTED", "UNKNOWN"):
        return None
    try:
        return int(s, 16) if s.lower().startswith("0x") else float(s)
    except ValueError:
        return None


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def fmt(x, nd=1):
    return "-" if x is None else f"{x:,.{nd}f}"


def pct(a, b):
    return None if a is None or b in (None, 0) else (a / b - 1.0) * 100.0


def sanitize(text: str) -> str:
    for p in {str(Path.home()), str(Path.home()).replace("\\", "/")}:
        if p and len(p) > 3:
            text = text.replace(p, "~")
    host = socket.gethostname()
    if host and len(host) > 2:
        text = re.sub(re.escape(host), "<host>", text, flags=re.IGNORECASE)
    return text


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def reasons_text(mask) -> str:
    if mask is None:
        return "-"
    names = [n for b, n in REASON_BITS.items() if int(mask) & b]
    return "+".join(names) if names else "none"


# --------------------------------------------------------------------------------------------------- machine facts

def gpu_facts(gpu: int) -> dict:
    fields = ["name", "driver_version", "vbios_version", "memory.total", "power.limit", "power.max_limit",
              "pcie.link.gen.max", "pcie.link.width.max", "compute_cap", "display_active", "driver_model.current"]
    facts: dict = {}
    for f in fields:          # one at a time: an older driver that lacks one field must not lose the others
        v = run(["nvidia-smi", f"--id={gpu}", f"--query-gpu={f}", "--format=csv,noheader"])
        facts[f] = v if v and "not a valid field" not in v.lower() else None
    apps = run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"])
    facts["compute_apps_before_run"] = [ln.strip() for ln in apps.splitlines() if ln.strip()]
    return facts


def host_facts() -> dict:
    f: dict = {"os": f"{platform.system()} {platform.release()} ({platform.version()})", "python": sys.version.split()[0]}
    if WIN:
        f["cpu"] = ps_json("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,"
                           "MaxClockSpeed")
        f["ram_modules"] = ps_json("Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,BankLabel,"
                                   "Capacity,Speed,ConfiguredClockSpeed,PartNumber")
        f["os_detail"] = ps_json("Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,"
                                 "TotalVisibleMemorySize")
        f["power_plan"] = run(["powercfg", "/getactivescheme"])
        f["disks"] = ps_json("Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size")
    else:
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            m = re.search(r"model name\s*:\s*(.+)", cpuinfo)
            f["cpu"] = {"Name": m.group(1).strip() if m else None, "logical": os.cpu_count(),
                        "avx512f": " avx512f" in cpuinfo}
            m = re.search(r"MemTotal:\s*(\d+)", Path("/proc/meminfo").read_text())
            f["ram_kib"] = int(m.group(1)) if m else None
        except OSError:
            pass
    return f


def strata_facts(root: Path) -> dict:
    f: dict = {"commit": None, "version_line": None}
    if shutil.which("git"):
        f["commit"] = run(["git", "-C", str(root), "rev-parse", "HEAD"]) or None
        f["dirty"] = bool(run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"]))
    if not f["commit"]:
        for c in (root / "COMMIT", root / "terminal" / "COMMIT"):
            if c.is_file():
                f["commit"] = c.read_text(errors="replace").strip()[:64]
                break
    agents = root / "AGENTS.md"
    if agents.is_file():
        for line in agents.read_text(errors="replace").splitlines()[:6]:
            if line.lower().startswith("version"):
                f["version_line"] = line.strip()
                break
    return f


# ------------------------------------------------------------------------------------------------------- telemetry

class Telemetry:
    """One `nvidia-smi -lms 1000` process; each line it prints is tagged with what the run was doing at that moment."""

    FIELDS = ["clocks.sm", "clocks.mem", "power.draw", "temperature.gpu", "utilization.gpu", "memory.used",
              "pcie.link.gen.current", "pcie.link.width.current"]

    def __init__(self, gpu: int, path: Path):
        self.gpu, self.path = gpu, path
        self.label = "idle"
        self.samples: list[dict] = []
        self.proc = None
        self.reason_field = None
        for cand in ("clocks_event_reasons.active", "clocks_throttle_reasons.active"):
            out = run(["nvidia-smi", f"--id={gpu}", f"--query-gpu={cand}", "--format=csv,noheader"])
            if out and "not a valid field" not in out.lower():
                self.reason_field = cand
                break
        self.fields = self.FIELDS + ([self.reason_field] if self.reason_field else [])
        self.lock = threading.Lock()

    def start(self) -> bool:
        if not shutil.which("nvidia-smi"):
            return False
        with open(self.path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(["t_s", "label"] + self.fields)
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(
            ["nvidia-smi", f"--id={self.gpu}", "--query-gpu=" + ",".join(self.fields), "--format=csv,noheader,nounits",
             "-lms", "1000"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace")
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _read(self) -> None:
        with open(self.path, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for line in self.proc.stdout:
                vals = [v.strip() for v in line.strip().split(",")]
                if len(vals) != len(self.fields):
                    continue
                t = round(time.monotonic() - self.t0, 1)
                s = {"t": t, "label": self.label}
                s.update({k: num(v) for k, v in zip(self.fields, vals)})
                with self.lock:
                    self.samples.append(s)
                w.writerow([t, s["label"]] + vals)
                fh.flush()

    def last(self, key: str):
        with self.lock:
            for s in reversed(self.samples):
                if s.get(key) is not None:
                    return s[key]
        return None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def window(self, label: str) -> dict:
        with self.lock:
            ss = [s for s in self.samples if s["label"] == label]
        if not ss:
            return {}
        reason = self.reason_field
        mask = 0
        throttled = 0
        for s in ss:
            r = s.get(reason) if reason else None
            if r is not None:
                mask |= int(r)
                throttled += 1 if int(r) & ~BENIGN_REASONS else 0
        return {"n": len(ss), "sm_mhz": med([s.get("clocks.sm") for s in ss]),
                "power_w": med([s.get("power.draw") for s in ss]),
                "temp_max": max([s.get("temperature.gpu") or 0 for s in ss]) or None,
                "util": med([s.get("utilization.gpu") for s in ss]),
                "pcie": f"gen{fmt(med([s.get('pcie.link.gen.current') for s in ss]), 0)} "
                        f"x{fmt(med([s.get('pcie.link.width.current') for s in ss]), 0)}",
                "reasons": reasons_text(mask) if reason else "-", "throttled_frac": throttled / len(ss)}


# ---------------------------------------------------------------------------------------------------------- server

class ServerDied(RuntimeError):
    pass


class Server:
    def __init__(self, python: str, terminal: Path, port: int, api_key: str | None, out: Path, tel: Telemetry):
        self.python, self.terminal, self.port, self.api_key, self.out, self.tel = python, terminal, port, api_key, out, tel
        self.proc = None
        self.name = ""
        self.engine_version = None

    def start(self, cfg: dict, env: dict[str, str], name: str, ready_timeout: float = 1800) -> float:
        self.name = name
        cfg = json.loads(json.dumps(cfg))
        log_path = self.out / "logs" / f"{name}.log"
        cfg["log"] = str(log_path)
        cfg["port"] = self.port
        cfg["host"] = "127.0.0.1"
        cfg_path = self.out / "configs" / f"{name}.json"
        cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        penv = {k: v for k, v in os.environ.items() if k not in SCRUB_EXACT and not k.startswith(SCRUB_PREFIX)}
        penv.update(env)
        penv["PYTHONIOENCODING"] = "utf-8"
        console = open(self.out / "logs" / f"{name}.console.txt", "w", encoding="utf-8", errors="replace")
        self.tel.label = f"load|{name}"
        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            [self.python, str(self.terminal / "serve" / "server.py"), "--engine", "strata", "--config", str(cfg_path),
             "--port", str(self.port)], cwd=str(self.terminal), env=penv, stdout=console, stderr=subprocess.STDOUT)
        self._console = console
        while time.monotonic() - t0 < ready_timeout:
            if self.proc.poll() is not None:
                raise ServerDied(f"server exited with code {self.proc.returncode} while loading; see logs/{name}.*")
            try:
                with urllib.request.urlopen(self._req("/v1/models"), timeout=5) as r:
                    if r.status == 200:
                        self.chat("Say hi.", 8)          # warm-up, as terminal/tools/ab_engine.py does; not recorded
                        self.engine_version = self._props_version()
                        self.tel.label = "idle"
                        return time.monotonic() - t0
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(3)
        raise ServerDied(f"server not ready after {ready_timeout:.0f} s; see logs/{name}.*")

    def _req(self, path: str, body: dict | None = None) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(body).encode() if body is not None else None
        return urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)

    def _props_version(self):
        try:
            with urllib.request.urlopen(self._req("/props"), timeout=10) as r:
                return json.loads(r.read()).get("build_info")
        except Exception:
            return None

    def chat(self, prompt: str, max_tokens: int) -> tuple[dict, float]:
        body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0,
                "stream": False, "chat_template_kwargs": {"enable_thinking": False}}
        t0 = time.monotonic()
        with urllib.request.urlopen(self._req("/v1/chat/completions", body), timeout=1800) as r:
            data = json.loads(r.read())
        return data, time.monotonic() - t0

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, idle_mem_mib) -> None:
        if self.proc is None:
            return
        self.tel.label = f"stop|{self.name}"
        if self.proc.poll() is None:
            self.proc.terminate()                # Windows: the engine is in a kill-on-close job object (serve/lifeline.py)
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(30)
        self._console.close()
        self.proc = None
        t0 = time.monotonic()                    # wait until the port is closed and the card's memory is back
        while time.monotonic() - t0 < 120:
            mem = self.tel.last("memory.used")
            if not port_in_use(self.port) and (idle_mem_mib is None or mem is None or mem <= idle_mem_mib + 400):
                break
            time.sleep(2)
        time.sleep(3)
        self.tel.label = "idle"


# ------------------------------------------------------------------------------------------------------- log reads

RESIDENT_RE = re.compile(r"(\d[\d,]*) of (\d[\d,]*) experts resident")
SLOTS_RE = re.compile(r"expert cache (\d[\d,]*) slots")
HIT_RE = re.compile(r"expert cache(?: hit rate:)?[^\n]*?(\d+(?:\.\d+)?)\s*%(?:\s*hit)?", re.IGNORECASE)
HIGHLIGHT_RE = re.compile(r"(?i)(sm_?75|turing|bf16_tc|select_simt|sm75|experts resident|expert cache|"
                          r"vram|took effect|warning|error)")


def read_log(path: Path) -> dict:
    if not path.is_file():
        return {"resident": None, "hit_pct": None, "highlights": []}
    text = path.read_text(encoding="utf-8", errors="replace")
    m = SLOTS_RE.search(text) or RESIDENT_RE.search(text)
    hits = [float(x) for x in re.findall(r"expert cache hit rate:\s*(\d+(?:\.\d+)?)%", text)] or \
        [float(x) for x in HIT_RE.findall(text)]
    seen, hl = set(), []
    for line in text.splitlines():
        line = line.strip()
        if HIGHLIGHT_RE.search(line):
            key = re.sub(r"\d+", "#", line)[:120]
            if key not in seen:
                seen.add(key)
                hl.append(line[:300])
        if len(hl) >= 25:
            break
    return {"resident": int(m.group(1).replace(",", "")) if m else None,
            "resident_of": int(m.group(2).replace(",", "")) if m and m.lastindex and m.lastindex >= 2 else None,
            "hit_pct": med(hits), "highlights": hl}


# ---------------------------------------------------------------------------------------------------------- the run

class Run:
    def __init__(self, a, root: Path, terminal: Path, cfg_path: Path):
        self.a, self.root, self.terminal, self.cfg_path = a, root, terminal, cfg_path
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.warnings: list[str] = []
        self.base_cfg = self._clean(raw)
        self.ctx = self._context(self.base_cfg.get("args") or [])
        self.api_key = a.api_key or (raw.get("api_key") if isinstance(raw.get("api_key"), str) else None) or None
        self.arms = self._arms()
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        self.out = Path(a.out) if a.out else Path(__file__).resolve().parent / "results" / f"{stamp}-turing-ab"
        self.rows: list[dict] = []
        self.loads: dict[str, dict] = {}

    # -- setup
    def _clean(self, raw: dict) -> dict:
        cfg = json.loads(json.dumps(raw))
        for k in DROP_KEYS:
            if k in cfg:
                cfg.pop(k)
                self.warnings.append(f"dropped `{k}` from the copies (a learned expert profile carries state between starts)")
        env = dict(cfg.get("env") or {})
        for k in list(env):
            if k in SCRUB_EXACT or k.startswith(SCRUB_PREFIX):
                self.warnings.append(f"removed `{k}={env[k]}` from the config's env for every arm (arms set it themselves)")
                env.pop(k)
        cfg["env"] = env
        for k in os.environ:
            if k in SCRUB_EXACT or k.startswith(SCRUB_PREFIX):
                self.warnings.append(f"`{k}` is set in this shell; it is ignored (arms set their own)")
            elif k.startswith("STRATA_"):
                self.warnings.append(f"`{k}={os.environ[k]}` is set in this shell and applies to every arm")
        return cfg

    @staticmethod
    def _context(args: list) -> int | None:
        args = [str(x) for x in args]
        for i, x in enumerate(args):
            for flag in ("--max-context", "--context", "--ctx-size", "-c"):
                if x == flag and i + 1 < len(args):
                    return int(num(args[i + 1]) or 0) or None
                if x.startswith(flag + "="):
                    return int(num(x.split("=", 1)[1]) or 0) or None
        return None

    def _arms(self) -> dict[str, dict[str, str]]:
        names = []
        for item in self.a.arms:
            names += [n for n in item.split(",") if n]
        arms: dict[str, dict[str, str]] = {}
        for n in names:
            if n not in BUILTIN_ARMS:
                sys.exit(f"unknown arm {n!r}; built-in arms: {', '.join(BUILTIN_ARMS)} (or add one with --arm)")
            arms[n] = dict(BUILTIN_ARMS[n])
        for spec in self.a.arm or []:
            name, _, kv = spec.partition(":")
            env = dict(x.split("=", 1) for x in kv.split(",") if "=" in x)
            arms[name] = env
        if "base" not in arms:
            sys.exit("the arms must include base: every comparison is against it")
        return arms

    def requests(self, lane: str, rnd: int) -> list[tuple[str, str, int]]:
        if lane == "identity":
            reqs = [(f"id{i + 1}", p, 256) for i, p in enumerate(CHAT + IDENTITY_EXTRA)]
            return reqs + [("doc4k", records_prompt(RECORDS_4K, "identity"), 128)]
        tag = f"run r{rnd}"
        reqs = [(f"chat{i + 1}", f"[{tag}] {p}", 256) for i, p in enumerate(CHAT)]
        reqs.append(("doc4k", records_prompt(RECORDS_4K, tag), 128))
        if self.ctx is None or self.ctx >= 20000:
            reqs.append(("doc16k", records_prompt(RECORDS_16K, tag), 128))
        reqs.append(("sustained", f"[{tag}] {SUSTAINED}", 1024))
        return reqs

    def schedule(self) -> list[tuple[str, int, str]]:
        names = list(self.arms)
        plan = []
        if not self.a.skip_identity and self.a.identity_rounds == 1:
            # base first, base2 last: base2 then tests a restart after the other arms ran
            order = ["base"] + [n for n in names if n not in ("base", "base2")] + (["base2"] if "base2" in names else [])
            plan += [("identity", 0, n) for n in order]
        elif not self.a.skip_identity:
            for r in range(1, self.a.identity_rounds + 1):
                order = names if r % 2 == 1 else names[::-1]
                plan += [("identity", r, n) for n in order]
        if not self.a.skip_speed:
            for r in range(1, self.a.rounds + 1):
                order = names if r % 2 == 1 else names[::-1]
                plan += [("speed", r, n) for n in order]
        return plan

    # -- execution
    def write_row(self, row: dict, out_record: dict) -> None:
        self.rows.append(row)
        path = self.out / "requests.csv"
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=REQ_FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
        with open(self.out / "outputs.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(out_record, ensure_ascii=False) + "\n")

    def do_start(self, srv: Server, tel: Telemetry, lane: str, rnd: int, arm: str, idle_mem) -> None:
        name = f"{lane}-r{rnd}-{arm}"
        cfg = json.loads(json.dumps(self.base_cfg))
        env = dict(self.arms[arm])
        cfg["env"] = {**cfg.get("env", {}), **env}
        if lane == "identity":
            cfg["args"] = [str(x) for x in (cfg.get("args") or [])] + IDENTITY_MODES[self.a.identity_mode][0]
        reqs = self.requests(lane, rnd)
        say(f"{name}: starting server ({', '.join(f'{k}={v}' for k, v in env.items()) or 'no switches'})")
        try:
            load_s = srv.start(cfg, env, name)
        except ServerDied as e:
            say(f"{name}: FAILED to start: {e}")
            srv.stop(idle_mem)
            for pos, (req, _, _) in enumerate(reqs):
                self.write_row({"lane": lane, "round": rnd, "arm": arm, "pos": pos, "req": req, "status": "skipped",
                                "error": f"server did not start: {e}"}, {"lane": lane, "round": rnd, "arm": arm,
                                                                          "req": req, "status": "skipped"})
            self.loads[name] = {"load_s": None, **read_log(self.out / "logs" / f"{name}.log")}
            return
        say(f"{name}: ready in {load_s:.0f} s (engine {srv.engine_version or 'version unknown'})")
        try:
            for pos, (req, prompt, cap) in enumerate(reqs):
                label = f"{lane}|{arm}|{rnd}|{req}"
                tel.label = label
                row = {"lane": lane, "round": rnd, "arm": arm, "pos": pos, "req": req, "engine_version": srv.engine_version}
                rec = {"lane": lane, "round": rnd, "arm": arm, "req": req, "max_tokens": cap, "prompt_head": prompt[:120]}
                if not srv.alive():
                    row.update(status="skipped", error="server died earlier in this start")
                    self.write_row(row, {**rec, "status": "skipped"})
                    continue
                try:
                    data, wall = srv.chat(prompt, cap)
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", "replace")[:500] if e.fp else ""
                    row.update(status="failed", error=f"HTTP {e.code}: {body}")
                    self.write_row(row, {**rec, "status": "failed", "error": row["error"]})
                    say(f"  {req:9s} FAILED: {row['error'][:160]}")
                    continue
                except Exception as e:  # noqa: BLE001 - every failure is recorded, none is retried
                    row.update(status="failed", error=f"{type(e).__name__}: {e}")
                    self.write_row(row, {**rec, "status": "failed", "error": row["error"]})
                    say(f"  {req:9s} FAILED: {row['error'][:160]}")
                    continue
                finally:
                    tel.label = "idle"
                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                usage = data.get("usage") or {}
                t = data.get("timings") or {}
                cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", t.get("cache_n"))
                row.update(status="completed" if choice.get("finish_reason") == "stop" else
                           ("truncated" if choice.get("finish_reason") == "length" else "completed"),
                           finish_reason=choice.get("finish_reason"), prompt_tokens=usage.get("prompt_tokens"),
                           cached_tokens=cached, prompt_n=t.get("prompt_n"), prompt_ms=t.get("prompt_ms"),
                           prompt_tps=t.get("prompt_per_second"), predicted_n=t.get("predicted_n"),
                           predicted_ms=t.get("predicted_ms"), decode_tps=t.get("predicted_per_second"),
                           completion_tokens=usage.get("completion_tokens"), wall_s=round(wall, 3),
                           sha256=hashlib.sha256((reasoning + "\x00" + content).encode("utf-8")).hexdigest())
                rec.update(status=row["status"], finish_reason=row["finish_reason"], content=content,
                           reasoning_content=reasoning or None, usage=usage, timings=t, wall_s=row["wall_s"],
                           sha256=row["sha256"], telemetry=tel.window(label))
                self.write_row(row, rec)
                say(f"  {req:9s} prompt {fmt(num(row['prompt_tps']))} tok/s ({row['prompt_n']} read, "
                    f"{cached} cached)  decode {fmt(num(row['decode_tps']))} tok/s ({row['predicted_n']} tok)  "
                    f"{row['wall_s']:.1f} s")
        finally:
            srv.stop(idle_mem)
            self.loads[name] = {"load_s": round(load_s, 1), **read_log(self.out / "logs" / f"{name}.log")}

    def go(self) -> int:
        a = self.a
        for d in ("logs", "configs"):
            (self.out / d).mkdir(parents=True, exist_ok=True)
        python = a.python or self.default_python()
        plan = self.schedule()
        gpu = gpu_facts(a.gpu) if shutil.which("nvidia-smi") else {}
        cc = (gpu.get("compute_cap") or "").strip()
        if cc and cc != "7.5":
            self.warnings.append(f"GPU {a.gpu} reports compute capability {cc}, not 7.5: the sm75 switches change nothing "
                                 f"on it, so sm75 vs base measures noise only")
        if not shutil.which("nvidia-smi"):
            self.warnings.append("nvidia-smi was not found: no telemetry or GPU facts")
        if gpu.get("compute_apps_before_run"):
            self.warnings.append("other programs were using the GPU at the start: " + "; ".join(gpu["compute_apps_before_run"]))
        if (gpu.get("display_active") or "").lower() == "enabled":
            self.warnings.append("this card drives a display: desktop activity during the run adds noise")
        machine = {"tool": f"turing_ab.py {VERSION}", "started_utc": now_utc(), "gpu_index": a.gpu, "gpu": gpu,
                   "host": host_facts(), "strata": strata_facts(self.root), "config_file": self.cfg_path.name,
                   "config_args": self.base_cfg.get("args"), "config_env": self.base_cfg.get("env"),
                   "context_tokens": self.ctx, "arms": self.arms, "rounds": a.rounds, "python_for_server": python,
                   "identity_mode": a.identity_mode, "identity_args": IDENTITY_MODES[a.identity_mode][0],
                   "identity_rounds": a.identity_rounds,
                   "warnings": self.warnings}
        (self.out / "machine.json").write_text(sanitize(json.dumps(machine, indent=1, ensure_ascii=False)), encoding="utf-8")

        say(f"turing_ab {VERSION}: {len(plan)} server starts planned; results in {self.out}")
        say(f"GPU {a.gpu}: {gpu.get('name') or '?'} (compute {cc or '?'}), driver {gpu.get('driver_version') or '?'}; "
            f"config {self.cfg_path.name}, context {self.ctx or 'unknown'}")
        say("arms: " + "; ".join(f"{k}={' '.join(f'{x}={y}' for x, y in v.items()) or '(defaults)'}"
                                 for k, v in self.arms.items()))
        for w in self.warnings:
            say("note: " + w)
        if a.dry_run:
            for lane, rnd, arm in plan:
                print(f"  {lane:8s} round {rnd}  {arm:8s}  {len(self.requests(lane, rnd))} requests")
            say("dry run: nothing was started")
            return 0
        if port_in_use(a.port):
            say(f"port {a.port} is already in use: stop whatever runs there (or pass --port) and try again")
            return 2

        tel = Telemetry(a.gpu, self.out / "telemetry.csv")
        tel_on = tel.start()
        time.sleep(6 if tel_on else 0)
        idle_mem = tel.last("memory.used") if tel_on else None
        srv = Server(python, self.terminal, a.port, self.api_key, self.out, tel)
        t_start = time.monotonic()
        rc = 0
        try:
            for i, (lane, rnd, arm) in enumerate(plan):
                self.do_start(srv, tel, lane, rnd, arm, idle_mem)
                done = i + 1
                if done < len(plan):
                    per = (time.monotonic() - t_start) / done
                    say(f"{done}/{len(plan)} starts done; about {per * (len(plan) - done) / 60:.0f} min left")
        except KeyboardInterrupt:
            say("interrupted: stopping the server and writing what was measured")
            rc = 130
        finally:
            srv.stop(idle_mem)
            tel.stop()
            self.summarize(tel, time.monotonic() - t_start, interrupted=rc != 0)
        say(f"done. Open {self.out / 'summary.md'}")
        return rc

    def default_python(self) -> str:
        cand = self.terminal / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
        return str(cand) if cand.is_file() else sys.executable

    # -- analysis
    def summarize(self, tel: Telemetry, elapsed: float, interrupted: bool) -> None:
        rows = self.rows
        arms = list(self.arms)
        L: list[str] = []
        m = json.loads((self.out / "machine.json").read_text(encoding="utf-8"))
        g, h, s = m.get("gpu", {}), m.get("host", {}), m.get("strata", {})
        cpu = h.get("cpu") or {}
        if isinstance(cpu, list):
            cpu = cpu[0] if cpu else {}
        ram = h.get("ram_modules")
        ram_txt = "-"
        if isinstance(ram, dict):
            ram = [ram]
        if isinstance(ram, list) and ram:
            total = sum(int(x.get("Capacity") or 0) for x in ram) / 2 ** 30
            speeds = sorted({str(x.get("ConfiguredClockSpeed") or x.get("Speed")) for x in ram})
            ram_txt = f"{total:.0f} GiB in {len(ram)} modules ({', '.join(x.get('DeviceLocator') or '?' for x in ram)}), " \
                      f"running at {'/'.join(speeds)} MT/s"
        elif h.get("ram_kib"):
            ram_txt = f"{h['ram_kib'] / 2 ** 20:.0f} GiB"

        L.append(f"# Turing A/B on {g.get('name') or 'this GPU'}")
        L.append("")
        tool = m.get("tool") or f"turing_ab.py {VERSION}"
        rewritten = "" if tool.endswith(VERSION) else f" (this summary rewritten by turing_ab.py {VERSION})"
        L.append(f"{tool}, started {m.get('started_utc')}, {elapsed / 60:.0f} min{rewritten}"
                 + (" — **interrupted, partial results**" if interrupted else ""))
        L.append("")
        L.append("## Machine")
        L.append("")
        L.append("| | |")
        L.append("| --- | --- |")
        L.append(f"| GPU | {g.get('name')}, {g.get('memory.total')}, compute {g.get('compute_cap')}, power limit "
                 f"{g.get('power.limit')} (max {g.get('power.max_limit')}), PCIe gen{g.get('pcie.link.gen.max')} "
                 f"x{g.get('pcie.link.width.max')} max, driver model {g.get('driver_model.current') or '-'}, "
                 f"display {g.get('display_active') or '-'} |")
        L.append(f"| Driver | {g.get('driver_version')}, VBIOS {g.get('vbios_version')} |")
        L.append(f"| CPU | {cpu.get('Name') if isinstance(cpu, dict) else cpu} "
                 f"({cpu.get('NumberOfCores', '?') if isinstance(cpu, dict) else '?'} cores) |")
        L.append(f"| RAM | {ram_txt} |")
        L.append(f"| OS | {h.get('os')} |")
        if h.get("power_plan"):
            L.append(f"| Power plan | {h.get('power_plan')} |")
        L.append(f"| Strata | {s.get('version_line') or '-'}, commit `{(s.get('commit') or 'unknown')[:12]}`"
                 f"{' (local changes)' if s.get('dirty') else ''} |")
        L.append(f"| Config | `{m.get('config_file')}`, context {m.get('context_tokens') or 'unknown'} |")
        L.append("")
        L.append("```text")
        L.append(sanitize(" ".join(str(x) for x in (m.get("config_args") or []))))
        L.append("```")
        if m.get("warnings"):
            L.append("")
            L.append("Notes: " + " ".join(f"({i + 1}) {w}." for i, w in enumerate(m["warnings"])))

        # identity
        idr = [r for r in rows if r["lane"] == "identity"]
        verdicts = {}
        if idr:
            mode = self.a.identity_mode
            nr = self.a.identity_rounds
            L += ["", f"## Identity lane ({IDENTITY_MODES[mode][1]}: `{' '.join(IDENTITY_MODES[mode][0]) or 'no extra flags'}`; "
                      f"greedy, byte-for-byte against base{f', paired by round, {nr} rounds' if nr > 1 else ''})", ""]
            key = (lambda r: f"r{r['round']} {r['req']}") if nr > 1 else (lambda r: r["req"])
            base = {key(r): r.get("sha256") for r in idr if r["arm"] == "base" and r.get("sha256")}
            L.append("| Arm | Identical to base | Differs on | Expected |")
            L.append("| --- | --- | --- | --- |")
            for arm in arms:
                if arm == "base":
                    continue
                mine = {key(r): r.get("sha256") for r in idr if r["arm"] == arm and r.get("sha256")}
                common = [k for k in base if k in mine]
                same = [k for k in common if base[k] == mine[k]]
                diff = [k for k in common if base[k] != mine[k]]
                exp = EXPECT_SAME.get(arm)
                verdicts[arm] = (len(same), len(common), diff)
                L.append(f"| {arm} | {f'{len(same)} of {len(common)}' if common else 'not measured'} | {', '.join(diff) or '-'} | "
                         f"{'identical' if exp else ('may differ' if exp is False else '-')} |")
            b2 = verdicts.get("base2")
            L.append("")
            if b2 and b2[1] and b2[0] < b2[1]:
                L.append("**base2 differs from base: this setup is not deterministic across restarts in this mode, so the "
                         "other identity results cannot be read as kernel differences.**")
            elif b2 and b2[1]:
                L.append("base2 equals base: the setup is deterministic across restarts, so a difference in another arm "
                         "comes from its switches.")
            s75 = verdicts.get("sm75")
            if s75 and s75[1] and (not b2 or b2[0] == b2[1]):
                if s75[0] == s75[1]:
                    L.append(f"**sm75 equals base on every request in this mode ({mode}): no answer changed on this card "
                             f"for these prompts.**")
                else:
                    L.append(f"**sm75 changed {len(s75[2])} answer(s) while base2 changed none: in this mode the series "
                             f"is not bitwise. Run compare_outputs.py to see where the answers split.**")

        # speed
        sp = [r for r in rows if r["lane"] == "speed" and r.get("status") in ("completed", "truncated")]
        speed_identity = ""
        if sp:
            sbase = {(r["round"], r["req"]): r.get("sha256") for r in sp if r["arm"] == "base" and r.get("sha256")}
            parts = []
            for arm in arms:
                if arm == "base":
                    continue
                mine = {(r["round"], r["req"]): r.get("sha256") for r in sp if r["arm"] == arm and r.get("sha256")}
                common = [k for k in sbase if k in mine]
                if common:
                    parts.append(f"{arm} {sum(1 for k in common if sbase[k] == mine[k])} of {len(common)}")
            if parts:
                speed_identity = ("Answers in the speed lane identical to base's, paired by round (setup's config, so the "
                                  "expert tier and the PCIe share move): " + ", ".join(parts) + ".")
        if sp:
            reqs = []
            for r in sp:
                if r["req"] not in reqs:
                    reqs.append(r["req"])
            by = {}
            for r in sp:
                by.setdefault((r["arm"], r["req"]), {})[r["round"]] = r
            L += ["", f"## Speed lane ({self.a.rounds} rounds, fresh server per arm per round, arm order flipped "
                      f"each round)", "",
                  "Engine-reported rates. Decode for the chats and the long answer, prompt reading for the documents. "
                  "Each cell: the arm's median rate (min-max, n), then the median of its per-round paired changes "
                  "against base (same round, same prompt); **wins** counts the rounds in which the arm beat base.", ""]
            L.append("| Request | Metric | " + " | ".join(arms) + " |")
            L.append("| --- | --- | " + " | ".join("---" for _ in arms) + " |")
            noise = {}
            for req in reqs:
                metric = "prompt_tps" if req.startswith("doc") else "decode_tps"
                cells = []
                bvals = by.get(("base", req), {})
                bmed = med([num(x.get(metric)) for x in bvals.values()])
                for arm in arms:
                    vals = by.get((arm, req), {})
                    xs = [num(x.get(metric)) for x in vals.values() if num(x.get(metric)) is not None]
                    if not xs:
                        cells.append("-")
                        continue
                    mm = med(xs)
                    cell = f"{fmt(mm)} ({fmt(min(xs))}-{fmt(max(xs))}, {len(xs)})"
                    if arm != "base" and bmed:
                        paired = [(num(vals[k].get(metric)), num(bvals[k].get(metric))) for k in vals if k in bvals]
                        paired = [(x, y) for x, y in paired if x is not None and y]
                        if paired:
                            ch = med([pct(x, y) for x, y in paired])
                            wins = sum(1 for x, y in paired if x > y)
                            cell += f" {ch:+.1f}% paired, wins {wins}/{len(paired)}"
                            if arm == "base2":
                                noise[req] = abs(ch)
                    cells.append(cell)
                L.append(f"| {req} | {'prompt' if metric == 'prompt_tps' else 'decode'} tok/s | " + " | ".join(cells) + " |")
            if speed_identity:
                L += ["", speed_identity]
            if noise:
                L.append("")
                L.append("Noise (base2 against base): " + ", ".join(f"{k} ±{v:.1f}%" for k, v in noise.items()) +
                         ". A change inside that band, or one that does not win most rounds, is not evidence.")
            # cached-token check
            reused = [r for r in sp if (num(r.get("cached_tokens")) or 0) > 64]
            if reused:
                L.append("")
                L.append(f"**{len(reused)} request(s) reported more than 64 cached prompt tokens on a fresh server; "
                         f"their prompt rates are not fresh reads:** " +
                         ", ".join(f"{r['arm']}/{r['req']}/r{r['round']}" for r in reused[:10]))

        # failures
        bad = [r for r in rows if r.get("status") in ("failed", "skipped")]
        if bad:
            L += ["", "## Failures and skipped requests", ""]
            groups: dict[tuple, list[str]] = {}
            for r in bad:
                key = (r["lane"], r["round"], r["arm"], r["status"], sanitize(str(r.get("error")))[:200])
                groups.setdefault(key, []).append(r["req"])
            for (lane, rnd, arm, status, err), reqs_ in list(groups.items())[:40]:
                L.append(f"- {lane} r{rnd} {arm}: {len(reqs_)} {status} ({', '.join(reqs_)}) — {err}")

        # telemetry and engine log
        if tel.samples or self.loads:
            L += ["", "## Card and engine per arm (speed lane)", "",
                  "| Arm | SM clock MHz | Power W | Max temp C | GPU util % | PCIe | Clock limits seen | "
                  "Expert slots | Cache hit % | Load s |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
            for arm in arms:
                ws = []
                for r in sp:
                    if r["arm"] == arm:
                        w = tel.window(f"speed|{arm}|{r['round']}|{r['req']}")
                        if w:
                            ws.append(w)
                mask_names = sorted({n for w in ws for n in str(w.get("reasons", "")).split("+")
                                     if n and n not in ("-", "none", "gpu_idle", "app_clocks", "display_clocks")})
                lo = [v for k, v in self.loads.items() if k.startswith("speed-") and k.endswith(f"-{arm}")]
                res = sorted({x["resident"] for x in lo if x.get("resident") is not None})
                L.append(f"| {arm} | {fmt(med([w.get('sm_mhz') for w in ws]), 0)} | {fmt(med([w.get('power_w') for w in ws]))}"
                         f" | {fmt(max([w.get('temp_max') or 0 for w in ws] or [0]) or None, 0)} | "
                         f"{fmt(med([w.get('util') for w in ws]), 0)} | {ws[0].get('pcie') if ws else '-'} | "
                         f"{', '.join(mask_names) or 'none'} | {', '.join(f'{x:,}' for x in res) or '-'} | "
                         f"{fmt(med([x.get('hit_pct') for x in lo]))} | {fmt(med([x.get('load_s') for x in lo]), 0)} |")
            res_all = {x["resident"] for k, x in self.loads.items() if k.startswith("speed-") and x.get("resident")}
            if len(res_all) > 1:
                L.append("")
                L.append("Expert slots differ between starts. A switch that changes VRAM use changes how many experts sit "
                         "on the card, which moves speed on its own; read the speed lane with that in mind.")
            hl = []
            for k, v in self.loads.items():
                if v.get("highlights"):
                    hl.append(f"{k}:")
                    hl += [f"  {sanitize(x)}" for x in v["highlights"][:12]]
                    break                                    # one start's lines are enough as a sample
            if hl:
                L += ["", "<details><summary>Engine log lines from the first start (all logs are in logs/)</summary>", "",
                      "```text", *hl, "```", "", "</details>"]

        L += ["", "## Files", "",
              "- `requests.csv`: one row per request (engine timings, token counts, wall time, answer hash)",
              "- `outputs.jsonl`: every answer in full with its usage, timings and the card's telemetry for that request",
              "- `telemetry.csv`: nvidia-smi once a second, tagged with what was running",
              "- `machine.json`, `configs/`, `logs/`: the setup, the exact configs, and the engine and server logs",
              "", "Logs and configs are not scrubbed. Read them before you post them anywhere.", ""]
        (self.out / "summary.md").write_text(sanitize("\n".join(L)), encoding="utf-8")
        summary_json = {"rows": rows, "loads": self.loads, "identity": {k: {"same": v[0], "total": v[1], "differs": v[2]}
                                                                         for k, v in (verdicts or {}).items()}}
        (self.out / "summary.json").write_text(sanitize(json.dumps(summary_json, indent=1, default=str)), encoding="utf-8")


def resummarize(folder: Path) -> int:
    """Write summary.md again from a results folder's own files (requests.csv, telemetry.csv, logs, machine.json)."""
    m = json.loads((folder / "machine.json").read_text(encoding="utf-8"))
    run = Run.__new__(Run)
    run.a = argparse.Namespace(rounds=m.get("rounds", 5), identity_mode=m.get("identity_mode", "frozen"),
                               identity_rounds=m.get("identity_rounds", 1))
    run.out, run.arms = folder, m.get("arms") or dict(BUILTIN_ARMS)
    with open(folder / "requests.csv", encoding="utf-8", newline="") as fh:
        run.rows = list(csv.DictReader(fh))
    run.loads = {p.stem: {"load_s": None, **read_log(p)} for p in sorted((folder / "logs").glob("*.log"))}
    tel = Telemetry.__new__(Telemetry)
    tel.lock, tel.samples, tel.reason_field = threading.Lock(), [], None
    elapsed = 0.0
    tpath = folder / "telemetry.csv"
    if tpath.is_file():
        with open(tpath, encoding="utf-8", newline="") as fh:
            rd = csv.reader(fh)
            head = next(rd, [])
            tel.reason_field = next((f for f in head if "reasons" in f), None)
            for row in rd:
                if len(row) != len(head):
                    continue
                smp = {"t": num(row[0]) or 0.0, "label": row[1]}
                smp.update({k: num(v) for k, v in zip(head[2:], row[2:])})
                tel.samples.append(smp)
        elapsed = max((x["t"] for x in tel.samples), default=0.0)
    run.summarize(tel, elapsed, interrupted=False)
    print(f"rewrote {folder / 'summary.md'}")
    return 0


def main() -> int:
    if "--resummarize" in sys.argv:
        i = sys.argv.index("--resummarize")
        if i + 1 >= len(sys.argv):
            sys.exit("--resummarize needs a results folder")
        return resummarize(Path(sys.argv[i + 1]).expanduser().resolve())
    ap = argparse.ArgumentParser(description="A/B Strata's opt-in Turing kernels on one card. "
                                 "--resummarize <results folder> rewrites a run's summary.md from its files.")
    ap.add_argument("--strata", required=True, help="the Strata source folder (the one with START-HERE.bat)")
    ap.add_argument("--config", help="model config (default: the newest terminal/strata-*.json)")
    ap.add_argument("--rounds", type=int, default=5, help="speed rounds per arm (default 5)")
    ap.add_argument("--arms", nargs="+", default=["base,base2,sm75,sm75_tc"],
                    help="built-in arms to run: base base2 sm75 sm75_tc (default all four)")
    ap.add_argument("--arm", action="append", help='extra arm, "name:STRATA_X=1,STRATA_Y=0" (repeatable)')
    ap.add_argument("--skip-identity", action="store_true")
    ap.add_argument("--identity-mode", choices=list(IDENTITY_MODES), default="frozen",
                    help="what the identity lane switches off: frozen (the expert tier and PCIe-streamed experts, the "
                         "default), adapt-off (only the tier), pcie-off (only the streaming), none (setup's config)")
    ap.add_argument("--identity-rounds", type=int, default=1,
                    help="identity rounds per arm (default 1); with more, the arm order flips every round")
    ap.add_argument("--skip-speed", action="store_true")
    ap.add_argument("--port", type=int, default=8090, help="port for the test server (default 8090)")
    ap.add_argument("--gpu", type=int, default=0, help="nvidia-smi index of the card to watch (default 0)")
    ap.add_argument("--python", help="Python that runs Strata's server (default: Strata's terminal/.venv)")
    ap.add_argument("--api-key", help="only if the config's server needs a key it does not carry itself")
    ap.add_argument("--out", help="results folder (default: results/<UTC time>-turing-ab next to this script)")
    ap.add_argument("--dry-run", action="store_true", help="check the setup and print the plan; start nothing")
    a = ap.parse_args()

    root = Path(a.strata).expanduser().resolve()
    terminal = root / "terminal"
    if not (terminal / "serve" / "server.py").is_file():
        sys.exit(f"{root} does not look like a Strata source folder (no terminal/serve/server.py)")
    here = Path(__file__).resolve()
    if root in here.parents:
        print("note: this script sits inside the Strata folder; results written here make the checkout dirty", flush=True)
    if a.config:
        cfg_path = Path(a.config).expanduser()
        if not cfg_path.is_absolute() and not cfg_path.exists():
            cfg_path = terminal / cfg_path
    else:
        found = sorted(terminal.glob("strata-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not found:
            sys.exit(f"no strata-*.json in {terminal}: run START-HERE.bat first, or pass --config")
        cfg_path = found[0]
    if not cfg_path.is_file():
        sys.exit(f"config not found: {cfg_path}")
    if a.rounds < 1 or a.identity_rounds < 1:
        sys.exit("--rounds and --identity-rounds must be at least 1")
    return Run(a, root, terminal, cfg_path.resolve()).go()


if __name__ == "__main__":
    sys.exit(main())
