# Graph Report - inventory_manager  (2026-07-19)

## Corpus Check
- 12 files · ~852 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 34 nodes · 30 edges · 11 communities (9 shown, 2 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 1 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `d52ac556`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- LoginView
- BaseView
- Registro Diario de Desarrollo
- Sistema Integrado de Inventario y Ventas
- prompt_inicial.md
- README.md

## God Nodes (most connected - your core abstractions)
1. `LoginView` - 8 edges
2. `BaseView` - 7 edges
3. `main()` - 3 edges
4. `Sistema Integrado de Inventario y Ventas` - 3 edges
5. `Registro Diario de Desarrollo` - 3 edges
6. `Clase base que define la estructura visual común.` - 1 edges
7. `Vista de inicio de sesión.` - 1 edges
8. `inventory_manager` - 1 edges
9. `Arquitectura del Proyecto` - 1 edges
10. `Tecnologías Principales` - 1 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `LoginView`  [EXTRACTED]
  main.py → ui/views/login_view.py
- `LoginView` --uses--> `BaseView`  [INFERRED]
  ui/views/login_view.py → ui/views/base_view.py

## Import Cycles
- None detected.

## Communities (11 total, 2 thin omitted)

### Community 0 - "LoginView"
Cohesion: 0.25
Nodes (5): main(), Page, LoginView, Control, Vista de inicio de sesión.

### Community 1 - "BaseView"
Cohesion: 0.36
Nodes (3): BaseView, Control, Clase base que define la estructura visual común.

### Community 2 - "Registro Diario de Desarrollo"
Cohesion: 0.50
Nodes (3): [2026-07-19] Creación del Entry Point y Configuración de Ventana, [2026-07-19] Inicialización de la Arquitectura y Entorno Base, Registro Diario de Desarrollo

### Community 3 - "Sistema Integrado de Inventario y Ventas"
Cohesion: 0.50
Nodes (3): Arquitectura del Proyecto, Sistema Integrado de Inventario y Ventas, Tecnologías Principales

## Knowledge Gaps
- **6 isolated node(s):** `inventory_manager`, `Arquitectura del Proyecto`, `Tecnologías Principales`, `[2026-07-19] Inicialización de la Arquitectura y Entorno Base`, `[2026-07-19] Creación del Entry Point y Configuración de Ventana` (+1 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `LoginView` connect `LoginView` to `BaseView`?**
  _High betweenness centrality (0.154) - this node is a cross-community bridge._
- **Why does `BaseView` connect `BaseView` to `LoginView`?**
  _High betweenness centrality (0.121) - this node is a cross-community bridge._
- **What connects `Clase base que define la estructura visual común.`, `Vista de inicio de sesión.`, `inventory_manager` to the rest of the system?**
  _8 weakly-connected nodes found - possible documentation gaps or missing edges._