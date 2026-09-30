# Open-Build Architecture Brief: The Local-First, Agentic Engineering IDE

## 1. Executive Summary

**Open-Build** is a specialized, local-first desktop IDE for physical engineering (machinery, solar grids, structural systems, and custom industrial skids). Built as a fork of the VS Code open-source architecture, it replaces code-editing workflows with an **autonomous engineering runtime**.

Instead of writing software source code, an AI agent operates within the user's local directory to write parametric Python models, run mathematical and physical verification tools, compile exact 3D geometry locally, and output production-ready Bills of Materials (BOMs) and STEP files.

---

## 2. Core Architectural Principles

* **Local-First & Air-Gapped:** All project files, CAD scripts, and proprietary designs remain 100% on the user's local machine or internal network. No secret blueprints are ever forced into public cloud infrastructure.
* **Bring Your Own Key (BYOK):** The core IDE, workspace management, and local compilation tools are fully open-source and free. Users plug in their own API keys (Anthropic, OpenAI, Google, or local open-weights via Ollama) to power the underlying AI reasoning engine directly.
* **Code-Native CAD (No Heavy Bloat):** Bypasses legacy, stateful GUI monoliths like FreeCAD. Instead, it utilizes programmatic, code-first Python math kernels (**`build123d` / OpenCASCADE**) to execute deterministic, reliable geometric generation.

---

## 3. High-Level System Architecture

```text
+-------------------------------------------------------------------+
|                        Open-Build IDE Fork                        |
|                     (VS Code Open-Source Core)                    |
|                                                                   |
|  +---------------------------+       +-------------------------+  |
|  |     Agent Chat Panel      | <---> |    File Tree Workspace  |  |
|  |   (Natural Language I/O)  |       |   (Config, Code, BOM)   |  |
|  +---------------------------+       +-------------------------+  |
|                |                                  |               |
|                v                                  v               |
|  +---------------------------------------------------------+      |
|  |                   AI Reasoning Loop                     |      |
|  |        (BYOK: Claude / OpenAI / Gemini / Ollama)        |      |
|  +---------------------------------------------------------+      |
|                                |                                  |
|          +---------------------+---------------------+            |
|          | (Tool Calls / MCP)                        |            |
|          v                                           v            |
|  +-----------------------------+     +--------------------------+ |
|  |  Parametric Geometry Engine |     |  Physics & Math Solvers  | |
|  |  (build123d / OpenCASCADE)  |     |  (Fluid/Electrical Check)| |
|  +-----------------------------+     +--------------------------+ |
|          |                                           |            |
|          +---------------------+---------------------+            |
|                                |                                  |
|                                v                                  |
|  +---------------------------------------------------------+      |
|  |                Split-Pane Visual Feedback               |      |
|  |    * Three.js Interactive 3D Webview Canvas (.step/.gltf)|     |
|  |    * Real-Time BOM & Component Catalog Table            |      |
|  +---------------------------------------------------------+      |
+-------------------------------------------------------------------+
```

## 4. Key Functional Layers

### A. The Project Workspace (File-System Manifest)

Projects are structured folders containing clear engineering artifacts rather than software source files:

* `system.yaml`: Top-level constraints (target voltage, pressure limits, max spatial footprint).
* `geometry/`: Parametric Python scripts defining the physical assets.
* `catalog/`: Approved internal component catalogs, part numbers, and vendor rules.
* `bom.json`: Automatically generated Bill of Materials.

### B. The AI Agent & BYOK Gateway

The built-in assistant parses plain-text requirements or voice notes from non-developer users (sales engineers, shop floor managers).

**Zero Vendor Lock-in / Cost Control:** Users configure their own LLM endpoint credentials (API keys) in settings, ensuring they pay providers directly for exact token consumption without hidden platform markups, or run completely free and private via local models.

### C. The Deterministic Tool-Calling Runtime

The agent doesn't "guess" dimensions; it invokes discrete background tools:

* **Geometry Compilation:** Executes local Python scripts using `build123d` to build exact B-rep boundary representations via OpenCASCADE.
* **Constraint & Validation Check:** Runs automated mathematical checks (e.g., fluid friction, structural load distribution, voltage drop).
* **Self-Correction Loop:** If a script throws a geometric or physical error, the traceback feeds directly back into the agent's context window to auto-correct the code.

### D. The Split-Pane Presentation Layer

* **Code View:** Inspect and tweak the generated parametric Python logic.
* **3D Webview:** Instantly hot-reloads and renders `.step` or `.gltf` meshes locally via Three.js.
* **BOM & Compliance Table:** Live-updates parts counts, supplier part numbers, and safety flag warnings.
