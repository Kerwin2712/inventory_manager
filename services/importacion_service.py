import os
import pandas as pd
from core.database import get_connection
from core.models import normalizar_costo, validar_costo_obligatorio

def limpiar_clave(k) -> str:
    """Normaliza las claves de diccionario de columnas para evitar fallos por acentos o formatos."""
    k_clean = str(k).lower().strip()
    replacements = (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("_", " "),
        ("-", " "),
        ("provehedor", "proveedor"),
    )
    for a, b in replacements:
        k_clean = k_clean.replace(a, b)
    return k_clean

# ═════════════════════════════════════════════════════════════════════════
# QUÉ INTENCIÓN TIENE LA IMPORTACIÓN SOBRE LA EXISTENCIA
# ═════════════════════════════════════════════════════════════════════════
# El mismo camino de Carga Masiva sirve para dos cosas que piden lo contrario:
#
#   - Cargar el catálogo inicial o RESTAURAR UN RESPALDO. Ahí la columna
#     Existencia describe el estado del inventario, así que hay que FIJARLA en
#     ese número. Si se sumara, cada vez que alguien reimporta un respaldo se
#     duplicarían las existencias de toda la base: un desastre silencioso y
#     muy difícil de deshacer, porque no hay con qué saber cuánto había antes.
#
#   - Ingresar una ENTRADA DE MERCANCÍA (el archivo que genera
#     `services.pedidos_service`). Ahí la columna Existencia es la cantidad que
#     acaba de llegar, así que hay que SUMARLA a lo que el producto ya tenía.
#     Decisión expresa del usuario del proyecto ("que sume al stock existente"):
#     si un repuesto tenía 5 unidades y el pedido trae 10, queda en 15 — antes
#     quedaba en 10 y las 5 que había se perdían.
#
# Las dos intenciones se distinguen por un marcador EXPLÍCITO dentro del
# archivo, nunca por adivinanza: la hoja de resumen que el generador de pedidos
# ya escribía lleva una fila cuyo valor es el literal `ENTRADA_DE_MERCANCIA`.
# Se exigen las dos cosas —el nombre de la hoja Y el literal en una celda—
# porque el nombre de una hoja es un indicio débil (cualquiera puede llamar así
# a una hoja), mientras que ese literal no lo escribe nadie por accidente. Todo
# lo demás, incluido cualquier archivo que un usuario arme a mano, entra por el
# camino de siempre: ante la duda se FIJA, que es el comportamiento histórico y
# el que no multiplica stock.
MODO_FIJAR = "fijar"
MODO_SUMAR = "sumar"

NOMBRE_HOJA_ENTRADA_MERCANCIA = "Resumen del Pedido"
ETIQUETA_TIPO_ARCHIVO = "Tipo de archivo"
MARCADOR_ENTRADA_MERCANCIA = "ENTRADA_DE_MERCANCIA"

_CLAVE_HOJA_ENTRADA = NOMBRE_HOJA_ENTRADA_MERCANCIA.lower().strip()


def _modo_desde_libro(excel_file, sheet_map: dict) -> str:
    """`MODO_SUMAR` solo si el libro trae el marcador de entrada de mercancía.

    Cualquier problema para leer la hoja de resumen devuelve `MODO_FIJAR`:
    fail-closed hacia el comportamiento histórico, porque equivocarse sumando
    duplica el inventario entero y equivocarse fijando solo deja el valor que el
    archivo declara.
    """
    hoja = sheet_map.get(_CLAVE_HOJA_ENTRADA)
    if hoja is None:
        return MODO_FIJAR
    try:
        df = pd.read_excel(excel_file, sheet_name=hoja).fillna("")
    except Exception:
        return MODO_FIJAR

    columnas = {limpiar_clave(c): c for c in df.columns}
    col_dato, col_valor = columnas.get("dato"), columnas.get("valor")
    if not col_dato or not col_valor:
        return MODO_FIJAR

    etiqueta_buscada = limpiar_clave(ETIQUETA_TIPO_ARCHIVO)
    for _idx, fila in df.iterrows():
        if limpiar_clave(fila[col_dato]) != etiqueta_buscada:
            continue
        if str(fila[col_valor]).strip().upper() == MARCADOR_ENTRADA_MERCANCIA:
            return MODO_SUMAR
    return MODO_FIJAR


def detectar_modo_existencia(ruta_archivo: str) -> str:
    """Intención del archivo sobre la existencia (`MODO_SUMAR`/`MODO_FIJAR`).

    Pública para que la interfaz pueda avisarle al Administrador qué está a
    punto de cargar, y para poder testear la detección sin importar nada.
    """
    try:
        excel_file = pd.ExcelFile(ruta_archivo)
    except Exception:
        return MODO_FIJAR
    try:
        sheet_map = {str(s).lower().strip(): s for s in excel_file.sheet_names}
        return _modo_desde_libro(excel_file, sheet_map)
    finally:
        try:
            excel_file.close()
        except Exception:
            pass


