"""Generador de Archivo por Nueva Mercancía (Nueva Función 6 — PDF 17/10/2026).

POR QUÉ EXISTE ESTE MÓDULO
Cuando llega mercancía nueva la recibe un empleado, no el Administrador, y un
empleado NO tiene permiso para modificar el stock (solo puede descontarlo
vendiendo). Este módulo le da una salida: armar el pedido en un borrador y
exportarlo como Excel para entregárselo al Administrador, que lo supervisa y
recién entonces lo ingresa por Carga Masiva de Datos.

De ahí la decisión central: **el flujo del pedido NO escribe NADA en la base de
datos**. No crea productos, no mueve existencias, no toca precios ni costos. Lo
único que produce es un archivo fuera del sistema. Por eso está disponible para
TODOS los roles (vendedores incluidos) sin romper la restricción de permisos:
el empleado describe lo que llegó, no altera el inventario. Cualquier cambio
futuro que haga que este módulo escriba en la base rompe esa garantía y con
ella la razón por la que es accesible a todo el mundo.

COMPATIBILIDAD DEL FORMATO (requisito duro)
El archivo generado tiene que poder volver a entrar por la Carga Masiva de
Datos existente sin que el Administrador tenga que mapear columnas a mano. Para
que el formato no se bifurque en dos definiciones que luego se desincronicen,
los encabezados y el nombre de la hoja NO se escriben como literales acá: se
derivan de lo que `services.importacion_service` declara (`CAMPOS_PRODUCTO_MAPEO`
y sus alias de encabezado). Si alguien renombra una columna allá, acá cambia
sola — y el test del círculo cerrado (generar → importar) lo verifica.

AISLAMIENTO POR SESIÓN
El borrador vive en memoria, indexado por `session_id`, con el mismo criterio
que `services.cart_manager` usa para los carritos: la aplicación Flet atiende
varias sesiones en el mismo proceso, y un estado en variables globales se
pisaría entre dos usuarios armando pedidos al mismo tiempo. No se crea ninguna
tabla nueva: el esquema de la base no se toca (ver arriba — este módulo no
escribe en la base).
"""
from datetime import datetime

import pandas as pd

from core.models import normalizar_costo
from services.busqueda_service import CRITERIO_POR_DEFECTO, buscar_productos
from services.importacion_service import (
    CAMPOS_PRODUCTO_MAPEO,
    _ALIAS_CAMPO_PRODUCTO,
    limpiar_clave,
)
from services.inventario_service import obtener_producto

# ═════════════════════════════════════════════════════════════════════════════
# FORMATO DEL ARCHIVO (derivado de la Carga Masiva, nunca duplicado)
# ═════════════════════════════════════════════════════════════════════════════

# `procesar_importacion_excel` busca la hoja de productos por nombre
# ('Productos'/'Producto'/'Inventario'); se usa el primero de esa lista para que
# la detección sea directa y no dependa del fallback de "hoja única".
NOMBRE_HOJA_PEDIDO = "Productos"

# Hoja informativa con los datos que el PDF exige UNA sola vez (Proveedor y
# Fecha de Recepción) más los totales del pedido. La Carga Masiva la ignora:
# solo lee las hojas llamadas Productos / Clientes / Proveedores.
NOMBRE_HOJA_RESUMEN = "Resumen del Pedido"


def _encabezado_compatible(campo: str, etiqueta: str) -> str:
    """Encabezado de columna que el lector de la importación va a reconocer
    para `campo`.

    La etiqueta que el asistente de mapeo muestra en pantalla no siempre es un
    alias válido para el lector heurístico (el caso real: el asistente rotula
    'Proveedor (nombre)', pero la importación sin mapeo manual solo reconoce
    'Proveedor'). Así que se usa la etiqueta cuando normaliza a un alias
    conocido y, si no, el primer alias declarado — que por definición sí lo es.
    """
    alias = _ALIAS_CAMPO_PRODUCTO.get(campo, ())
    if limpiar_clave(etiqueta) in alias:
        return etiqueta
    return alias[0].title() if alias else etiqueta


