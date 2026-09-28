# Términos y Condiciones de Uso y Licencia de Software (EULA)

**Sistema Integrado de Inventario y Ventas**  
**Versión del Documento:** 1.0  
**Fecha de Entrada en Vigor:** 28 de septiembre de 2026  
**Titular y Desarrollador:** Kerwin Quintero (en adelante, el "Licenciante" o "Desarrollador")

---

## 1. Aceptación de los Términos

El presente documento constituye un contrato de licencia de uso de software (en adelante, el "Acuerdo" o "Términos y Condiciones") entre usted (persona natural o jurídica, en adelante el "Usuario" o "Cliente") y el Desarrollador. 

Al instalar, copiar, descargar, acceder o utilizar de cualquier manera el software **Sistema Integrado de Inventario y Ventas** (en adelante, la "Aplicación" o el "Software"), el Usuario declara haber leído, comprendido y aceptado en su totalidad las cláusulas y condiciones aquí estipuladas. Si el Usuario no está de acuerdo con estos términos, no deberá instalar ni hacer uso del Software.

---

## 2. Otorgamiento de Licencia de Uso

1. **Naturaleza de la Licencia:** El Desarrollador otorga al Cliente una licencia de uso personal, comercial interno, no exclusiva, intransferible y revocable para ejecutar el Software en los equipos de cómputo acordados o autorizados.
2. **Alcance:** La adquisición de una copia o derecho de uso del Software **no transfiere la propiedad intelectual ni los derechos de autor** sobre el mismo; únicamente otorga el derecho a utilizar la aplicación conforme a las funcionalidades contratadas.
3. **Restricciones Prohibidas:** Queda expresamente prohibido para el Usuario, sus empleados o terceros:
   - Modificar, descompilar, realizar ingeniería inversa, desensamblar o intentar derivar el código fuente del Software.
   - Vender, revender, sublicenciar, alquilar, arrendar, distribuir, ceder o comercializar copias del Software o partes de este a terceras partes.
   - Remover, alterar u ocultar cualquier indicación de derechos de autor, marcas comerciales o avisos de propiedad intelectual presentes en el Software o su documentación.
   - Utilizar el Software para fines ilícitos o en contravención con las leyes vigentes del país de operación.

---

## 3. Arquitectura y Almacenamiento Local (Offline-First)

1. **Operación Local:** El Software ha sido diseñado bajo una arquitectura de escritorio local (*offline-first*). Todas las bases de datos transaccionales, catálogos de inventario, costos, ventas y registros de clientes residen en el equipo informático del Cliente (`%APPDATA%\SistemaInventario\inventory.db` en sistemas Microsoft Windows).
2. **Propiedad y Custodia de los Datos:** Todos los datos comerciales, inventarios, precios, listas de clientes, transacciones de venta e información financiera introducida en el Software son propiedad única y exclusiva del Cliente. El Desarrollador **no tiene acceso, no almacena en servidores externos ni comercializa** dicha información.

---

## 4. Respaldos y Responsabilidad sobre la Información

1. **Responsabilidad del Cliente:** La custodia, integridad física y lógica, y disponibilidad de la información almacenada en el Software recae de manera exclusiva en el Cliente.
2. **Copias de Seguridad (Backups):** El Software incluye herramientas integradas en el módulo de *Gestión de Datos y Respaldos* para la exportación y generación de copias de seguridad de la base de datos. Es obligación inexcusable del Cliente:
   - Generar respaldos periódicos en dispositivos de almacenamiento externos, discos secundarios o servicios de almacenamiento seguro.
   - Proteger los archivos de respaldo contra accesos no autorizados, fallos de disco o infecciones de malware/ransomware.
3. **Exención por Pérdida de Datos:** El Desarrollador no se hace responsable bajo ninguna circunstancia por la pérdida total o parcial de información derivada de fallas de hardware, cortes de energía eléctrica, virus o malware en el equipo del Cliente, formateo del sistema operativo o negligencia en la ejecución de copias de seguridad.

---

## 5. Control de Acceso y Credenciales

1. **Seguridad Criptográfica:** El Software implementa almacenamiento protegido de contraseñas mediante derivación de claves con algoritmos de hashing seguro (PBKDF2-HMAC-SHA256).
2. **Responsabilidad de Claves:** El Cliente es responsable de la confidencialidad y adecuada gestión de las credenciales de los distintos roles del sistema (SuperAdmin, Administrador, Vendedor, Gerencia).
3. **Clave de Recuperación del Sistema:** Al inicializarse el sistema se genera una clave inicial/maestra de instalación para el usuario administrador. La custodia segura y cambio oportuno de dicha credencial es de exclusiva responsabilidad del administrador del establecimiento comercial.

---

## 6. Garantía Limitada y Exención de Responsabilidad

1. **Suministro "Tal Cual" (*As Is*):** El Software se proporciona "tal cual" y "según disponibilidad", sin garantías expresas o implícitas de ningún tipo, incluyendo pero no limitándose a garantías de comerciabilidad, adecuación para un propósito particular o ausencia de errores menores.
2. **Limitación de Responsabilidad:** En ningún caso el Desarrollador será responsable frente al Cliente o terceros por daños directos, indirectos, incidentales, consecuentes o punitivos, incluyendo lucro cesante, interrupción de actividades comerciales, penalizaciones fiscales, discrepancias de inventario o fallas operativas derivadas del uso o imposibilidad de uso del Software.
3. **Responsabilidad Máxima:** En caso de que una autoridad judicial competente determine alguna responsabilidad por parte del Desarrollador, la indemnización total máxima estará estrictamente limitada al monto efectivamente pagado por el Cliente al Desarrollador por la licencia de uso del Software durante los últimos seis (6) meses.

---

## 7. Actualizaciones y Soporte Técnico

1. **Actualizaciones:** El Desarrollador podrá lanzar periódicamente actualizaciones, parches de seguridad, optimizaciones de rendimiento y mejoras funcionales a través de nuevos instaladores. 
2. **Proceso de Actualización:** El instalador del Software está configurado para actualizar los componentes de la aplicación sin alterar ni sobrescribir la base de datos local del Cliente. No obstante, se recomienda encarecidamente realizar una copia de seguridad previa antes de aplicar cualquier actualización.
3. **Soporte Técnico:** La prestación de asistencia técnica, capacitaciones, soporte correctivo o desarrollos a medida se regirá por los acuerdos de servicio individuales pactados entre el Desarrollador y el Cliente.

---

## 8. Modificaciones a los Términos

El Desarrollador se reserva el derecho de modificar o actualizar estos Términos y Condiciones para adaptarlos a novedades normativas, mejoras técnicas o cambios funcionales del Software. Las nuevas versiones estarán disponibles en la documentación del producto y entrarán en vigor a partir de su publicación o entrega con las actualizaciones correspondientes.

---

## 9. Contacto y Titularidad

Para consultas, dudas relativas a esta licencia o solicitud de soporte técnico oficial, comuníquese a través de los canales autorizados del Desarrollador:

- **Titular:** Kerwin Quintero
- **Repositorio Oficial:** [https://github.com/Kerwin2712/inventory_manager](https://github.com/Kerwin2712/inventory_manager)