def analizar_proveedores_excel(ruta_archivo: str) -> dict:
    """
    Analiza el archivo Excel buscando nombres de proveedores que no estén registrados en la base de datos.
    Retorna un diccionario indicando el éxito y la lista de nombres faltantes.
    """
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return {
            "exito": False,
            "proveedores_faltantes": [],
            "mensaje": f"El archivo especificado no existe o la ruta no es válida: '{ruta_archivo}'"
        }

    try:
        excel_file = pd.ExcelFile(ruta_archivo)
        sheet_names = excel_file.sheet_names
    except Exception as ex:
        return {
            "exito": False,
            "proveedores_faltantes": [],
            "mensaje": f"Error al abrir el archivo Excel: {str(ex)}"
        }

    sheet_map = {str(s).lower().strip(): s for s in sheet_names}
    hoja_productos = None

    # Buscar la pestaña de productos
    for key in ["productos", "producto", "inventario"]:
        if key in sheet_map:
            hoja_productos = sheet_map[key]
            break

    if not hoja_productos:
        if len(sheet_names) == 1:
            hoja_productos = sheet_names[0]
        elif "hoja1" in sheet_map:
            hoja_productos = sheet_map["hoja1"]
        else:
            excel_file.close()
            return {
                "exito": False,
                "proveedores_faltantes": [],
                "mensaje": "No se encontró la pestaña de productos en el Excel (buscadas: 'Productos', 'Inventario' o una pestaña única)."
            }

    try:
        df = pd.read_excel(excel_file, sheet_name=hoja_productos).fillna("")
        excel_file.close()

        # Buscar la columna del proveedor de manera tolerante
        col_proveedor = None
        for col in df.columns:
            col_clean = limpiar_clave(col)
            if col_clean in ["proveedor", "proveedor nombre", "proveedores", "nombre proveedor"]:
                col_proveedor = col
                break

        if not col_proveedor:
            return {
                "exito": True,
                "proveedores_faltantes": [],
                "mensaje": "No se encontró columna de proveedor en la hoja de productos."
            }

        proveedores_excel = set()
        for v in df[col_proveedor].unique():
            val = str(v).strip()
            if val and val != "nan" and val.upper() != "NAN":
                proveedores_excel.add(val)

        if not proveedores_excel:
            return {
                "exito": True,
                "proveedores_faltantes": [],
                "mensaje": "No hay nombres de proveedores registrados en el catálogo de productos."
            }

        # Comparar con los proveedores existentes en BD
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT empresa FROM proveedores")
        prov_existentes = {str(row["empresa"]).strip().lower() for row in cursor.fetchall()}
        conn.close()

        faltantes = []
        for p in proveedores_excel:
            if p.lower() not in prov_existentes:
                faltantes.append(p)

        return {
            "exito": True,
            "proveedores_faltantes": sorted(faltantes),
            "mensaje": f"Análisis finalizado. Encontrados {len(faltantes)} proveedores nuevos."
        }

    except Exception as ex:
        try:
            excel_file.close()
        except Exception:
            pass
        return {
            "exito": False,
            "proveedores_faltantes": [],
            "mensaje": f"Error al analizar el contenido de la hoja de productos: {str(ex)}"
        }

# ═════════════════════════════════════════════════════════════════════════
# Asistente de mapeo de columnas (importación de inventario)
# ═════════════════════════════════════════════════════════════════════════
# En vez de adivinar a ciegas a partir del nombre de cada columna del Excel
# (heurística usada por `procesar_importacion_excel` más abajo), este flujo
# le muestra al usuario las columnas reales del archivo con una muestra de
# filas y le deja decidir explícitamente a qué campo de la base de datos
# corresponde cada una — funciona sin importar cómo se llamen las columnas.

# (campo_bd, etiqueta visible, obligatorio)
#
# El Sub-Departamento y los dos COSTOS entraron acá por decisión expresa del
# usuario del proyecto ("sí, agregarlos"): las columnas existen en `productos`
# desde la migración de octubre 2026, pero la Carga Masiva no las leía, así que
# los costos que el empleado anotaba en el pedido de nueva mercancía llegaban al
# Administrador como información meramente visual y alguien tenía que
# retipearlos a mano en la ficha de cada producto.
#
# Los COSTOS son información reservada a la administración
# (`services.permisos_service`), y esto no abre ningún camino nuevo hacia ellos:
# se ESCRIBEN desde un archivo que el Administrador supervisa, y quien los lea
# después sigue pasando por `obtener_producto`/`listar_productos`, que filtran
# por rol. Lo que no debe hacerse nunca es exportarlos desde una vista sin
# control de rol (ver la Copia de Seguridad de Gestión de Datos, que está
# disponible para todos los roles y por eso NO los incluye).
CAMPOS_PRODUCTO_MAPEO = [
    ("codigo", "Código", True),
    ("referencia", "Referencia", False),
    ("departamento", "Departamento", False),
    ("sub_departamento", "Sub-Departamento", False),
    ("descripcion_general", "Descripción General", False),
    ("marca", "Marca", False),
    ("precio_dolares", "Precio USD (Efectivo)", False),
    ("precio_bcv", "Precio USD (BCV)", False),
    ("costo_usd_efectivo", "Costo USD (Efectivo)", False),
    ("costo_usd_bcv", "Costo USD (BCV)", False),
    ("proveedor", "Proveedor (nombre)", False),
    ("existencia", "Existencia", False),
    ("codigo_barras", "Código de Barras", False),
    ("nombre_referencia_corto", "Nombre Corto", False),
]

