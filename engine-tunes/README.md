# engine-tunes

Benchmark and tuning runs of local AI inference engines on my own hardware. Each run is published with the script that produced it and the raw results, so anyone can check the numbers or repeat the test on their own machine.

## Runs

| Folder | Test | Result |
| --- | --- | --- |
| [strata-titan-rtx](strata-titan-rtx/REPORT.md) | [Strata](https://github.com/Niko1221/Strata) 0.2.16 (engine 0.1.62), `STRATA_SM75_PERF=1` on one NVIDIA TITAN RTX, Windows 11, ready-made package, Q2_0 pack. Written for [Strata #2197](https://github.com/Niko1221/Strata/issues/2197). | Identical answers with the expert tier frozen (36/36); 17/30 identical in setup's config; decode +2 to +9 % |

Start with the folder's `REPORT.md`. It has the environment, the method, the tables, what was not run, and the limits.

## Repeating the Strata run

You need Strata installed and set up with a model, a Turing card (compute capability 7.5: RTX 20 series, TITAN RTX, Quadro RTX, T4), and `nvidia-smi` on the path. The script uses only Python's standard library and changes nothing in the Strata folder.

1. Copy `turing_ab.py` and `compare_outputs.py` to a folder outside the Strata folder.
2. Close other programs that use the GPU.
3. Check the setup first, then run it, with Strata's own Python:

```text
C:\Strata\terminal\.venv\Scripts\python.exe turing_ab.py --strata C:\Strata --dry-run
C:\Strata\terminal\.venv\Scripts\python.exe turing_ab.py --strata C:\Strata
C:\Strata\terminal\.venv\Scripts\python.exe compare_outputs.py
```

The full run took about 40 minutes here. Results land in a `results` folder next to the script; open its `summary.md` first. `compare_outputs.py` shows where any differing answers split. The exact commands for the two extra identity lanes are in the report.

The logs and configs a run writes are not scrubbed. Read them before you post them anywhere.

## How this was made

The harness and the write-up were prepared with help from an AI assistant. I ran every test on my own machine. A second AI assistant, which took no part in the runs, recomputed the main run's numbers from the raw files and checked the citations.

## License

MIT. See [LICENSE](LICENSE).