# campo del pedido -> encabezado en el Excel, en el orden en que la importación
# declara sus campos (así la hoja se lee igual que la plantilla de Carga Masiva).
ENCABEZADO_POR_CAMPO: dict[str, str] = {
    campo: _encabezado_compatible(campo, etiqueta)
    for campo, etiqueta, _obligatorio in CAMPOS_PRODUCTO_MAPEO
}

# Columnas informativas para que el Administrador supervise el pedido. La
# importación las ignora hoy (ninguna normaliza a un alias suyo), pero son
# datos que el PDF pide explícitamente y que se perderían si no viajaran en el
# archivo. Van al final para no alterar el orden de la plantilla compatible.
ENCABEZADO_SUB_DEPARTAMENTO = "Sub-Departamento"
ENCABEZADO_COSTO_EFECTIVO = "Costo USD (Efectivo)"
ENCABEZADO_COSTO_BCV = "Costo USD (BCV)"
ENCABEZADO_FECHA_RECEPCION = "Fecha de Recepción"

ENCABEZADOS_INFORMATIVOS: tuple[str, ...] = (
    ENCABEZADO_SUB_DEPARTAMENTO,
    ENCABEZADO_COSTO_EFECTIVO,
    ENCABEZADO_COSTO_BCV,
    ENCABEZADO_FECHA_RECEPCION,
)

ENCABEZADOS_PEDIDO: tuple[str, ...] = tuple(ENCABEZADO_POR_CAMPO.values()) + ENCABEZADOS_INFORMATIVOS

# Campos que el usuario completa por renglón: lo único que se le pide cuando el
# item ya está en el banco de datos (el resto lo trae el sistema). El PDF los
# enumera como "Costo $/BCV, Precio Venta $/BCV, Marca, Cantidad".
CAMPOS_EDITABLES_RENGLON: tuple[str, ...] = (
    "costo_usd_efectivo",
    "costo_usd_bcv",
    "precio_usd_efectivo",
    "precio_usd_bcv",
    "marca",
    "cantidad",
)

# Etiquetas visibles de los montos, usadas también en los mensajes de error.
ETIQUETA_MONTO = {
    "costo_usd_efectivo": "Costo USD Efectivo",
    "costo_usd_bcv": "Costo USD BCV",
    "precio_usd_efectivo": "Precio Venta USD Efectivo",
    "precio_usd_bcv": "Precio Venta USD BCV",
}

FORMATO_FECHA_RECEPCION = "DD/MM/AAAA"
_FORMATO_FECHA_STRPTIME = "%d/%m/%Y"


# ═════════════════════════════════════════════════════════════════════════════
# BORRADOR EN MEMORIA, AISLADO POR SESIÓN
# ═════════════════════════════════════════════════════════════════════════════

# session_id -> {"renglones": [...]}
# Mismo criterio que `cart_manager._sesiones`: el estado NUNCA vive en globales
# planas porque dos usuarios conectados al mismo proceso Flet se pisarían el
# pedido mutuamente.
_sesiones: dict[str, dict] = {}


def _estado_sesion(session_id: str) -> dict:
    """Devuelve (creando si hace falta) el borrador aislado de una sesión."""
    estado = _sesiones.get(session_id)
    if estado is None:
        estado = {"renglones": []}
        _sesiones[session_id] = estado
    return estado


def limpiar_sesion(session_id: str) -> None:
    """Libera el borrador de una sesión (al desconectarse el navegador) para no
    acumular memoria indefinidamente en el servidor."""
    _sesiones.pop(session_id, None)


def obtener_pedido(session_id: str) -> dict:
    """Borrador vivo de la sesión: `{"renglones": [...]}`."""
    return _estado_sesion(session_id)