# Alias conocidos por campo. Se usan para PRE-sugerir el mapeo (el usuario
# siempre puede corregirlo antes de confirmar la importación) y también como la
# única definición de "cómo se puede llamar esta columna" para el lector
# heurístico de más abajo — antes había dos listas de alias separadas, escritas
# a mano, que se desincronizaban en silencio.
#
# Los alias de los tres campos nuevos incluyen a propósito el encabezado EXACTO
# que `services.pedidos_service` ya venía emitiendo para esas columnas cuando
# eran meramente informativas ('Sub-Departamento', 'Costo USD (Efectivo)',
# 'Costo USD (BCV)'): así los archivos de pedido ya generados y guardados por
# ahí siguen entrando, y ahora además con sus costos.
_ALIAS_CAMPO_PRODUCTO = {
    "codigo": ["codigo"],
    "referencia": ["referencias", "referencia"],
    "departamento": ["departamento", "categoria"],
    "sub_departamento": ["sub departamento", "subdepartamento", "sub categoria", "subcategoria"],
    "descripcion_general": ["descripcion general", "descripcion"],
    "marca": ["marca"],
    "precio_dolares": ["precio usd (efectivo)", "precio usd", "precio ($)", "precio"],
    "precio_bcv": ["precio usd (bcv)", "precio bcv", "precio (bs bcv)"],
    "costo_usd_efectivo": ["costo usd (efectivo)", "costo usd", "costo ($)", "costo"],
    "costo_usd_bcv": ["costo usd (bcv)", "costo bcv", "costo (bs bcv)"],
    "proveedor": ["proveedor", "proveedor nombre", "nombre proveedor"],
    "existencia": ["existencia", "stock"],
    "codigo_barras": ["codigo de barra", "codigo de barras", "codigo barras"],
    "nombre_referencia_corto": ["nombre referencia corto", "nombre corto"],
}

# Alias que solo entiende el lector heurístico. El ID de proveedor no es un
# campo del asistente de mapeo (ahí el proveedor se elige por nombre), pero el
# respaldo que genera la propia aplicación lo exporta, así que un respaldo
# reimportado tiene que seguir enlazando sus proveedores.
_ALIAS_LECTURA_PRODUCTO = {
    **_ALIAS_CAMPO_PRODUCTO,
    "proveedor_id": ["id proveedor", "proveedor id"],
}

# Campos cuyo valor YA ALMACENADO se conserva cuando el archivo no trae su
# columna (o la trae en blanco). Son los tres que se agregaron a la Carga
# Masiva: los archivos que la gente tiene guardados de antes no los mencionan,
# y `INSERT OR REPLACE` borra la fila entera y la vuelve a insertar, así que sin
# esta mezcla reimportar un respaldo viejo borraría en silencio los costos y el
# sub-departamento de todo el catálogo.
_CAMPOS_CONSERVABLES = ("sub_departamento", "costo_usd_efectivo", "costo_usd_bcv")


def listar_hojas_excel(ruta_archivo: str) -> list[str]:
    """Nombres de las pestañas (hojas) del archivo Excel, en orden."""
    excel_file = pd.ExcelFile(ruta_archivo)
    try:
        return list(excel_file.sheet_names)
    finally:
        excel_file.close()


def detectar_hoja_productos(ruta_archivo: str) -> str | None:
    """Misma heurística de detección de la hoja de productos usada por el
    resto del módulo (nombre 'Productos'/'Inventario', o la única hoja si
    solo hay una), reutilizada como sugerencia inicial del asistente de
    mapeo — el usuario puede elegir otra hoja si la detección falla."""
    sheet_names = listar_hojas_excel(ruta_archivo)
    sheet_map = {str(s).lower().strip(): s for s in sheet_names}
    for key in ["productos", "producto", "inventario"]:
        if key in sheet_map:
            return sheet_map[key]
    if len(sheet_names) == 1:
        return sheet_names[0]
    if "hoja1" in sheet_map:
        return sheet_map["hoja1"]
    return None


def obtener_columnas_y_muestra(ruta_archivo: str, hoja: str, n_muestra: int = 5) -> dict:
    """Lee solo las primeras `n_muestra` filas de la hoja indicada: columnas
    reales del archivo (en el orden en que aparecen) y, por cada una, sus
    primeros valores — para que el usuario vea qué contiene cada columna
    antes de decidir a qué campo mapearla."""
    df = pd.read_excel(ruta_archivo, sheet_name=hoja, nrows=n_muestra).fillna("")
    columnas = [str(c) for c in df.columns]
    muestra = {str(c): [str(v) for v in df[c].tolist()] for c in df.columns}
    return {"columnas": columnas, "muestra": muestra}


def sugerir_mapeo_columnas(columnas: list[str]) -> dict[str, str]:
    """Pre-rellena campo_bd -> columna_excel usando los alias conocidos,
    como punto de partida editable por el usuario en el asistente."""
    limpio_a_original = {limpiar_clave(c): c for c in columnas}
    mapeo: dict[str, str] = {}
    for campo, alias_list in _ALIAS_CAMPO_PRODUCTO.items():
        for alias in alias_list:
            if alias in limpio_a_original:
                mapeo[campo] = limpio_a_original[alias]
                break
    return mapeo


