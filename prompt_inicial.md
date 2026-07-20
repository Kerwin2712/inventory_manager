# Reglas de Flujo de Trabajo del Agente

REGLA 1: Al iniciar cada conversación, debes leer obligatoriamente `docs/README_proyecto.md` y el archivo correspondiente al mes actual en `docs/bitacora/` (ejemplo: `julio_2026.md`) para recuperar el contexto.

REGLA 2: Cada vez que realices un cambio, debes registrarlo cronológicamente en el archivo del mes actual dentro de `docs/bitacora/`.

REGLA 3: Los commits que generes deben ser estrictamente atómicos (un commit por funcionalidad o arreglo específico).

REGLA 4: BAJO NINGUNA CIRCUNSTANCIA debes ejecutar el comando `git push`.

REGLA 5: Se utilizará la herramienta Graphify para mantener el grafo del proyecto actualizado en cada fase importante (`graphify update .`).
