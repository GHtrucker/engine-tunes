# Turing A/B on NVIDIA TITAN RTX

turing_ab.py 1.0, started 2026-11-19T17:09:19Z, 40 min (this summary rewritten by turing_ab.py 1.1)

## Machine

| | |
| --- | --- |
| GPU | NVIDIA TITAN RTX, 24576 MiB, compute 7.5, power limit 250.00 W (max 320.00 W), PCIe gen3 x16 max, driver model WDDM, display Enabled |
| Driver | 621.24, VBIOS 90.02.23.00.01 |
| CPU | Intel(R) Xeon(R) W-2123 CPU @ 3.60GHz (4 cores) |
| RAM | 32 GiB in 6 modules (CPU0-DIMM1, CPU0-DIMM2, CPU0-DIMM3, CPU0-DIMM6, CPU0-DIMM7, CPU0-DIMM8), running at 2133 MT/s |
| OS | Windows 11 (10.0.26300) |
| Power plan | Power Scheme GUID: 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c  (High performance) |
| Strata | Version 0.2.16, engine 0.1.62. The public model families are, commit `58ee32277206` |
| Config | `strata-q2_0.json`, context 131072 |

```text
--pack C:\Strata-data\packs\q2_0 --native C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf --ple-gguf C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00002-of-00002.gguf --expert-profile C:\Strata\terminal\data\expert-profile.bin --expert-cache auto --prefill auto --spec 4 --mtp C:\Strata-data\mtp\rt --max-context 131072 --kv int8 --resident-experts --vision --vram-reserve-mib 700 --spec-min-p 0.5
```

Notes: (1) other programs were using the GPU at the start: 2320, C:\Windows\System32\dwm.exe, [N/A]; 7400, C:\Windows\System32\ShellHost.exe, [N/A]; 7836, C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\CrossDeviceResume.exe, [N/A]; 7220, C:\Windows\explorer.exe, [N/A]; 8604, C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe, [N/A]; 8596, C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\SearchHost.exe, [N/A]; 10552, C:\Program Files (x86)\Microsoft\EdgeWebView\Application\157.0.4341.60\msedgewebview2.exe, [N/A]; 13252, C:\Program Files\Google\Chrome\Application\chrome.exe, [N/A]; 13020, C:\Program Files (x86)\Microsoft\EdgeWebView\Application\157.0.4341.60\msedgewebview2.exe, [N/A]; 13536, C:\Program Files\Google\Chrome\Application\chrome.exe, [N/A]; 10192, C:\Program Files\WindowsApps\MicrosoftWindows.Client.WebExperience_526.21100.40.0_x64__cw5n1h2txyewy\WidgetBoard.exe, [N/A]; 16340, C:\Windows\System32\ApplicationFrameHost.exe, [N/A]; 8236, C:\Windows\ImmersiveControlPanel\SystemSettings.exe, [N/A]; 1052, C:\Windows\SystemApps\ShellExperienceHost_cw5n1h2txyewy\ShellExperienceHost.exe, [N/A]. (2) this card drives a display: desktop activity during the run adds noise.

## Identity lane (expert tier frozen, no PCIe-streamed experts: `--adapt-every 0 --pcie-frac 0`; greedy, byte-for-byte against base)

| Arm | Identical to base | Differs on | Expected |
| --- | --- | --- | --- |
| base2 | 9 of 9 | - | identical |
| sm75 | 9 of 9 | - | identical |
| sm75_tc | 8 of 9 | doc4k | may differ |

base2 equals base: the setup is deterministic across restarts, so a difference in another arm comes from its switches.
**sm75 equals base on every request in this mode (frozen): no answer changed on this card for these prompts.**

## Speed lane (5 rounds, fresh server per arm per round, arm order flipped each round)

Engine-reported rates. Decode for the chats and the long answer, prompt reading for the documents. Each cell: the arm's median rate (min-max, n), then the median of its per-round paired changes against base (same round, same prompt); **wins** counts the rounds in which the arm beat base.

