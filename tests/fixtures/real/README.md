# Real-migration fixtures

These are files from three open-source projects, used to test luna-check against real migrations off `gpt-4o-mini`. Each `before/` folder holds the files as they were upstream. Each `after/` folder holds the same files after prasadrandika's migration commit, which **modifies** the original code.

| Folder | Project | License | Before (upstream) | After (migration commit) |
|---|---|---|---|---|
| `dsl/` | [projectdiscovery/dsl](https://github.com/projectdiscovery/dsl) | MIT, see `dsl/LICENSE.md` | `e20410a0850623a7fd97d8f621222fe4e73ec1f6` | `88e35fe13d526bd7746026a74ad74eb055fba588` |
| `nasiko/` | [Nasiko-Labs/nasiko](https://github.com/Nasiko-Labs/nasiko) | Apache-2.0, see `nasiko/LICENSE` | `97cd065eebafc748ed78fbef750c7a2b12622b04` | `167ea56e2bf6c1b7ba46f2b63840e0654d84d36a` |
| `weclaw/` | [fastclaw-ai/weclaw](https://github.com/fastclaw-ai/weclaw) | MIT, see `weclaw/LICENSE` | `f9560754a67a7ed5e83be1eb793d972471b06cf7` | `61f70704aa6945ff9b75a650c1e6ecb45fe54d61` |

The files keep their original licenses. luna-check's MIT license does not cover them.

Two more migrations, Basic-Rag and youtube_transcription_api, have no license, so their files are **not** copied here. `tests/test_real_repos.py` downloads them at pinned commits from the public forks at github.com/prasadrandika when the tests run.
