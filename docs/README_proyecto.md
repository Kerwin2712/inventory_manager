# Sistema Integrado de Inventario y Ventas

Este proyecto está diseñado siguiendo los principios de la **Arquitectura Limpia (Clean Architecture)** y utilizando **Flet** como framework para la interfaz gráfica basada en Flutter.

## Arquitectura del Proyecto

El diseño del software separa estrictamente las responsabilidades en las siguientes capas y directorios:

- **`core/`**: Centraliza las configuraciones globales, constantes y los manejadores de conexión (como el ciclo de vida de la base de datos SQLite).
- **`services/`**: Contiene la lógica de negocio y las implementaciones de los casos de uso del sistema. Interactúa con SQLite mediante repositorios de datos dedicados, sirviendo de puente entre el almacenamiento de datos y la interfaz de usuario.
- **`ui/`**: Capa del frontend que maneja la experiencia visual y los eventos del usuario.
  - **`ui/views/`**: Alberga las clases de cada pantalla de la aplicación, las cuales heredan de una plantilla visual unificada (`BaseView`).
  - **`ui/components/`**: Contiene widgets y componentes visuales reutilizables a lo largo del sistema.
- **`docs/`**: Documentación del proyecto, bitácora de desarrollo y especificaciones técnicas.

## Tecnologías Principales
- **Python 3.x**: Lenguaje de programación principal.
- **Flet**: Framework de desarrollo de interfaces de usuario.
- **SQLite**: Motor de base de datos relacional ligero y autónomo.
- **Pandas / Openpyxl**: Herramientas para importación/exportación y generación de reportes en Excel.