| Request | Metric | base | base2 | sm75 | sm75_tc |
| --- | --- | --- | --- | --- | --- |
| chat1 | decode tok/s | 51.4 (50.8-51.7, 5) | 51.5 (50.8-52.0, 5) +0.0% paired, wins 2/5 | 52.6 (51.1-53.1, 5) +2.4% paired, wins 4/5 | 51.6 (50.0-52.7, 5) +1.0% paired, wins 4/5 |
| chat2 | decode tok/s | 54.7 (53.8-56.4, 5) | 54.6 (53.6-56.5, 5) -0.2% paired, wins 1/5 | 58.8 (56.8-60.7, 5) +6.9% paired, wins 5/5 | 59.5 (55.6-60.4, 5) +6.8% paired, wins 5/5 |
| chat3 | decode tok/s | 57.1 (54.6-59.7, 5) | 56.8 (54.7-59.7, 5) +0.0% paired, wins 2/5 | 59.2 (56.5-62.5, 5) +4.4% paired, wins 5/5 | 59.2 (58.5-61.7, 5) +4.0% paired, wins 5/5 |
| doc4k | prompt tok/s | 1,075.2 (1,074.1-1,078.7, 5) | 1,072.6 (1,061.0-1,074.3, 5) -0.6% paired, wins 0/5 | 1,122.1 (1,118.5-1,123.8, 5) +4.3% paired, wins 5/5 | 1,370.5 (1,356.6-1,377.6, 5) +27.5% paired, wins 5/5 |
| doc16k | prompt tok/s | 1,382.4 (1,377.4-1,389.3, 5) | 1,380.9 (1,377.9-1,382.3, 5) -0.1% paired, wins 2/5 | 1,486.7 (1,481.1-1,487.9, 5) +7.5% paired, wins 5/5 | 1,950.1 (1,937.6-1,951.7, 5) +41.0% paired, wins 5/5 |
| sustained | decode tok/s | 76.0 (72.9-77.4, 5) | 76.1 (72.9-77.4, 5) +0.0% paired, wins 1/5 | 82.5 (81.7-84.1, 5) +9.4% paired, wins 5/5 | 81.7 (79.8-83.3, 5) +9.3% paired, wins 5/5 |

Answers in the speed lane identical to base's, paired by round (setup's config, so the expert tier and the PCIe share move): base2 30 of 30, sm75 17 of 30, sm75_tc 12 of 30.

Noise (base2 against base): chat1 ±0.0%, chat2 ±0.2%, chat3 ±0.0%, doc4k ±0.6%, doc16k ±0.1%, sustained ±0.0%. A change inside that band, or one that does not win most rounds, is not evidence.

## Card and engine per arm (speed lane)

| Arm | SM clock MHz | Power W | Max temp C | GPU util % | PCIe | Clock limits seen | Expert slots | Cache hit % | Load s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base | 1,886 | 212.3 | 65 | 92 | gen3 x16 | sw_power_cap | 11,149 | 90.9 | - |
| base2 | 1,886 | 218.5 | 66 | 92 | gen3 x16 | sw_power_cap | 11,149 | 90.9 | - |
| sm75 | 1,898 | 220.1 | 65 | 90 | gen3 x16 | sw_power_cap | 11,149 | 90.9 | - |
| sm75_tc | 1,905 | 209.9 | 64 | 90 | gen3 x16 | sw_power_cap | 11,149 | 90.8 | - |

<details><summary>Engine log lines from the first start (all logs are in logs/)</summary>

```text
identity-r0-base:
  [strata] 2026-11-19 11:09:32 engine started: C:\Strata\terminal\engine\strata.exe --serve --pack C:\Strata-data\packs\q2_0 --native C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf --ple-gguf C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00002-of-00002.gguf
  strata generate: the resident RAM mode cannot resize the expert cache, so the picture reader's 2048 MiB stay in the reserve (700 MiB asked)
  strata generate: expert cache auto: 16.94 GiB free, 2048 MiB reserved (+346 MiB for the draft head, +256 MiB for what is allocated after the cache) -> 11149 slots
  strata generate: expert cache 11149 slots, 14.35 GiB of VRAM; policy is
  strata dflash2: 106299-token draft head (178.4 MiB), drafter 765 MiB of VRAM (Q4_0 weights)
  strata serve: 2143 MiB of VRAM free with everything loaded
  strata verify: capturing the 1-token window (2143 MiB of VRAM free)
  strata verify: captured the 1-token window (upload no error, sync no error) in 29.5 ms
  strata serve: decode expert cache hit rate: 76.0% (3034 hits / 3993 lookups)
  strata serve: resident RAM: 19.85 GiB of experts in RAM, 0 exchanged with the VRAM tier, 0 blob reads from the file
```

</details>

## Files

- `requests.csv`: one row per request (engine timings, token counts, wall time, answer hash)
- `outputs.jsonl`: every answer in full with its usage, timings and the card's telemetry for that request
- `telemetry.csv`: nvidia-smi once a second, tagged with what was running
- `machine.json`, `configs/`, `logs/`: the setup, the exact configs, and the engine and server logs

Logs and configs are not scrubbed. Read them before you post them anywhere.