def obtener_renglones(session_id: str) -> list[dict]:
    """Renglones del pedido en borrador de la sesión, en orden de agregado."""
    return _estado_sesion(session_id)["renglones"]


def vaciar_pedido(session_id: str) -> None:
    """Descarta todos los renglones del borrador de la sesión."""
    _estado_sesion(session_id)["renglones"] = []


# ═════════════════════════════════════════════════════════════════════════════
# VALIDACIONES
# ═════════════════════════════════════════════════════════════════════════════

def normalizar_cantidad(valor) -> float:
    """Cantidad recibida de mercancía: número > 0.

    Un renglón con cantidad 0 no es mercancía que llegó, es ruido en el pedido;
    y una cantidad negativa importada como existencia dejaría stock negativo en
    el inventario del Administrador.
    """
    if isinstance(valor, bool) or valor is None or (isinstance(valor, str) and not valor.strip()):
        raise ValueError("ERR_PEDIDO_CANT: La cantidad es obligatoria y debe ser mayor a cero.")
    crudo = valor.strip().replace(",", ".") if isinstance(valor, str) else valor
    try:
        numero = float(crudo)
    except (TypeError, ValueError):
        raise ValueError("ERR_PEDIDO_CANT: La cantidad debe ser un número válido.")
    if numero <= 0:
        raise ValueError("ERR_PEDIDO_CANT: La cantidad debe ser mayor a cero.")
    return numero


def normalizar_monto(valor, campo: str) -> float:
    """Costo o precio de venta de un renglón: numérico y no negativo.

    Delega en `core.models.normalizar_costo` a propósito, para que "qué es un
    monto válido" (coma o punto decimal, vacío = sin dato, nunca negativo) tenga
    una sola definición compartida con el formulario de Inventario. El vacío se
    colapsa a 0.0 porque en el Excel la celda tiene que llevar un número: la
    importación lee ese 0 como "sin precio cargado" y el Administrador lo
    completa al supervisar.
    """
    etiqueta = ETIQUETA_MONTO.get(campo, campo)
    try:
        numero = normalizar_costo(valor, etiqueta)
    except ValueError as ex:
        # Se re-etiqueta con el prefijo del pedido: el mensaje de Inventario
        # habla de "costos del inventario" y acá no se está tocando ninguno.
        raise ValueError(f"ERR_PEDIDO_MONTO: {str(ex).split(': ', 1)[-1]}")
    return 0.0 if numero is None else numero


def validar_fecha_recepcion(texto: str) -> str:
    """Valida la Fecha de Recepción en `DD/MM/AAAA` y la devuelve normalizada.

    Se exige el formato que usa el usuario venezolano (día primero) y se valida
    con `strptime` para rechazar fechas inexistentes como 31/02/2026, que un
    simple split por '/' aceptaría.
    """
    crudo = (texto or "").strip()
    if not crudo:
        raise ValueError("ERR_PEDIDO_FECHA: La Fecha de Recepción es obligatoria para cerrar el pedido.")
    try:
        fecha = datetime.strptime(crudo, _FORMATO_FECHA_STRPTIME)
    except ValueError:
        raise ValueError(
            f"ERR_PEDIDO_FECHA: La Fecha de Recepción '{crudo}' no es una fecha "
            f"válida en formato {FORMATO_FECHA_RECEPCION}."
        )
    return fecha.strftime(_FORMATO_FECHA_STRPTIME)


def validar_proveedor(nombre: str) -> str:
    """Valida el Proveedor del pedido (se pide una sola vez, al cerrar).

    Solo se valida que venga un nombre: la vista lo elige de los proveedores ya
    registrados (`cartera_service.listar_proveedores`), y si el Administrador
    importa un nombre que no existe, la Carga Masiva ya tiene su propio
    asistente para registrarlo antes de seguir.
    """
    crudo = (nombre or "").strip()
    if not crudo:
        raise ValueError("ERR_PEDIDO_PROV: El Proveedor es obligatorio para cerrar el pedido.")
    return crudo