def analizar_proveedores_con_mapeo(ruta_archivo: str, hoja: str, columna_proveedor: str | None) -> dict:
    """Igual que `analizar_proveedores_excel`, pero usando la columna de
    proveedor que el usuario indicó explícitamente en el asistente de mapeo
    en vez de adivinarla por nombre."""
    if not columna_proveedor:
        return {"exito": True, "proveedores_faltantes": [], "mensaje": "No se mapeó ninguna columna a Proveedor."}

    try:
        df = pd.read_excel(ruta_archivo, sheet_name=hoja).fillna("")
        if columna_proveedor not in df.columns:
            return {"exito": True, "proveedores_faltantes": [], "mensaje": "La columna de proveedor mapeada ya no existe en la hoja."}

        proveedores_excel = set()
        for v in df[columna_proveedor].unique():
            val = str(v).strip()
            if val and val.upper() != "NAN":
                proveedores_excel.add(val)

        if not proveedores_excel:
            return {"exito": True, "proveedores_faltantes": [], "mensaje": "No hay nombres de proveedores en esa columna."}

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT empresa FROM proveedores")
            prov_existentes = {str(row["empresa"]).strip().lower() for row in cursor.fetchall()}

        faltantes = sorted(p for p in proveedores_excel if p.lower() not in prov_existentes)
        return {
            "exito": True,
            "proveedores_faltantes": faltantes,
            "mensaje": f"Análisis finalizado. Encontrados {len(faltantes)} proveedores nuevos.",
        }
    except Exception as ex:
        return {"exito": False, "proveedores_faltantes": [], "mensaje": f"Error al analizar proveedores: {ex}"}


# ═════════════════════════════════════════════════════════════════════════
# LECTURA Y ESCRITURA DE UNA FILA DE PRODUCTOS (compartidas)
# ═════════════════════════════════════════════════════════════════════════
# Hay tres caminos de importación de productos —heurística completa, mapeo
# explícito de solo productos y mapeo explícito completo— y los tres repetían
# la misma normalización de la fila y el mismo `INSERT OR REPLACE` copiado
# literal. Mantener tres copias sincronizadas a mano no es viable: una que se
# quede atrás no rompe ningún test, el archivo simplemente se importa con
# columnas ignoradas. Así que la normalización y la escritura viven acá, y cada
# camino solo aporta su LECTOR de columnas.
#
# Contrato del lector: `leer(campo) -> str | None`.
#   `None` → el archivo NO trae esa columna.
#   `""`   → la trae, pero esta fila la dejó en blanco.
# La diferencia no es cosmética: decide si un dato se sobrescribe o se conserva
# el ya almacenado (ver `_CAMPOS_CONSERVABLES`).


def _lector_mapeado(row, mapeo: dict[str, str]):
    """Lector de una fila con el mapeo campo_bd -> columna_excel que el usuario
    confirmó en el asistente. Un campo sin columna mapeada es un campo que el
    archivo no trae."""
    def leer(campo: str) -> str | None:
        columna = mapeo.get(campo)
        if not columna or columna not in row:
            return None
        v = row[columna]
        return "" if v is None else str(v).strip()
    return leer


def _lector_heuristico(r_dict: dict[str, str]):
    """Lector que adivina la columna por su nombre, usando los MISMOS alias que
    pre-sugiere el asistente de mapeo (`_ALIAS_LECTURA_PRODUCTO`).

    Entre varios alias presentes gana el primero que traiga un valor —no el
    primero que exista— para no cambiar el comportamiento histórico: un archivo
    con 'Precio USD (Efectivo)' en blanco y 'Precio' con el número seguía
    tomando el número.
    """
    def leer(campo: str) -> str | None:
        presente = False
        for alias in _ALIAS_LECTURA_PRODUCTO.get(campo, ()):
            if alias not in r_dict:
                continue
            presente = True
            valor = r_dict[alias]
            if valor:
                return valor
        return "" if presente else None
    return leer


def _numero_legado(texto: str, simbolos: tuple[str, ...] = ("$",)) -> float:
    """Parseo histórico de los PRECIOS de venta: quita el símbolo monetario, los
    espacios y las comas (ahí la coma es separador de miles, '$ 1,234.56') y
    devuelve 0.0 si la celda está vacía. Lanza `ValueError` si no es un número."""
    crudo = str(texto)
    for simbolo in simbolos:
        crudo = crudo.replace(simbolo, "")
    crudo = crudo.replace(" ", "").replace(",", "").strip()
    return float(crudo) if crudo else 0.0


