# Política de Privacidad y Protección de Datos

**Sistema Integrado de Inventario y Ventas**  
**Versión del Documento:** 1.0  
**Fecha de Entrada en Vigor:** 28 de septiembre de 2026  
**Titular y Responsable del Desarrollo:** Kerwin Quintero  

---

## 1. Declaración Fundamental de Privacidad

La privacidad y confidencialidad de la información comercial de su empresa es una prioridad absoluta. El **Sistema Integrado de Inventario y Ventas** (en adelante, la "Aplicación" o el "Software") fue concebido bajo el principio de **Privacidad por Diseño (*Privacy by Design*)** y arquitectura **Completamente Local (*Offline-First*)**.

> **Compromiso de Privacidad:**  
> La Aplicación **NO recolecta, no transmite, no rastrea, no almacena en la nube ni vende** a terceros la información financiera, de inventario, de costos, de ventas ni los datos personales de sus clientes o proveedores.

---

## 2. Naturaleza y Almacenamiento de los Datos

1. **Almacenamiento Local Exclusivo:** Toda la información procesada por el Software se almacena de forma local en la máquina del usuario o en el servidor local donde se instale la aplicación, en el directorio del sistema operativo del usuario:
   ```text
   %APPDATA%\SistemaInventario\inventory.db
   (C:\Users\<Usuario>\AppData\Roaming\SistemaInventario\inventory.db)
   ```
2. **Sin Conexión Forzada a Servidores Externos:** El Software no requiere conexión a internet para su funcionamiento operativo regular. No se envían datos de uso, telemetría, estadísticas ocultas ni registros a servidores del Desarrollador.

---

## 3. Categorías de Datos Gestionados por el Usuario

Dentro de la operación autónoma del negocio, el Software permite registrar y procesar las siguientes categorías de datos:

1. **Datos de Productos e Inventario:**
   - Códigos de barras, referencias internas, nombres cortos y descripciones.
   - Cantidades de existencias físicas y niveles de stock mínimo de alerta.
   - Costos de adquisición en divisas (USD Efectivo / USD BCV) y precios de venta al público.
   - Departamentos, subdepartamentos y categorías comerciales.
2. **Datos de Clientes y Proveedores (Módulo Cartera):**
   - Nombres o razones sociales, cédulas de identidad o RIF.
   - Direcciones físicas de entrega o despacho.
   - Números de teléfono de contacto y direcciones de correo electrónico.
3. **Datos de Transacciones y Ventas:**
   - Notas de entrega, registros de pedidos, detalles de artículos despachados y fechas de emisión.
   - Historial de movimientos de inventario y auditoría de acciones.
4. **Datos de Usuarios y Credenciales:**
   - Nombres de usuario y roles asignados (`SuperAdmin`, `Administrador`, `Vendedor`, `Gerencia`).
   - Contraseñas almacenadas de forma unidireccional y salada mediante **PBKDF2-HMAC-SHA256**. Ninguna contraseña se almacena en texto plano.

---

## 4. Control de Acceso y Segregación de Roles

El Software incorpora mecanismos internos de seguridad para restringir el acceso a datos sensibles:

1. **Protección de Costos y Rentabilidad:** Los costos de compra de los artículos solo son accesibles y visibles para usuarios con roles de nivel administrativo o gerencial (`administrador`, `superadmin`, `gerencia`). Los roles operativos o de venta no tienen visibilidad de los márgenes ni costos de adquisición.
2. **Aislamiento de Cuentas:** La creación y modificación de usuarios con permisos elevados se encuentra restringida a la interfaz de administración.
3. **Persistencia Segura:** Las contraseñas se almacenan mediante hashes criptográficos no reversibles.

---

## 5. Asistencia Técnica y Acceso a la Información

1. **Soporte Técnico:** En caso de que el Cliente solicite soporte técnico, diagnóstico o asistencia personalizada al Desarrollador que requiera acceso remoto a la pantalla o a la base de datos:
   - Dicho acceso se realizará **única y exclusivamente con autorización previa y supervisión directa** del Cliente.
   - El Desarrollador mantendrá la más estricta reserva y secreto profesional respecto a cualquier información a la que tenga acceso incidental durante el proceso de soporte.
   - Finalizada la sesión técnica, el Desarrollador no conservará copia alguna de los datos comerciales del Cliente a menos que este lo solicite formalmente para propósitos de recuperación o migración autorizada.

---

## 6. Derechos del Usuario sobre sus Datos

Dado que todos los datos residen en la infraestructura local del Cliente, este tiene el control y dominio absoluto para:

- **Consultar y Modificar:** Acceder, editar y rectificar cualquier información en cualquier momento desde la interfaz del sistema.
- **Exportar y Portar:** Generar exportaciones a hojas de cálculo (Microsoft Excel) y respaldos completos de la base de datos a través de las opciones integradas en el módulo de *Gestión de Datos y Respaldos*.
- **Eliminar y Depurar:** Eliminar registros individuales, desincorporar productos o purgar por completo la base de datos eliminando el archivo local `inventory.db` cuando así lo decida.

---

## 7. Medidas de Seguridad Recomendadas para el Cliente

Dado que el entorno de ejecución está bajo el control exclusivo del Cliente, se recomienda seguir las siguientes buenas prácticas para proteger la confidencialidad de la información:

1. Mantener actualizado el sistema operativo y el software antivirus del equipo donde opera la aplicación.
2. Configurar cuentas de usuario protegidas con contraseña a nivel del sistema operativo Windows para evitar accesos no autorizados a la carpeta `%APPDATA%`.
3. Guardar las copias de seguridad de la base de datos en discos externos desconectables o ubicaciones seguras fuera del equipo principal.
4. No compartir las contraseñas de los usuarios administradores del sistema.

---

## 8. Modificaciones a la Presente Política

Esta Política de Privacidad podrá actualizarse para reflejar futuras mejoras técnicas o requerimientos legales. Cualquier cambio sustancial será documentado en las notas de la versión entregadas con los paquetes de instalación o actualizaciones del Software.

---

## 9. Contacto

Si tiene alguna consulta o inquietud acerca de esta Política de Privacidad o las prácticas de seguridad del Software, puede contactar al Desarrollador:

- **Responsable:** Kerwin Quintero
- **Repositorio Oficial:** [https://github.com/Kerwin2712/inventory_manager](https://github.com/Kerwin2712/inventory_manager)