# ═════════════════════════════════════════════════════════════════════════════
# ARMADO DEL PEDIDO
# ═════════════════════════════════════════════════════════════════════════════

def buscar_items_para_pedido(termino: str, criterio: str = CRITERIO_POR_DEFECTO, limite: int = 25) -> list[dict]:
    """Busca en el banco de datos de items registrados (código, descripción,
    referencia, …) para que el usuario ubique la pieza que llegó sin reescribir
    todas sus casillas.

    Delega en `busqueda_service.buscar_productos`, que nunca selecciona las
    columnas de costo: el vendedor que arma el pedido ve la ficha del producto
    pero no los costos del negocio, y los costos que escribe son los de ESTA
    entrada de mercancía, no los almacenados.
    """
    return buscar_productos(termino, criterio=criterio, limite=limite)


def _renglon_existente(renglones: list[dict], codigo: str) -> dict | None:
    return next((r for r in renglones if r["codigo"].strip().upper() == codigo.strip().upper()), None)


def _normalizar_valores_renglon(
    cantidad, costo_usd_efectivo, costo_usd_bcv, precio_usd_efectivo, precio_usd_bcv,
) -> dict:
    """Valida de una sola pasada las casillas que el usuario completa."""
    return {
        "cantidad": normalizar_cantidad(cantidad),
        "costo_usd_efectivo": normalizar_monto(costo_usd_efectivo, "costo_usd_efectivo"),
        "costo_usd_bcv": normalizar_monto(costo_usd_bcv, "costo_usd_bcv"),
        "precio_usd_efectivo": normalizar_monto(precio_usd_efectivo, "precio_usd_efectivo"),
        "precio_usd_bcv": normalizar_monto(precio_usd_bcv, "precio_usd_bcv"),
    }


def _acumular_o_agregar(renglones: list[dict], nuevo: dict) -> dict:
    """Inserta el renglón, o acumula la cantidad si su código ya está.

    El Excel debe tener UNA fila por código: la importación hace
    `INSERT OR REPLACE`, así que dos filas del mismo producto no suman
    existencias — la segunda sobrescribe a la primera y la cantidad de la
    primera se perdería en silencio. Al acumular acá, el archivo ya sale con la
    cantidad total correcta. Los demás valores (marca, costos, precios) se
    actualizan con los últimos ingresados: son los de la entrada que el usuario
    está registrando ahora.
    """
    existente = _renglon_existente(renglones, nuevo["codigo"])
    if existente is None:
        renglones.append(nuevo)
        return nuevo

    cantidad_total = existente["cantidad"] + nuevo["cantidad"]
    existente.update(nuevo)
    existente["cantidad"] = cantidad_total
    return existente


def agregar_renglon_desde_banco(
    session_id: str,
    codigo: str,
    cantidad,
    costo_usd_efectivo=None,
    costo_usd_bcv=None,
    precio_usd_efectivo=None,
    precio_usd_bcv=None,
    marca: str | None = None,
) -> dict:
    """Agrega al pedido un item YA REGISTRADO, trayendo del banco de datos todo
    lo que no hace falta volver a escribir (código, referencia, departamento,
    sub-departamento, descripciones y código de barras).

    `marca` llega pre-rellenada con la del producto registrado y es editable: el
    PDF la pide como casilla a llenar porque una misma pieza puede llegar de
    otra marca. Pasar `None` conserva la marca registrada.

    Se consulta con `rol_usuario=None` (fail-closed) porque este flujo no
    necesita —ni debe ver— los costos almacenados del producto.
    """
    producto = obtener_producto((codigo or "").strip(), rol_usuario=None)
    if not producto:
        raise ValueError(
            f"ERR_PEDIDO_ITEM: No existe un producto registrado con el código "
            f"'{codigo}'. Use el alta manual si la mercancía es nueva."
        )

    valores = _normalizar_valores_renglon(
        cantidad, costo_usd_efectivo, costo_usd_bcv, precio_usd_efectivo, precio_usd_bcv
    )
    marca_final = producto.get("marca") or "" if marca is None else str(marca).strip()

    renglon = {
        "codigo": str(producto["codigo"]).strip(),
        "referencia": producto.get("referencia") or "",
        "departamento": producto.get("departamento") or "",
        "sub_departamento": producto.get("sub_departamento") or "",
        "descripcion_general": producto.get("descripcion_general") or "",
        "nombre_referencia_corto": producto.get("nombre_referencia_corto") or "",
        "codigo_barras": producto.get("codigo_barras") or "",
        "marca": marca_final,
        "origen": "banco",
        **valores,
    }
    return _acumular_o_agregar(obtener_renglones(session_id), renglon)