def _valores_producto(leer, hoja: str, num_fila: int) -> tuple[dict, set[str]] | None:
    """Normaliza una fila de la hoja de productos.

    Devuelve `(valores, presentes)`, o `None` si la fila está vacía y hay que
    saltarla. `presentes` son los campos que el archivo trae como columna.
    """
    crudo = {campo: leer(campo) for campo, _etiqueta, _obligatorio in CAMPOS_PRODUCTO_MAPEO}
    crudo["proveedor_id"] = leer("proveedor_id")
    presentes = {campo for campo, valor in crudo.items() if valor is not None}

    def texto(campo: str) -> str:
        return str(crudo.get(campo) or "").strip()

    codigo = texto("codigo")
    cod_barras = texto("codigo_barras")
    # Sin código pero con código de barras, el de barras hace de código: es el
    # identificador que de hecho trae el archivo.
    if not codigo and cod_barras:
        codigo = cod_barras
    nombre_corto = texto("nombre_referencia_corto")

    if not codigo and not nombre_corto:
        return None
    if not codigo:
        raise ValueError(f"Hoja '{hoja}' (Fila {num_fila}): El Código de producto no puede estar vacío.")
    if not nombre_corto:
        nombre_corto = codigo[:30]

    try:
        precio_usd = _numero_legado(texto("precio_dolares"))
    except ValueError:
        raise ValueError(
            f"Hoja '{hoja}' (Fila {num_fila}): El precio en USD "
            f"'{texto('precio_dolares')}' no es un número válido."
        )

    try:
        precio_bcv = _numero_legado(texto("precio_bcv"), simbolos=("Bs", "$"))
    except ValueError:
        # El precio BCV es una referencia derivada: una celda ilegible no debe
        # abortar la importación completa (comportamiento histórico).
        precio_bcv = 0.0

    try:
        existencia = _numero_legado(texto("existencia"), simbolos=())
    except ValueError:
        raise ValueError(
            f"Hoja '{hoja}' (Fila {num_fila}): La existencia "
            f"'{texto('existencia')}' no es un número válido."
        )

    valores = {
        "codigo": codigo,
        "referencia": texto("referencia"),
        "departamento": texto("departamento") or "GENERAL",
        "sub_departamento": texto("sub_departamento"),
        "descripcion_general": texto("descripcion_general"),
        "marca": texto("marca"),
        "precio_dolares": precio_usd,
        "precio_bcv": precio_bcv,
        "existencia": existencia,
        "codigo_barras": cod_barras,
        "nombre_referencia_corto": nombre_corto,
        "proveedor": texto("proveedor"),
        "proveedor_id": texto("proveedor_id"),
    }

    for campo, etiqueta in (
        ("costo_usd_efectivo", "Costo USD Efectivo"),
        ("costo_usd_bcv", "Costo USD BCV"),
    ):
        valores[campo] = _costo_de_celda(crudo.get(campo), etiqueta, hoja, num_fila)

    return valores, presentes


def _costo_de_celda(bruto, etiqueta: str, hoja: str, num_fila: int) -> float | None:
    """Costo leído del Excel, con la MISMA definición de validez que el
    formulario de Inventario: se delega en `core.models.normalizar_costo` en vez
    de reimplementar la regla (acepta coma o punto decimal, vacío = sin dato,
    rechaza negativos y no numéricos).

    Se le quitan antes el símbolo monetario y los espacios, porque la celda
    puede venir formateada como '$ 20,50'; las COMAS no se tocan, y ahí está la
    diferencia deliberada con `_numero_legado`: en un costo la coma es el
    separador decimal que escribe el usuario venezolano, no un separador de
    miles. Una sola definición de costo válido en todo el sistema vale más que
    la simetría con el parseo histórico de los precios.
    """
    if bruto is None:
        return None
    limpio = str(bruto).replace("$", "").replace("Bs", "").replace(" ", "").strip()
    try:
        return normalizar_costo(limpio, etiqueta)
    except ValueError as ex:
        raise ValueError(f"Hoja '{hoja}' (Fila {num_fila}): {str(ex).split(': ', 1)[-1]}")


