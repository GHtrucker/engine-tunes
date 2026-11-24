# 2x RTX 5060 Ti 16 GB, Windows, ready-made package: Q2_0 on a layer split against one card, engine 0.1.65

**Result in one line:** on the standard benchmark, two cards read prompts about 2.1x as fast as one card and decoded about 1.5x to 1.8x as fast; the tuner, a display change and the all-cards split engine changed nothing measurable.

Six runs of `strata bench run` on 2026-11-23, all of them published here: five on both cards and one on a single card. Every run finished 21 of 21 required requests and passed 12 of 12 sanity checks. Nothing was left out, including the runs that turned out to measure the same configuration again.

This folder also records a setup problem met on the way (the default launch of Q2_0 did not start on this PC) and the launch line that worked. See "Setup problem" below.

## Environment

- Two NVIDIA GeForce RTX 5060 Ti 16 GB (16,311 MiB each), driver 621.24, WDDM, power limit 180 W each (the default).
- PCIe: both slots report Gen 5 as their maximum. Card 0 sits in a slot of maximum width x16 and had negotiated x8. Card 1 sits in a slot of maximum width x8 and had negotiated x4.
- AMD Ryzen 9 9950X (16 cores), 32 GB DDR5 (the runner reports 31 GB), Windows build 10.0.26300.
- Strata Terminal 0.2.20 (`strata --version`: "strata 0.2.20 (build 0.1.66") with engine 0.1.65 (`0.1.65-windows-x86_64-cuda-cuda13`, the release archive of v0.2.19, unpacked by hand and selected with `strata components use 0.1.65`). The engine that came with the install, 0.1.66, was not benchmarked. The runner's reports give the Strata commit as `2e87c08db18aa4577c22fd623d6ba53252719d63` and the engine as 0.1.65.
- Model files on an NVMe SSD (WD_BLACK SN850X 2 TB, per the runner).
- Qwen3.8-Flash-Next GSQ-RCO Q2_0, context 131,072, int8 KV, low-RAM (resident) mode, picture reader on the CPU, MTP draft layer.
- Protocol `strata-qwen38-thinking-v1-draft.1`, track `custom` (the launch was not setup's default; see below).

## Commands

Two cards (runs 162964e7, 62879dbe, 8abfda9f):

```
strata launch --family qwen --model q2_0 --gpu 0,1 --drafting mtp --mtp on --yes --no-tui
strata bench run --url http://127.0.0.1:8080
```

One card (run b9fc22f3): the same with `--gpu 1`.
Run 444b0b93: the two-card line with `--tune quick` added.
Run 67340057: the two-card line with `--split-engine on` added.

The server was stopped and started again before every run. `--gpu 0,1` made card 1 the Main card and card 0 the Helper (the launcher's own recommendation).

## Results

Medians of three requests per case, with the minimum and maximum, as the runner printed them. Rates are the engine's own timings in tokens per second; first token is the client's time in seconds.

### One card against two

| Case | One card (b9fc22f3) | Two cards (162964e7) | Ratio |
| --- | --- | --- | --- |
| short, decode | 55.2 (51.8-55.5) | 93.2 (90.8-99.1) | 1.69 |
| 4K prompt, prompt read | 634.4 (579.8-711.6) | 1363.8 (1293.0-1366.4) | 2.15 |
| 4K prompt, decode | 55.3 (54.1-56.6) | 85.5 (85.1-91.2) | 1.55 |
| 4K prompt, first token | 6.50 s | 3.03 s | 0.47 |
| 16K prompt, prompt read | 993.1 (958.6-1060.4) | 2126.1 (2044.2-2129.2) | 2.14 |
| 16K prompt, decode | 53.1 (52.2-55.7) | 86.4 (79.3-95.2) | 1.63 |
| 16K prompt, first token | 16.56 s | 7.75 s | 0.47 |

These two runs were made one after the other. Time after the model loaded: 3 min 54 s on one card, 2 min 7 s on two.

### All five two-card runs

| Run | What differed | short decode | 4K prompt read | 4K decode | 16K prompt read | 16K decode |
| --- | --- | --- | --- | --- | --- | --- |
| 162964e7 | first run | 93.2 (90.8-99.1) | 1363.8 (1293.0-1366.4) | 85.5 (85.1-91.2) | 2126.1 (2044.2-2129.2) | 86.4 (79.3-95.2) |
| 62879dbe | monitor cable moved to the motherboard output | 98.1 (95.3-103.9) | 1348.6 (1345.1-1349.7) | 88.1 (87.1-92.5) | 2118.3 (2100.2-2120.1) | 84.7 (84.6-88.7) |
| 8abfda9f | same line again, later | 100.0 (97.5-100.4) | 1380.6 (1325.0-1382.8) | 93.8 (88.9-95.7) | 2147.3 (2093.9-2153.0) | 94.4 (81.5-95.8) |
| 444b0b93 | `--tune quick` | 101.0 (100.2-102.9) | 1350.7 (1348.4-1351.3) | 91.5 (88.4-94.4) | 2117.4 (2106.6-2121.2) | 82.1 (81.0-92.8) |
| 67340057 | `--split-engine on` (refused, normal layer split) | 99.9 (99.3-102.3) | 1343.8 (1338.7-1347.3) | 91.0 (88.0-93.7) | 2111.4 (2108.8-2113.2) | 81.6 (80.4-86.0) |

First token across the five: 1.12 to 1.20 s (short), 3.00 to 3.08 s (4K), 7.69 to 7.81 s (16K).

Against the single one-card run, the five two-card medians give prompt read 2.12x to 2.18x (4K) and 2.13x to 2.16x (16K), and decode 1.69x to 1.83x (short), 1.55x to 1.70x (4K) and 1.54x to 1.78x (16K).

### What the three changes did

- **Tuner.** `--tune quick` answered "Tuning result: already fastest. Your computer already runs at its best with the standard settings. Nothing needed changing."
- **Display.** Before run 62879dbe the monitor cable was moved from card 0 to the motherboard output, without a restart. `nvidia-smi` just before the launch still showed 934 MiB in use on card 0 with the desktop processes listed on it (1,181 MiB had been in use the day's first reading). Card 0's memory was not read again before the later runs.
- **All-cards split engine.** `--split-engine on` was refused with: "Using the normal layer split: the all-cards split engine runs on Linux (and Windows AMD HIP) only; the token embeddings are Q3_K, which it cannot convert to Q8_0; the shared expert is Q2_0/Q3_K/Q4_0/Q5_0, which it cannot read; all the experts do not fit in the cards' memory (each card needs about 41 GiB, has 15 GiB free); there is not enough free RAM (about 42 GiB needed, 24 GiB free)." Run 67340057 is therefore a fifth run of the normal layer split.

The differences between the five two-card runs are no larger than the spread inside single runs (16K decode ranged from 79.3 to 95.2 within the first run alone). I read them as run-to-run variation and credit none of the three changes with a gain. Prompt read is the steady figure: within 3 % across all five runs.

## Setup problem: the default Q2_0 launch did not start

`strata launch --family qwen --model q2_0 --gpu 0,1 --yes --no-tui` downloaded the model and the DFlash2 drafter, then the engine stopped while loading:

```
strata generate: --draft dflash2 --draft-fallback none: DFlash2 is off here: it needs a native pack; there is no MTP to draft instead, so the start ends here
```

It did the same on engine 0.1.66 and on 0.1.65, on two cards and on one (`--gpu 1`), and again with `--drafting mtp` added. Adding `--mtp on` as well made setup download the MTP draft layer (about 5 GB), and the model then loaded and answered. Every run here uses that line.

What I think happens, from reading the source at commit 6a6db7f; this is not confirmed by the maintainers:

1. On a CPU with AVX-512 VNNI and VBMI, setup builds Q2_0 as the AVX-512 pack, which has no `native_experts.txt`. The engine's DFlash2 check refuses a pack without it ("it needs a native pack").
2. Setup's automatic drafter rule still picks DFlash2 for this model, so the MTP layer is not downloaded. With `--drafting mtp` alone the launch found the model "already installed" and did not run setup again for the layer; at start the server had no MTP on disk and passed DFlash2 to the engine.

I found no existing issue with this error text when I searched on 2026-11-24.

## Limits

- One run on one card. The one-card figure has no repeat, so the ratios rest on it.
- The one card measured was card 1 (the x4 slot, no display). Card 0 alone was not run.
- Other programs were not closed for these runs. Before run 62879dbe a browser, a game launcher and the desktop were listed on card 0.
- Windows only. The Strata docs say a multi-GPU run under WDDM pins 8 GiB of the expert arena where Linux pins all of it; Linux was not run here.
- One pack (Q2_0) with the MTP drafter. DFlash2 and the i-quant and Unsloth packs were not run.
- The runner did not record the engine options: every run used `--url` against a server that was already running, so each `config.json` says "the server was already running; its engine options are not exposed". The launch lines above are the record of the configuration. Each runner report also notes that the server had answered a request before the run (the first one says 1).
- The layer placement was not read from the logs of these six starts, and the engine logs are not included (each start overwrote the last).
- Not comparable one to one with the TITAN RTX run in `strata-titan-rtx/`: that run used engine 0.1.62 with DFlash2 drafts and its own harness, not this protocol.
- The protocol is a draft; these are pilot data under its draft ID.

## Files

For each run, named by the last eight characters of the runner's folder name:

- `<run>-README.md`: the runner's own report.
- `<run>-results.json`: hardware, versions and every request.
- `<run>-outputs.jsonl`: the answers.
- `<run>-config.json`: the configuration the runner saved.

The files were renamed with the run prefix to sit in one folder, so the links inside the runner's reports (`results.json`, `outputs.jsonl`, `config.json`) point at the unprefixed names and do not resolve here. The runner's `provenance/` subfolder (the chat template) is not included.

Runs: `162964e7`, `b9fc22f3`, `62879dbe`, `8abfda9f`, `444b0b93`, `67340057` (in the order they were made). 24 files in all, as the runner wrote them.
