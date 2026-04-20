# Guardian — Anti-Scam Decision Security Agent

> On-device AI that protects elderly banking users' **decisions**, not just their transactions.

Prototype for FTEC5660 group project. See `ppt.md` for the pitch,
`.windsurf/plans/streamlit-refactor-e18e62.md` for the refactor plan,
and `legacy-flutter/` for the original Flutter prototype this Python
port replaces.

---

## What it does

Three cooperating agents run entirely on-device:

- **Context Agent** buffers call / SMS / chat / transaction events in a
  rolling 72-hour window and maintains temporal features (seconds since
  last call, prior max risk, recent-event counts).
- **Risk Agent** produces an interpretable score: a fast rule layer
  (scam blocklist + keyword + temporal rules) fused with an LLM
  (Ollama + ReAct tool loop) and a reviewer second-opinion
  (heuristic) when the primary LLM's confidence is low or it diverges
  from the fast score.
- **Intervention Agent** maps the final risk to graduated friction —
  silent, ambient banner, full-screen pause, or 24-hour delay.

Every decision is surfaced in the **Audit** screen with rule
contributions, LLM tactics / reasons, reviewer score, consensus label,
and the full tool-call trace — *explainability by construction*.

---

## Stack

- **Python 3.11+** + **Streamlit** multi-page app (sidebar nav, stock widgets).
- **Ollama** (optional) for the LLM layer; falls back to a deterministic
  heuristic runtime when unavailable — the UI never deadlocks.
- Data lives at the repo root (`data/scam_db.csv`, `scenarios/*.json`)
  so both the Streamlit port and the legacy Flutter tree read the same
  source of truth.

---

## Quick start

### Prerequisites

| Tool | Install |
|------|---------|
| Python 3.11+ | `sudo apt install python3 python3-venv` |
| just | `curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh \| bash -s -- --to ~/.local/bin` |
| Ollama (optional, for real LLM) | `curl -fsSL https://ollama.com/install.sh \| sh` |

### Bootstrap

```bash
just setup              # creates .venv and installs streamlit + deps
just fetch-model        # pulls llama3.2:3b via ollama (skip if ollama absent)
just run                # launches on http://localhost:8501
```

### Demo

```bash
just play 04_urgent_transfer     # auto-plays the flagship multi-vector scam
just play 03_romance_investment  # pig-butchering chat with temporal memory
just play benign_01_family_transfer   # sanity: no false positive
```

Or open the app and click a scenario button on the Home page.

---

## Repository layout

```
projects/group/
├── streamlit_app/                 # Python port (primary)
│   ├── app.py                     # entry: `streamlit run streamlit_app/app.py`
│   ├── pages/                     # multi-page nav targets (Home, Bank, Messages, …)
│   ├── guardian/
│   │   ├── agents/                # context / risk / intervention / bank / user_settings
│   │   ├── llm/                   # runtime abc + ollama + heuristic + prompts + tools
│   │   ├── scenarios/             # event model + engine
│   │   ├── data/                  # scam_db + event_log
│   │   ├── ui/                    # render fns per screen (bank.py, audit.py, …)
│   │   └── core/theme.py          # RiskPalette
│   ├── tools/eval.py              # headless scenario evaluator
│   ├── tests/                     # pytest unit tests
│   └── pyproject.toml             # deps
├── data/
│   └── scam_db.csv                # blocklist + keyword weights
├── scenarios/                     # source-of-truth scripted scenarios
│   ├── 01_sms_phishing.json
│   ├── 02_voice_police.json
│   ├── 03_romance_investment.json
│   ├── 04_urgent_transfer.json
│   ├── benign_01_family_transfer.json
│   └── benign_02_utility_bill.json
├── legacy-flutter/app/            # previous Flutter prototype (preserved)
├── reports/                       # written by `just eval`
├── justfile                       # CLI entry-point
├── ppt.md                         # pitch deck
└── README.md
```

---

## CLI (`just <task>`)

### Streamlit (primary)

| Command | Purpose |
|---------|---------|
| `just setup` | Create `.venv`, install deps + pytest + ruff |
| `just run` | `streamlit run streamlit_app/app.py` |
| `just play <scenario>` | Launch + auto-play via `GUARDIAN_AUTOPLAY` env |
| `just test` | `pytest streamlit_app/tests` |
| `just eval` | Headless scenario eval (heuristic, exits non-zero on fail) |
| `just eval-ollama` | Same eval, using Smart runtime (Ollama + fallback) |
| `just lint` \| `just fmt` | `ruff check` / `ruff format` |
| `just fetch-model [name]` | `ollama pull` — default `llama3.2:3b` |
| `just list-models` / `just list-scenarios` | Inventory |
| `just clean` | Wipe `.venv` + caches |

### Legacy Flutter

| Command | Purpose |
|---------|---------|
| `just flutter-setup` | `pub get` + sync scenarios into the Flutter asset tree |
| `just flutter-run [platform]` | `flutter run -d linux / chrome / …` |
| `just flutter-play <scenario> [platform]` | Flutter with `AUTOPLAY=<id>` |
| `just flutter-test` / `flutter-eval` | Dart unit tests / Dart eval CLI |
| `just flutter-build-linux` \| `-web` \| `-android` | Release builds |
| `just flutter-clean` | `flutter clean` + drop synced scenarios |

