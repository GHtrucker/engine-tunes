# Turing A/B on NVIDIA TITAN RTX

turing_ab.py 1.0, started 2026-11-19T19:01:47Z, 13 min

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

Notes: (1) other programs were using the GPU at the start: 2320, C:\Windows\System32\dwm.exe, [N/A]; 7400, C:\Windows\System32\ShellHost.exe, [N/A]; 7836, C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\CrossDeviceResume.exe, [N/A]; 7220, C:\Windows\explorer.exe, [N/A]; 8604, C:\Windows\SystemApps\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\StartMenuExperienceHost.exe, [N/A]; 8596, C:\Windows\SystemApps\MicrosoftWindows.Client.CBS_cw5n1h2txyewy\SearchHost.exe, [N/A]; 10552, C:\Program Files (x86)\Microsoft\EdgeWebView\Application\157.0.4341.60\msedgewebview2.exe, [N/A]; 13020, C:\Program Files (x86)\Microsoft\EdgeWebView\Application\157.0.4341.60\msedgewebview2.exe, [N/A]; 10192, C:\Program Files\WindowsApps\MicrosoftWindows.Client.WebExperience_526.21100.40.0_x64__cw5n1h2txyewy\WidgetBoard.exe, [N/A]; 16340, C:\Windows\System32\ApplicationFrameHost.exe, [N/A]; 8236, C:\Windows\ImmersiveControlPanel\SystemSettings.exe, [N/A]; 1052, C:\Windows\SystemApps\ShellExperienceHost_cw5n1h2txyewy\ShellExperienceHost.exe, [N/A]; 14624, C:\Program Files\Google\Chrome\Application\chrome.exe, [N/A]; 2668, C:\Program Files\Google\Chrome\Application\chrome.exe, [N/A]. (2) this card drives a display: desktop activity during the run adds noise.

## Identity lane (no PCIe-streamed experts, expert tier adaptive: `--pcie-frac 0`; greedy, byte-for-byte against base, paired by round, 3 rounds)

| Arm | Identical to base | Differs on | Expected |
| --- | --- | --- | --- |
| base2 | 22 of 27 | r1 id2, r1 id3, r1 id7, r1 id8, r1 doc4k | identical |
| sm75 | 20 of 27 | r3 id2, r3 id3, r3 id4, r3 id5, r3 id7, r3 id8, r3 doc4k | identical |

**base2 differs from base: this setup is not deterministic across restarts in this mode, so the other identity results cannot be read as kernel differences.**

## Card and engine per arm (speed lane)

| Arm | SM clock MHz | Power W | Max temp C | GPU util % | PCIe | Clock limits seen | Expert slots | Cache hit % | Load s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base | - | - | - | - | - | none | - | - | - |
| base2 | - | - | - | - | - | none | - | - | - |
| sm75 | - | - | - | - | - | none | - | - | - |

<details><summary>Engine log lines from the first start (all logs are in logs/)</summary>

```text
identity-r1-base:
  [strata] 2026-11-19 13:02:00 engine started: C:\Strata\terminal\engine\strata.exe --serve --pack C:\Strata-data\packs\q2_0 --native C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00001-of-00002.gguf --ple-gguf C:\Strata-data\models\Q2_0\Qwen3.8-Flash-Next-GSQ-RCO-Q2_0-00002-of-00002.gguf
  strata generate: the resident RAM mode cannot resize the expert cache, so the picture reader's 2048 MiB stay in the reserve (700 MiB asked)
  strata generate: expert cache auto: 16.94 GiB free, 2048 MiB reserved (+346 MiB for the draft head, +256 MiB for what is allocated after the cache) -> 11149 slots
  strata generate: expert cache 11149 slots, 14.35 GiB of VRAM; policy is
  strata dflash2: 106299-token draft head (178.4 MiB), drafter 765 MiB of VRAM (Q4_0 weights)
  strata serve: 2143 MiB of VRAM free with everything loaded
  strata verify: capturing the 1-token window (2143 MiB of VRAM free)
  strata verify: captured the 1-token window (upload no error, sync no error) in 18.3 ms
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