def _escribir_producto(
    cursor, valores: dict, presentes: set[str], hoja: str, num_fila: int,
    modo: str = MODO_FIJAR,
) -> None:
    """Inserta o actualiza el producto de una fila ya normalizada.

    `modo` es lo que el archivo quiere de la existencia: `MODO_FIJAR` la deja en
    el número de la columna (catálogo, respaldo) y `MODO_SUMAR` se la suma a la
    que el producto ya tenía (entrada de mercancía). Ver la sección de arriba.
    """
    codigo = valores["codigo"]
    cursor.execute(
        "SELECT existencia, sub_departamento, costo_usd_efectivo, costo_usd_bcv, "
        "alerta_stock_minimo FROM productos WHERE codigo = ?",
        (codigo,),
    )
    previo = cursor.fetchone()

    def conservado(campo: str):
        """El valor del archivo si lo trae, y si no el que ya estaba guardado.
        Una columna ausente —o presente pero en blanco— significa "no tengo
        dato", nunca "borrá el que había": ver `_CAMPOS_CONSERVABLES`."""
        propio = valores.get(campo)
        if campo in presentes and propio not in (None, ""):
            return propio
        return previo[campo] if previo is not None else None

    sub_departamento = conservado("sub_departamento")
    costo_efectivo = conservado("costo_usd_efectivo")
    costo_bcv = conservado("costo_usd_bcv")
    # La alerta de stock mínimo no viaja en ningún archivo, así que siempre se
    # conserva: sin esto, `INSERT OR REPLACE` la pondría en NULL en cada carga.
    alerta = previo["alerta_stock_minimo"] if previo is not None else None

    existencia = valores["existencia"]
    if modo == MODO_SUMAR and previo is not None:
        # Entrada de mercancía: la cantidad recibida se SUMA a lo que había.
        # Un producto que todavía no existe entra con la cantidad tal cual, sin
        # tratamiento especial: no tiene existencia previa a la que sumarle.
        existencia = float(previo["existencia"] or 0.0) + existencia

    # Regla de negocio del dominio (`core.models.validar_costo_obligatorio`):
    # un producto con existencia (>= 1 unidad) debe tener su Costo USD Efectivo.
    # Solo se exige cuando el archivo TRAE la columna de costo: un archivo viejo
    # que no la menciona no puede volverse inválido de golpe —el usuario del
    # proyecto pidió expresamente que los archivos ya existentes sigan
    # entrando—. Cuando sí la trae, se RECHAZA la fila en vez de importarla:
    # un producto con stock y sin costo es un producto que el dominio considera
    # inválido y que después ningún formulario deja volver a guardar.
    if "costo_usd_efectivo" in presentes:
        try:
            validar_costo_obligatorio(existencia, costo_efectivo)
        except ValueError:
            raise ValueError(
                f"Hoja '{hoja}' (Fila {num_fila}): El producto '{codigo}' queda con "
                f"existencia ({existencia:g}), así que el archivo debe traer su "
                f"Costo USD Efectivo."
            )

    prov_id = _resolver_proveedor(cursor, valores)

    cursor.execute(
        """
        INSERT OR REPLACE INTO productos (
            codigo, referencia, departamento, sub_departamento, descripcion_general,
            marca, precio_dolares, precio_bcv, costo_usd_efectivo, costo_usd_bcv,
            proveedor_id, existencia, codigo_barras, nombre_referencia_corto,
            alerta_stock_minimo, fecha_ultima_modificacion, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (
            codigo, valores["referencia"], valores["departamento"], sub_departamento,
            valores["descripcion_general"], valores["marca"], valores["precio_dolares"],
            valores["precio_bcv"], costo_efectivo, costo_bcv, prov_id, existencia,
            valores["codigo_barras"], valores["nombre_referencia_corto"], alerta,
        ),
    )


def _resolver_proveedor(cursor, valores: dict) -> int | None:
    """ID del proveedor de la fila: por ID numérico si el archivo lo trae, y si
    no buscando su razón social en la tabla `proveedores`."""
    prov_id_str = valores.get("proveedor_id") or ""
    if prov_id_str and prov_id_str.replace(".", "", 1).isdigit():
        return int(float(prov_id_str))
    prov_nombre = valores.get("proveedor") or ""
    if not prov_nombre:
        return None
    cursor.execute(
        "SELECT id FROM proveedores WHERE LOWER(TRIM(empresa)) = LOWER(TRIM(?))", (prov_nombre,)
    )
    fila = cursor.fetchone()
    return fila["id"] if fila else None


def procesar_importacion_productos_mapeada(ruta_archivo: str, hoja: str, mapeo: dict[str, str]) -> dict:
    """Importa la hoja de productos indicada usando un mapeo EXPLÍCITO
    `campo_bd -> columna_excel` elegido por el usuario en el asistente
    (en vez de adivinar por nombre de columna) — transaccional (ACID),
    con ROLLBACK automático ante cualquier fila inválida."""
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return {"exito": False, "mensaje": f"El archivo especificado no existe: '{ruta_archivo}'", "hoja": hoja, "fila": None}
    if not mapeo.get("codigo"):
        return {"exito": False, "mensaje": "Debe mapear una columna al campo obligatorio 'Código'.", "hoja": hoja, "fila": None}

    try:
        df = pd.read_excel(ruta_archivo, sheet_name=hoja).fillna("")
    except Exception as ex:
        return {"exito": False, "mensaje": f"Error al leer la hoja '{hoja}': {ex}", "hoja": hoja, "fila": None}

    modo = detectar_modo_existencia(ruta_archivo)
    conn = get_connection()
    conn.isolation_level = None
    cursor = conn.cursor()
    num_fila = 0

    try:
        cursor.execute("BEGIN TRANSACTION")
        count = 0
        for idx, row in df.iterrows():
            num_fila = idx + 2
            normalizada = _valores_producto(_lector_mapeado(row, mapeo), hoja, num_fila)
            if normalizada is None:
                continue
            valores, presentes = normalizada
            _escribir_producto(cursor, valores, presentes, hoja, num_fila, modo=modo)
            count += 1

        cursor.execute("COMMIT")
        conn.close()

        return {
            "exito": True,
            "mensaje": f"Importación exitosa: {count} producto(s) procesado(s) desde la hoja '{hoja}'.",
            "detalles": {"productos": count},
        }
    except Exception as ex:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        msg_error = str(ex)
        if "Hoja " not in msg_error:
            msg_error = f"Error en la hoja '{hoja}' (Fila {num_fila}): {msg_error}"
        return {"exito": False, "mensaje": msg_error, "hoja": hoja, "fila": num_fila}


def _importar_hoja_proveedores(cursor, excel_file, sheet_map: dict) -> tuple[int, str | None]:
    """Inserta/actualiza proveedores desde la hoja 'Proveedores' (heurística
    automática por nombre de columna), si existe. Devuelve (cantidad, hoja
    usada) — (0, None) si no hay hoja de proveedores en el archivo. Extraída
    como helper para ser reutilizada tanto por la importación clásica
    (heurística también en Productos) como por la importación con mapeo
    explícito de columnas de Productos."""
    for key in ["proveedores", "proveedor"]:
        if key not in sheet_map:
            continue
        hoja = sheet_map[key]
        df = pd.read_excel(excel_file, sheet_name=hoja).fillna("")
        count = 0
        for idx, row in df.iterrows():
            num_fila = idx + 2
            r_dict = {limpiar_clave(k): str(v).strip() for k, v in row.items()}

            empresa = (r_dict.get("razon social / empresa") or r_dict.get("empresa") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()
            if not empresa:
                continue

            prov_id_str = r_dict.get("id") or r_dict.get("id proveedor") or r_dict.get("proveedor id") or ""
            try:
                prov_id = int(float(prov_id_str)) if prov_id_str and prov_id_str.replace('.', '', 1).isdigit() else None
            except ValueError:
                prov_id = None

            contacto = r_dict.get("persona de contacto") or r_dict.get("contacto") or ""
            telefono = r_dict.get("telefono") or ""
            correo = r_dict.get("correo electronico") or r_dict.get("correo") or r_dict.get("email") or ""
            desc = r_dict.get("descripcion / notas") or r_dict.get("descripcion") or r_dict.get("notas") or ""

            if prov_id:
                cursor.execute(
                    "INSERT OR REPLACE INTO proveedores (id, empresa, contacto, telefono, correo, descripcion, updated_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    (prov_id, empresa, contacto, telefono, correo, desc),
                )
            else:
                cursor.execute(
                    "INSERT INTO proveedores (empresa, contacto, telefono, correo, descripcion, created_at, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (empresa, contacto, telefono, correo, desc),
                )
            count += 1
        return count, hoja
    return 0, None


def _importar_hoja_clientes(cursor, excel_file, sheet_map: dict) -> tuple[int, str | None]:
    """Inserta/actualiza clientes desde la hoja 'Clientes' (heurística
    automática), si existe. Devuelve (cantidad, hoja usada)."""
    for key in ["clientes", "cliente"]:
        if key not in sheet_map:
            continue
        hoja = sheet_map[key]
        df = pd.read_excel(excel_file, sheet_name=hoja).fillna("")
        count = 0
        for idx, row in df.iterrows():
            num_fila = idx + 2
            r_dict = {limpiar_clave(k): str(v).strip() for k, v in row.items()}

            cedula_rif = (r_dict.get("cedula / rif") or r_dict.get("cedula rif") or r_dict.get("cedula") or r_dict.get("rif") or "").strip()
            nombre = (r_dict.get("razon social / nombre") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()

            if not cedula_rif and not nombre:
                continue
            if not cedula_rif:
                raise ValueError(f"Hoja '{hoja}' (Fila {num_fila}): La Cédula/RIF del cliente no puede estar vacía.")

            direccion = r_dict.get("direccion") or ""
            telefono = r_dict.get("telefono") or ""
            correo = r_dict.get("correo electronico") or r_dict.get("email") or r_dict.get("correo") or ""

            cursor.execute(
                "INSERT OR REPLACE INTO clientes (cedula_rif, nombre, direccion, telefono, correo, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (cedula_rif, nombre, direccion, telefono, correo),
            )
            count += 1
        return count, hoja
    return 0, None


def ejecutar_importacion_completa_mapeada(ruta_archivo: str, hoja_productos: str, mapeo_productos: dict) -> dict:
    """Orquesta la importación completa en una sola transacción: Proveedores
    y Clientes se procesan igual que en `procesar_importacion_excel`
    (heurística automática por nombre de columna, sin cambios), y la hoja de
    Productos se procesa con el mapeo EXPLÍCITO campo_bd->columna_excel que
    el usuario confirmó en el asistente de mapeo — funciona sin importar
    cómo se llamen las columnas del archivo."""
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return {"exito": False, "mensaje": f"El archivo especificado no existe: '{ruta_archivo}'", "hoja": None, "fila": None}
    if not mapeo_productos.get("codigo"):
        return {"exito": False, "mensaje": "Debe mapear una columna al campo obligatorio 'Código'.", "hoja": hoja_productos, "fila": None}

    try:
        excel_file = pd.ExcelFile(ruta_archivo)
        sheet_names = excel_file.sheet_names
    except Exception as ex:
        return {"exito": False, "mensaje": f"Error al abrir el archivo Excel: {ex}", "hoja": None, "fila": None}

    sheet_map = {str(s).lower().strip(): s for s in sheet_names}
    modo = _modo_desde_libro(excel_file, sheet_map)
    conn = get_connection()
    conn.isolation_level = None
    cursor = conn.cursor()
    hoja_actual = None
    num_fila = 0

    try:
        cursor.execute("BEGIN TRANSACTION")
        stats = {"productos": 0, "clientes": 0, "proveedores": 0}

        stats["proveedores"], hoja_prov = _importar_hoja_proveedores(cursor, excel_file, sheet_map)
        if hoja_prov:
            hoja_actual = hoja_prov

        stats["clientes"], hoja_cli = _importar_hoja_clientes(cursor, excel_file, sheet_map)
        if hoja_cli:
            hoja_actual = hoja_cli

        if hoja_productos:
            hoja_actual = hoja_productos
            df = pd.read_excel(excel_file, sheet_name=hoja_productos).fillna("")
            for idx, row in df.iterrows():
                num_fila = idx + 2
                normalizada = _valores_producto(
                    _lector_mapeado(row, mapeo_productos), hoja_actual, num_fila
                )
                if normalizada is None:
                    continue
                valores, presentes = normalizada
                _escribir_producto(cursor, valores, presentes, hoja_actual, num_fila, modo=modo)
                stats["productos"] += 1

        cursor.execute("COMMIT")
        conn.close()
        excel_file.close()

        total = stats["productos"] + stats["clientes"] + stats["proveedores"]
        if total == 0:
            return {
                "exito": True,
                "mensaje": "El archivo se leyó correctamente, pero no se encontraron filas de datos válidos para procesar.",
                "detalles": stats,
            }
        return {
            "exito": True,
            "mensaje": f"Importación exitosa. Se procesaron {stats['productos']} productos, {stats['clientes']} clientes y {stats['proveedores']} proveedores.",
            "detalles": stats,
        }
    except Exception as ex:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        try:
            excel_file.close()
        except Exception:
            pass
        msg_error = str(ex)
        if hoja_actual and num_fila > 0 and "Hoja " not in msg_error:
            msg_error = f"Error en la hoja '{hoja_actual}' (Fila {num_fila}): {msg_error}"
        return {"exito": False, "mensaje": msg_error, "hoja": hoja_actual, "fila": num_fila}


def procesar_importacion_excel(ruta_archivo: str) -> dict:
    """
    Procesa un archivo Excel de forma defensiva y transaccional (ACID).
    Busca pestañas 'Productos', 'Clientes' y 'Proveedores' (insensible a mayúsculas).
    Si se trata de un archivo con una única hoja, la trata como el catálogo de productos.
    """
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return {
            "exito": False,
            "mensaje": f"El archivo especificado no existe o la ruta no es válida: '{ruta_archivo}'",
            "hoja": None,
            "fila": None
        }

    try:
        excel_file = pd.ExcelFile(ruta_archivo)
        sheet_names = excel_file.sheet_names
    except Exception as ex:
        return {
            "exito": False,
            "mensaje": f"Error al abrir el archivo Excel: {str(ex)}",
            "hoja": None,
            "fila": None
        }

    sheet_map = {str(s).lower().strip(): s for s in sheet_names}
    modo = _modo_desde_libro(excel_file, sheet_map)

    conn = get_connection()
    conn.isolation_level = None  # Control de transacciones explícitas
    cursor = conn.cursor()

    hoja_actual = None
    num_fila = 0

    try:
        cursor.execute("BEGIN TRANSACTION")
        stats = {"productos": 0, "clientes": 0, "proveedores": 0}

        # ── 1. PROVEEDORES ───────────────────────────────────────────────────
        stats["proveedores"], hoja_prov = _importar_hoja_proveedores(cursor, excel_file, sheet_map)
        if hoja_prov:
            hoja_actual = hoja_prov

        # ── 2. CLIENTES ──────────────────────────────────────────────────────
        stats["clientes"], hoja_cli = _importar_hoja_clientes(cursor, excel_file, sheet_map)
        if hoja_cli:
            hoja_actual = hoja_cli

        # ── 3. PRODUCTOS ─────────────────────────────────────────────────────
        hoja_productos = None
        for key in ["productos", "producto", "inventario"]:
            if key in sheet_map:
                hoja_productos = sheet_map[key]
                break

        # Fallback: Si no tiene pestañas específicas pero tiene una sola hoja, o se llama Hoja1
        if not hoja_productos:
            if len(sheet_names) == 1:
                hoja_productos = sheet_names[0]
            elif "hoja1" in sheet_map:
                hoja_productos = sheet_map["hoja1"]

        if hoja_productos:
            hoja_actual = hoja_productos
            df = pd.read_excel(excel_file, sheet_name=hoja_productos).fillna("")
            for idx, row in df.iterrows():
                num_fila = idx + 2
                r_dict = {limpiar_clave(k): str(v).strip() for k, v in row.items()}
                normalizada = _valores_producto(
                    _lector_heuristico(r_dict), hoja_actual, num_fila
                )
                if normalizada is None:
                    continue
                valores, presentes = normalizada
                _escribir_producto(cursor, valores, presentes, hoja_actual, num_fila, modo=modo)
                stats["productos"] += 1

        cursor.execute("COMMIT")
        conn.close()
        excel_file.close()

        total = stats["productos"] + stats["clientes"] + stats["proveedores"]
        if total == 0:
            return {
                "exito": True,
                "mensaje": "El archivo se leyó correctamente, pero no se encontraron pestañas o filas de datos válidos para procesar.",
                "detalles": stats
            }

        return {
            "exito": True,
            "mensaje": f"Importación exitosa. Se procesaron {stats['productos']} productos, {stats['clientes']} clientes y {stats['proveedores']} proveedores.",
            "detalles": stats
        }

    except Exception as ex:
        try:
            cursor.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
        try:
            excel_file.close()
        except Exception:
            pass

        msg_error = str(ex)
        if hoja_actual and num_fila > 0 and "Hoja " not in msg_error:
            msg_error = f"Error en la hoja '{hoja_actual}' (Fila {num_fila}): {msg_error}"

        return {
            "exito": False,
            "mensaje": msg_error,
            "hoja": hoja_actual,
            "fila": num_fila
        }