def agregar_renglon_manual(
    session_id: str,
    codigo: str,
    descripcion_general: str,
    cantidad,
    costo_usd_efectivo=None,
    costo_usd_bcv=None,
    precio_usd_efectivo=None,
    precio_usd_bcv=None,
    marca: str = "",
    referencia: str = "",
    departamento: str = "",
    sub_departamento: str = "",
    codigo_barras: str = "",
    nombre_referencia_corto: str = "",
) -> dict:
    """Alta de un renglón para mercancía que NO está en el banco de datos.

    El PDF solo contempla items ya registrados, pero un pedido real trae piezas
    nuevas y obligar a registrarlas antes rompería el punto del módulo (el
    empleado no puede crear productos). Se piden los campos que la importación
    exige para poder crear la ficha: `codigo` (su único obligatorio real) y una
    `descripcion_general` para que el Administrador sepa qué es la pieza. El
    resto queda con los mismos valores por defecto que aplica la Carga Masiva
    (departamento 'GENERAL', nombre corto derivado del código/descripción).

    Queda marcado con `origen='manual'` para que la vista y el Administrador
    puedan distinguir estos renglones de los que vinieron del banco de datos.
    """
    codigo_limpio = (codigo or "").strip()
    descripcion = (descripcion_general or "").strip()
    if not codigo_limpio:
        raise ValueError("ERR_PEDIDO_MANUAL: El Código es obligatorio para dar de alta mercancía nueva.")
    if not descripcion:
        raise ValueError("ERR_PEDIDO_MANUAL: La Descripción General es obligatoria para dar de alta mercancía nueva.")

    valores = _normalizar_valores_renglon(
        cantidad, costo_usd_efectivo, costo_usd_bcv, precio_usd_efectivo, precio_usd_bcv
    )
    nombre_corto = (nombre_referencia_corto or "").strip() or descripcion[:30].strip()

    renglon = {
        "codigo": codigo_limpio,
        "referencia": (referencia or "").strip(),
        # 'GENERAL' es el mismo relleno que usa la importación cuando la
        # columna viene vacía; se escribe acá para que el archivo sea explícito.
        "departamento": (departamento or "").strip() or "GENERAL",
        "sub_departamento": (sub_departamento or "").strip(),
        "descripcion_general": descripcion,
        "nombre_referencia_corto": nombre_corto,
        "codigo_barras": (codigo_barras or "").strip(),
        "marca": (marca or "").strip(),
        "origen": "manual",
        **valores,
    }
    return _acumular_o_agregar(obtener_renglones(session_id), renglon)


