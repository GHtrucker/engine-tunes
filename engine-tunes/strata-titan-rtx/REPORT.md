# TITAN RTX (one card), Windows 11, ready-made package: `STRATA_SM75_PERF=1` on Q2_0, engine 0.1.62

**Result in one line:** identical answers with the expert tier frozen (36/36); 17/30 identical in setup's config, where the tier is adaptive; decode +2 to +9 %.

Written for [Niko1221/Strata #2197](https://github.com/Niko1221/Strata/issues/2197) (make the `STRATA_SM75_PERF` series the default on sm_75). Three runs on 2026-11-19.

I haven't found a run of the shipped Windows package in this thread, so this one checks the series in that package: `0.1.62-windows-x86_64-cuda-cuda13` from the update feed, not built locally. The switches take effect there on this sm_75 card (the speed changes below). It is also a single desktop card with 32 GB of RAM in low-RAM (resident) mode, on the same Q2_0 pack as the T4 run earlier in the thread.

**Environment:** Strata 0.2.16 (58ee322), engine 0.1.62, Windows 11 build 26300, driver 621.24 (WDDM; the card also drives the display). NVIDIA TITAN RTX 24 GB, PCIe 3.0 x16, power limit lowered to 250 W (default 280 W). Xeon W-2123 (4 cores), 32 GB DDR4-2133, fixed page file (4 GB on C: + 64 GB on a second NVMe). Qwen3.8-Flash-Next GSQ-RCO Q2_0 with setup's config after `--calibrate` (it kept the defaults): `--expert-profile data/expert-profile.bin --expert-cache auto --prefill auto --spec 4 --mtp <mtp dir> --max-context 131072 --kv int8 --resident-experts --vision --vram-reserve-mib 700 --spec-min-p 0.5` (pack and model paths omitted; the full line is in `summary.md`). The server turns the draft flags into `--draft dflash2 --draft-fallback none --spec 6 --draft-conf 0.5 --vram-elastic` on the engine's own command line (the first line of every engine log). Drafts come from DFlash2: `--mtp` is in the config, but the log reports no MTP layer loaded. 11,149 expert slots in every start (all 42 starts across the three runs). Resident mode held 19.85 GiB of the other experts in RAM in every start; at most 120 expert blobs per start were read from the drive.

**Method:** `turing_ab.py` (in this folder; Python standard library only). It starts `terminal/serve/server.py` fresh for each arm in each round, as `terminal/tools/ab_engine.py` does, reverses the arm order every round, sends greedy requests with thinking off, takes rates from the engine's `timings`, and hashes every full answer. One warm-up request per start, not counted. Every prompt was read fresh: 0 cached prompt tokens on every request in all three runs. Speed-lane prompts carry a per-round tag, the same for every arm within a round. base2 is a second baseline start that measures noise and reproducibility. Identity prompts: 8 short plus one ~4K-token prompt. I started each run, then closed every other window and turned the display off for the measurement (the summaries list the desktop processes present at launch).

Commands, run with Strata's own Python (`C:\Strata\terminal\.venv\Scripts\python.exe`):

```text
turing_ab.py --strata C:\Strata
turing_ab.py --strata C:\Strata --skip-speed --arms base base2 sm75 --identity-mode adapt-off --identity-rounds 3
turing_ab.py --strata C:\Strata --skip-speed --arms base base2 sm75 --identity-mode pcie-off --identity-rounds 3
```

The first is the main run (speed lane, 5 rounds, plus the first identity lane). It used an earlier version of the script whose identity lane was fixed to `--adapt-every 0 --pcie-frac 0`; in the version published here that is `--identity-mode frozen`, the default, so the same command reproduces it. All three summaries carry the script's label at the time, 1.0; the file published here is labelled 1.1.

**Identity**, by lane (flags added to setup's config):

| Lane | Flags | Rounds | base2 = base | `SM75_PERF=1` = base |
| --- | --- | ---: | ---: | ---: |
| tier frozen, no PCIe-streamed experts | `--adapt-every 0 --pcie-frac 0` | 1 | 9/9 | 9/9 |
| tier frozen, PCIe share left to the engine | `--adapt-every 0` | 3 | 27/27 | 27/27 |
| tier adaptive, no PCIe-streamed experts | `--pcie-frac 0` | 3 | 22/27 | 20/27 |
| setup's config (speed-lane prompts) | none | 5 | 30/30 | 17/30 |

The PCIe share is not a fixed setting: in the main run's logs the engine starts every speed-lane start at 0.55 and, after the warm-up request, measures its way to 0.60 (in one start, base2 in round 2, it went back to 0.55 after chat 1 and up to 0.60 again after chat 3).

`--adapt-every 0` did freeze the tier: the engine logged 0 swaps ("exchanged with the VRAM tier") on all 130 per-request lines of the 13 frozen-lane starts, against nonzero counts in the adaptive lane.

With the expert tier frozen, the series changed no answer (36/36), with or without PCIe-streamed experts, and neither did a second baseline start. The lanes that don't reproduce are exactly the ones with the tier adaptive. There the baseline itself is not reproducible across restarts on this box: in the third lane base2 differed from base on 5 of 27 answers, all 5 in one round. That fits what others saw earlier in this thread: Adamyno (the same arm twice differed with the adaptive tier), coolthor (the default arm differed across restarts at long context) and ozabramov (answers changed between rounds of the same arm in setup's config). It also fits the docs (the "Reproducible output" recipe adds `--adapt-swaps 0`; seed-reproducible sampling needs `--adapt-every 100000`), #5136 (route tail skip keys on residency that the adaptive swaps move) and #4673 (T=0 answers not reproducible on the Windows CUDA package, 0.1.52/0.1.54). What the table adds is the split between the two moving parts on one box: freezing the tier was enough here, and PCIe-streamed experts made no difference to identity. That isn't general: Adamyno's two-card rig still drifted between restarts with a static cache.

In setup's config, base2 held 30/30 while the series flipped 13/30. All 13 are in 3 of 5 rounds. In each of those rounds, during the first request, the series arm's offered-draft count and route-tail-skip count already differed from base's while that request's text was still identical; in round 1 the tier's swap count after that request was still the same (1,027 in both). In the two rounds without flips, those counts matched base's too. All 13 flips are mid-answer near-ties (split at roughly output tokens 37–230), with both continuations coherent and on-topic, e.g. "…to memorize vocabulary efficiently" vs "…to efficiently memorize vocabulary" (`diff_report.txt` has every split). They go both ways: on the ~16K prompt, the same two openings swap sides between rounds 1 and 5.

That first-request difference is not specific to the series, and on its own it changes no answer. In the frozen lane of the main run the same two counts differed between the two baseline starts as well: on the first request base offered 230 drafts, base2 224 and the series 220, with 204 accepted and byte-identical text in all three, and the tail-skip counts differed the same way. So the counts move between restarts even with the tier frozen; only with the tier adaptive does a later answer change.

Counted by start across the two adaptive-tier lanes, the series diverged in 4 of 8 starts and base2 in 1 of 8, too few to say the series does it more often. One pattern I can't explain: all 4 of the series' divergent starts ran after base in their round (rounds 1, 3 and 5 of the speed lane, round 3 of the adaptive identity lane). It diverged in 4 of the 5 starts where it ran after base and in none of the 3 where it ran before. That could be chance (about 1 in 14); a run with a fixed arm order would test it. base2's one divergent start also ran after base. And the two arms are not placed alike: in the speed lane the order is base, base2, sm75, sm75_tc, then reversed, so base2 always starts next to base and the series never does. base2 is therefore a noise check for neighbouring starts, not for the series' position.

My reading: the series' kernels give identical answers whenever the tier is frozen (36/36). With the tier adaptive, a run can take a different path through drafting and the tail skips early on, and a later near-tie then goes the other way. That happened to the series arm in 4 starts and to the second baseline in 1. I haven't isolated what triggers it, or whether the series makes it more likely. How often it shows up depends on the rig: Adamyno's Lane A (adaptive tier, IQ3_S) was 4/4 identical. With `STRATA_BF16_TC=1 STRATA_SELECT_SIMT=1` added, 8/9 matched in the first lane (the 4K prompt differs), as expected for those opt-ins.

**Speed** (setup's config; base is the median of 5 rounds; the other columns are medians of the 5 paired per-round changes against base, with rounds won):

| Request | base | base2 (noise) | `SM75_PERF=1` | + `BF16_TC` + `SELECT_SIMT` |
| --- | ---: | ---: | ---: | ---: |
| chat 1, decode | 51.4 tok/s | 0.0% (2/5) | +2.4% (4/5) | +1.0% (4/5) |
| chat 2, decode | 54.7 tok/s | -0.2% (1/5) | +6.9% (5/5) | +6.8% (5/5) |
| chat 3, decode | 57.1 tok/s | 0.0% (2/5) | +4.4% (5/5) | +4.0% (5/5) |
| 1,024-token answer, decode | 76.0 tok/s | 0.0% (1/5) | +9.4% (5/5) | +9.3% (5/5) |
| ~4K prompt, read | 1,075 tok/s | -0.6% (0/5) | +4.3% (5/5) | +27.5% (5/5) |
| ~16K prompt, read | 1,382 tok/s | -0.1% (2/5) | +7.5% (5/5) | +41.0% (5/5) |

The decode gains don't depend on the flips: on the 12 decode requests whose answers matched base exactly, the series was faster in 11 (median +4.5 %, range -1.2 to +8.7 %), and the 1,024-token answer gained +8.6/+8.7 % in the two rounds where it matched. The prompt-read rates are measured before that request generates any text, so its own flip can't touch them; across rounds with and without an earlier flip in the same start, the series' read rates stay within 0.5 % of each other. No request failed in any run (156 in the main run).

**`BF16_TC` + `SELECT_SIMT` on top of the series** (numerics opt-ins outside the proposal; `=1` for both is the pair docs/OLDER_GPUS.md sets for Turing in its Quadro RTX 8000 section; medians of paired per-round changes against the `SM75_PERF=1` arm): ~4K prompt read +22.1 % (5/5), ~16K +31.2 % (5/5); decode -1.3 / 0.0 / 0.0 / -1.0 %. The T4 run had BF16_TC alone; with SELECT_SIMT also on here, the picture is the same: a large prompt-read gain, decode flat.

Card telemetry was flat across arms (SM clock 1,886–1,905 MHz, 66 °C at most). `sw_power_cap` appeared in every arm, which fits the lowered 250 W limit.

**Against the T4 on the same pack:** the decode gain here (+2.4 to +9.4 %) is well below the T4's +20 to +27 %. I haven't isolated why. rafatxf's reading earlier in the thread, that the size depends on how much of the decode runs on the GPU, fits the numbers: the T4 ran down to about 660 MHz at its 70 W cap, on a host with 52 vCPUs. This card ran at ~1.9 GHz, with a 4-core CPU taking its share of the experts that miss the card (2–29 % of expert lookups per request; decode expert-cache hit rate 70.7–98.2 %, median 91.35 %, over the speed lane's 120 requests in the engine logs). So the GPU kernels are a smaller share of each token here. If it helps, I can run `STRATA_SM75_IL=1` alone to see whether IL carries the gain on this card too.

**Not run:** the full byte-identical recipe (the frozen lanes used `--adapt-every 0`, not `--adapt-swaps 0`, and kept the prompt cache on, though no request reused cached tokens; I didn't set `STRATA_IQ_MT_MIN=1`, which the T4 identity lane used, nor `STRATA_PREFILL_CPU_SHARE=0` and `STRATA_ROUTE_TAIL_SKIP=0`, which docs/OLDER_GPUS.md adds for comparing answers byte for byte: the main run's logs show both at their defaults); a `--window-hashes` run; the 10-prompt / exact_pp gate (the identity lanes used 9 prompts up to ~4K tokens; the setup's-config row covers the speed prompts up to ~16K); other packs (setup marked only Q2_0 as fitting this box); per-switch drop-one; a fixed-arm-order run; concurrent requests; a cuobjdump check of the binary.

**Limits:** one machine, one pack, one request at a time, power limit lowered to 250 W.

Reproduction status: measured locally. The harness and this write-up were prepared with help from an AI assistant; I ran every test on this machine, and every number comes from the files in this folder. The hit rates and the swap, skip and draft counts come from the engine logs: the main run's are included, and the two identity lanes' logs are kept and can be added.

**Files:** `turing_ab.py` and `compare_outputs.py` (the harness), `summary.md` and `requests.csv` (main run; the summary was rewritten from the run's own files with paired changes, so its numbers match this report), `diff_report.txt` (where each differing answer splits), `logs-main-run/` (the main run's 24 engine logs), `summary-tier-frozen.md` and `summary-tier-adaptive.md` (the two identity lanes). The summaries are the harness's output as written: their "Files" footers name run files (`outputs.jsonl`, `telemetry.csv`, `machine.json`, `configs/`) that are not published here.

## Verification

A second AI assistant, which did not write the harness or take part in the runs, recomputed the main run's numbers from `requests.csv`, the 24 engine logs and `diff_report.txt`: the identity counts, the 13 flips and where they split, every row of the speed table, the opt-in comparison, the matched-answer decode figures, the swap, draft and skip counts, and the hit rates. All matched. The two extra identity lanes (27/27, 22/27, 20/27) were checked against their summaries only. The citations to the thread, #4673, #5136 and the docs were checked against the sources on 2026-11-19.
