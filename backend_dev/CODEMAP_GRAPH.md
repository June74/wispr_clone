# Wispr Clone — Visual Code Map

Status: **planning only**. These diagrams are drawn from the "Contracts and dependency direction" tables in [CODEMAP.md](CODEMAP.md) §3 and the webview/clipboard/model-server rules in §4, §6 and §7. They do not describe working code.
Solid arrows mean "imports / calls". Dashed arrows are **injected callbacks** wired by `app.py`: the producer calls an interface and never imports the consumer, so they add no import edge.

## 1. Module dependency graph (layers, top → bottom)

```mermaid
flowchart TB
  subgraph L0["Composition root"]
    app["app.py / __main__.py"]
  end

  subgraph L1["Presentation (Windows GUI thread)"]
    bridge["ui.bridge"]
    events["ui.events (EventSink impl)"]
    windows["ui.windows / ui.overlay"]
    web["web/*.js (settings renderer)"]
    hud["HUD renderer (no bridge)"]
  end

  subgraph L2["Application (asyncio worker)"]
    api["application.api (router)"]
    cmds["application.commands.*"]
    modelsvc["application.model_service"]
  end

  subgraph L3["Orchestration"]
    run["pipeline.run_controller"]
    sm["pipeline.state_machine"]
    proto["pipeline.insertion_protocol"]
  end

  subgraph L4["Domain services and adapters"]
    hot["hotkeys"]
    audio["audio (+ device_lease)"]
    stt["stt"]
    clean["cleanup"]
    dict["dictionary"]
    hist["history"]
    ins["insertion (+ win32)"]
    reg["models.registry"]
    settings["settings"]
  end

  subgraph L5["Infrastructure"]
    storage["storage"]
  end

  app --> bridge & events & windows & api & modelsvc & run & hot & audio & stt & clean & dict & hist & ins & reg & settings & storage

  web -->|window.pywebview.api| bridge
  bridge --> api
  api --> cmds
  cmds --> run & audio & modelsvc & settings & dict & hist

  modelsvc --> reg & settings
  modelsvc -->|interface| stt
  modelsvc -->|interface| clean

  run --> sm & proto & audio & stt & clean & dict & hist
  proto --> hist & ins

  dict --> storage
  hist --> storage
  settings --> storage

  run -.->|EventSink| events
  hist -.->|EventSink| events
  modelsvc -.->|EventSink| events
  hist -.->|on_run_evicted| run
  hot -.->|on_start/stop/cancel| api
  events -.->|serialized events| web
  events -.->|state + levels only| hud
```

Shared leaves (`contracts/`, `config`, `util`) are left out of the arrows because any module may import them and they import nothing above themselves.

**Cycle check** (a topological sort of the solid edges, run as a planning check with Python's `graphlib`): the import graph is **acyclic**. Adding the dashed callbacks as runtime calls leaves exactly one loop: `run → history → on_run_evicted → run`. CODEMAP §3 breaks it by delivering every callback asynchronously on the worker loop, never re-entrantly.

## 2. Fan-in / fan-out summary

| Module | Fan-out (imports) | Fan-in (imported by) | Note |
|---|---|---|---|
| `contracts/*` | 0 | many, split across 4 small files | A type enters only when ≥2 packages outside its owner need it |
| `app.py` | ~all | 0 | Expected for a composition root |
| `application.api` | 1 (commands) | 1 (bridge) | Thin router only |
| `application.commands.*` | 1–2 each | 1 (api) | One handler per command group |
| `pipeline.run_controller` | 7 | 2 (commands, app) | Orchestrator; insertion sequence delegated to `insertion_protocol` |
| `pipeline.insertion_protocol` | 2 | 1 | Sole owner of claim → dispatch → outcome |
| `history` | 1 + sink/callback | 4 (commands, run, protocol, app) | Highest domain fan-in, each caller using a distinct part of its interface |
| `storage` | 0 | 3 (dictionary, history, settings) | Healthy |
| `audio` | 0 | 3 (commands, run, app) | Device lease enforces one owner |

## 3. Trust boundaries and sensitive data

```mermaid
flowchart LR
  subgraph Ext["Outside the app's control"]
    OtherApps["Other Windows apps<br/>(target app, clipboard readers)"]
    ClipHist["Clipboard history / cloud sync"]
    LocalProcs["Other local or WSL processes"]
    LAN["LAN"]
  end

  subgraph Renderer["WebView2 renderer: bundled files only, CSP, no navigation"]
    SettingsUI["Settings UI JS"]
    HudUI["HUD JS: no bridge"]
  end

  subgraph Core["Python core (trusted)"]
    Bridge["ui.bridge: validation gate"]
    Api["application.api"]
    Hook["hotkey hook: discards non-binding keys"]
    Ins["insertion: exclusion-flagged clipboard or Unicode input"]
    Data[("SQLite + WAVs: transcripts, audio,<br/>title hashes only")]
    Secrets[("Credential Manager: optional cloud keys")]
  end

  subgraph WSL["WSL model servers: bound to 127.0.0.1, no auth"]
    Vox["vLLM :8000"]
    Oll["Ollama :11434"]
  end

  SettingsUI --> Bridge --> Api --> Data
  Api -.->|events only| HudUI
  Hook -->|start/stop/cancel only| Api
  Api --> Ins --> OtherApps
  Ins -. "blocked by exclusion formats (verify in G4)" .-> ClipHist
  Api --> Vox & Oll
  LocalProcs -. "accepted local-only risk" .-> Vox & Oll
  LAN -. "blocked by loopback bind (verify in G2)" .-> Vox & Oll
  Api -. "cloud mode only" .-> Secrets
```