def editar_renglon(session_id: str, indice: int, **cambios) -> dict:
    """Modifica las casillas editables de un renglón del borrador.

    Solo se aceptan los campos de `CAMPOS_EDITABLES_RENGLON` (los que el PDF
    pide por renglón): los datos traídos del banco de datos no se editan acá
    para que el archivo siga describiendo al producto registrado tal como está.
    """
    renglones = obtener_renglones(session_id)
    if not (0 <= indice < len(renglones)):
        raise ValueError(f"ERR_PEDIDO_INDICE: El pedido no tiene un renglón en la posición {indice}.")

    desconocidos = [c for c in cambios if c not in CAMPOS_EDITABLES_RENGLON]
    if desconocidos:
        raise ValueError(
            "ERR_PEDIDO_CAMPO: Solo se pueden editar "
            f"{', '.join(CAMPOS_EDITABLES_RENGLON)}; recibido: {', '.join(desconocidos)}."
        )

    renglon = renglones[indice]
    normalizados: dict = {}
    for campo, valor in cambios.items():
        if campo == "cantidad":
            normalizados["cantidad"] = normalizar_cantidad(valor)
        elif campo == "marca":
            normalizados["marca"] = (valor or "").strip()
        else:
            normalizados[campo] = normalizar_monto(valor, campo)

    renglon.update(normalizados)
    return renglon


def quitar_renglon(session_id: str, indice: int) -> bool:
    """Quita un renglón del borrador por su posición. `False` si no existía."""
    renglones = obtener_renglones(session_id)
    if not (0 <= indice < len(renglones)):
        return False
    renglones.pop(indice)
    return True


def total_unidades(session_id: str) -> float:
    """Unidades totales del pedido (para el resumen que ve el usuario)."""
    return sum(r["cantidad"] for r in obtener_renglones(session_id))


def total_costo_efectivo(session_id: str) -> float:
    """Costo USD Efectivo total del pedido: cantidad × costo, por renglón."""
    return round(sum(r["cantidad"] * r["costo_usd_efectivo"] for r in obtener_renglones(session_id)), 2)


# ═════════════════════════════════════════════════════════════════════════════
# GENERACIÓN DEL ARCHIVO EXCEL
# ═════════════════════════════════════════════════════════════════════════════

def _fila_excel(renglon: dict, proveedor: str, fecha_recepcion: str) -> dict:
    """Traduce un renglón del borrador a una fila con los encabezados que la
    Carga Masiva reconoce. Los montos se escriben como NÚMEROS (no como texto
    con '$'): el lector de la importación interpreta la celda con `float`, y un
    texto formateado lo obligaría a adivinar separadores."""
    return {
        ENCABEZADO_POR_CAMPO["codigo"]: renglon["codigo"],
        ENCABEZADO_POR_CAMPO["referencia"]: renglon["referencia"],
        ENCABEZADO_POR_CAMPO["departamento"]: renglon["departamento"],
        ENCABEZADO_POR_CAMPO["descripcion_general"]: renglon["descripcion_general"],
        ENCABEZADO_POR_CAMPO["marca"]: renglon["marca"],
        ENCABEZADO_POR_CAMPO["precio_dolares"]: renglon["precio_usd_efectivo"],
        ENCABEZADO_POR_CAMPO["precio_bcv"]: renglon["precio_usd_bcv"],
        # El Proveedor y la Fecha de Recepción se piden UNA sola vez al cerrar
        # el pedido, pero se repiten en cada fila porque la Carga Masiva resuelve
        # el proveedor fila por fila (busca su `empresa` para enlazar el ID).
        ENCABEZADO_POR_CAMPO["proveedor"]: proveedor,
        # La cantidad recibida viaja en la columna Existencia: es la única que
        # la importación escribe sobre el stock. Ojo (y es la razón por la que
        # este archivo lo supervisa un Administrador): la importación hace
        # INSERT OR REPLACE, así que FIJA la existencia en este número en vez de
        # sumarla a la que el producto ya tenía.
        ENCABEZADO_POR_CAMPO["existencia"]: renglon["cantidad"],
        ENCABEZADO_POR_CAMPO["codigo_barras"]: renglon["codigo_barras"],
        ENCABEZADO_POR_CAMPO["nombre_referencia_corto"]: renglon["nombre_referencia_corto"],
        ENCABEZADO_SUB_DEPARTAMENTO: renglon["sub_departamento"],
        ENCABEZADO_COSTO_EFECTIVO: renglon["costo_usd_efectivo"],
        ENCABEZADO_COSTO_BCV: renglon["costo_usd_bcv"],
        ENCABEZADO_FECHA_RECEPCION: fecha_recepcion,
    }