---

## Demo script (90 s)

1. `just run` — presenter opens Guardian in the browser at
   http://localhost:8501.
2. Click **04 urgent transfer** on the Home page to auto-play.
3. Fake "Police" call arrives — sidebar shows scenario progress, an
   ambient banner appears: *"Something looks off about this call"*.
4. 45 s later a phishing SMS lands in **Messages**. Banner escalates.
5. Presenter opens **Bank → Transfer**. The form is pre-filled with
   the scripted 50 000 HKD recipient. Click **Review and send**.
6. Full-screen dialog: plain-language explanation stitched from the
   LLM reasons + rule contributions, 60 s cool-off, **Call my son**
   button, override locked for 24 h.
7. Navigate to **Audit** to show rule contribution bars, LLM JSON
   output, reviewer consensus, and the ReAct tool-call trace —
   demonstrating explainability.
8. Back to Home → play **benign_01_family_transfer** to show no false
   positive.

---

## Eval snapshot

All 6 scripted scenarios pass intervention + risk-range checks against
the rule + heuristic-LLM pipeline (heuristic is the always-available
fallback; with ollama + `llama3.2:3b` the LLM stage refines tactics
and explanations further).

| Scenario | Risk | Expected | Intervention | Pass |
|----------|------|----------|--------------|------|
| 01_sms_phishing | 1.00 | [0.70, 1.00] | fullScreen | ✓ |
| 02_voice_police | 1.00 | [0.70, 1.00] | fullScreen | ✓ |
| 03_romance_investment | 1.00 | [0.65, 1.00] | fullScreen | ✓ |
| 04_urgent_transfer | 1.00 | [0.85, 1.00] | delay | ✓ |
| benign_01_family_transfer | 0.00 | [0.00, 0.30] | none | ✓ |
| benign_02_utility_bill | 0.15 | [0.00, 0.30] | none | ✓ |

Re-run yourself with `just eval` (heuristic) or `just eval-ollama`
(Smart runtime). Reports land in `reports/eval-<ts>.json`.

---

## LLM runtime & tuning

The sidebar shows a live LLM health pill that can be in one of three
states:

- `ollama/llama3.2:3b` — primary healthy, every risk score goes through
  the real LLM.
- `heuristic (primary cooling down · retry in Ns)` — primary timed out
  once; the session falls back to the deterministic heuristic and the
  primary is re-probed automatically after an exponential cooldown
  (30 s → 60 s → 120 s → 300 s). Click **Retry primary now** to skip
  the wait.
- `heuristic` — primary was never reachable (Ollama not running or not
  serving the configured model).

### Why single-shot by default

`llama3.2:3b` cannot reliably follow the ReAct `<tool>{...}</tool>`
grammar — it hallucinates XML-attribute tags and fabricates its own
`<observation>` blocks. Single-shot JSON mode (enforced via Ollama's
`format: "json"`) is both faster (~2× shorter prompt) and strictly
well-formed. Opt into the full tool-use loop with:

```bash
GUARDIAN_REACT=1 just run
```

Larger models (`qwen2.5:7b`, `llama3.1:8b`) handle the ReAct grammar
fine at the cost of more RAM and longer latency.

### Environment knobs

| Variable | Default | Purpose |
|----------|---------|---------|
| `OLLAMA_ENDPOINT` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2:3b` | Chat model name |
| `OLLAMA_TIMEOUT` | `120` | Per-inference timeout (seconds) |
| `OLLAMA_WARMUP_TIMEOUT` | `60` | Warmup timeout (seconds) |
| `OLLAMA_KEEP_ALIVE` | `15m` | Model residency between calls |
| `GUARDIAN_REACT` | unset | Set to `1` to enable ReAct tool use |
| `GUARDIAN_AUTOPLAY` | unset | Scenario id to auto-play on first rerun |

On a slow CPU bump `OLLAMA_TIMEOUT=300`; with a GPU drop it to `30`.

---

## Why Streamlit

This port replaces the original Flutter desktop prototype with a
Python-native Streamlit app for easier iteration:

- Zero build step — edit a `.py` file, save, refresh.
- Agents are plain Python dataclasses / classes; no Riverpod, no `go_router`.
- `streamlit-autorefresh` drives real-time scenario playback via
  periodic reruns (~400 ms).
- LLM calls are synchronous HTTP against Ollama; no platform channels
  or GGUF FFI needed.

The Flutter implementation is preserved under `legacy-flutter/app/`
and is fully functional via the `flutter-*` just targets.

---

## What's out of scope (Phase 2+)

- Real telephony / SMS listener (Android accessibility service, iOS
  call directory extension).
- Real bank SDK integration — the mock Bank page models the contract.
- Cross-bank intelligence sharing — federated blocklist + shared
  tactic tags.
- Live STT for the voice-call scenario — canned transcripts today.
- Secure trusted-contact delivery (SMS / push).

---

## License

Coursework prototype. Not for production use.