def construir_filas_pedido(session_id: str, proveedor: str, fecha_recepcion: str) -> list[dict]:
    """Filas del Excel (encabezado → valor) del pedido de la sesión, ya
    validadas. Separado de la escritura del archivo para poder verificar el
    contenido sin tocar el disco."""
    renglones = obtener_renglones(session_id)
    if not renglones:
        raise ValueError("ERR_PEDIDO_VACIO: No se puede generar el archivo de un pedido sin renglones.")
    proveedor = validar_proveedor(proveedor)
    fecha_recepcion = validar_fecha_recepcion(fecha_recepcion)
    return [_fila_excel(r, proveedor, fecha_recepcion) for r in renglones]


def generar_archivo_pedido(session_id: str, ruta_destino: str, proveedor: str, fecha_recepcion: str) -> dict:
    """Escribe el Excel del pedido en `ruta_destino` y devuelve su resumen.

    El libro sale con la hoja de productos en el formato de la Carga Masiva (así
    el Administrador lo ingresa sin mapear columnas) más una hoja de resumen con
    el Proveedor, la Fecha de Recepción y los totales, para que pueda
    supervisarlo antes de importarlo.

    No escribe nada en la base de datos (ver docstring del módulo) y tampoco
    vacía el borrador: si el usuario quiere corregir algo y volver a exportar,
    su pedido sigue armado.
    """
    filas = construir_filas_pedido(session_id, proveedor, fecha_recepcion)
    proveedor = validar_proveedor(proveedor)
    fecha_recepcion = validar_fecha_recepcion(fecha_recepcion)

    if not (ruta_destino or "").strip():
        raise ValueError("ERR_PEDIDO_RUTA: Debe indicar dónde guardar el archivo del pedido.")

    # `columns=` explícito: fija el orden de las columnas y garantiza que todas
    # las de la plantilla existan incluso si alguna fila no las trajera.
    df_productos = pd.DataFrame(filas, columns=list(ENCABEZADOS_PEDIDO))
    df_resumen = pd.DataFrame(
        [
            {"Dato": "Proveedor", "Valor": proveedor},
            {"Dato": "Fecha de Recepción", "Valor": fecha_recepcion},
            {"Dato": "Renglones", "Valor": len(filas)},
            {"Dato": "Unidades totales", "Valor": total_unidades(session_id)},
            {"Dato": "Costo USD Efectivo total", "Valor": total_costo_efectivo(session_id)},
            {"Dato": "Generado", "Valor": datetime.now().strftime("%d/%m/%Y %H:%M:%S")},
        ]
    )

    with pd.ExcelWriter(ruta_destino, engine="openpyxl") as writer:
        df_productos.to_excel(writer, sheet_name=NOMBRE_HOJA_PEDIDO, index=False)
        df_resumen.to_excel(writer, sheet_name=NOMBRE_HOJA_RESUMEN, index=False)

    return {
        "exito": True,
        "ruta": ruta_destino,
        "proveedor": proveedor,
        "fecha_recepcion": fecha_recepcion,
        "renglones": len(filas),
        "unidades": total_unidades(session_id),
        "mensaje": (
            f"Pedido de nueva mercancía generado con {len(filas)} renglón(es) "
            f"del proveedor '{proveedor}' (recepción {fecha_recepcion})."
        ),
    }


def nombre_archivo_sugerido(proveedor: str = "") -> str:
    """Nombre propuesto en el diálogo de guardado: identifica al proveedor y al
    momento para que dos pedidos no se sobrescriban entre sí."""
    prov = "".join(c for c in (proveedor or "") if c.isalnum() or c in " -_").strip().replace(" ", "_")
    sufijo = f"_{prov}" if prov else ""
    return f"Pedido_Nueva_Mercancia{sufijo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
