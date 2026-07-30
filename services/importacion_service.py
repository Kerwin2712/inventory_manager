import os
import pandas as pd
from core.database import get_connection

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
    )
    for a, b in replacements:
        k_clean = k_clean.replace(a, b)
    return k_clean

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

    conn = get_connection()
    conn.isolation_level = None  # Control de transacciones explícitas
    cursor = conn.cursor()

    hoja_actual = None
    num_fila = 0

    try:
        cursor.execute("BEGIN TRANSACTION")
        stats = {"productos": 0, "clientes": 0, "proveedores": 0}

        # ── 1. PROVEEDORES ───────────────────────────────────────────────────
        for key in ["proveedores", "proveedor"]:
            if key in sheet_map:
                hoja_actual = sheet_map[key]
                df = pd.read_excel(excel_file, sheet_name=hoja_actual).fillna("")
                for idx, row in df.iterrows():
                    num_fila = idx + 2
                    r_dict = {limpiar_clave(k): str(v).strip() for k, v in row.items()}
                    
                    empresa = (r_dict.get("razon social / empresa") or r_dict.get("empresa") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()
                    if not empresa:
                        continue  # Omitir vacíos

                    prov_id_str = r_dict.get("id") or r_dict.get("id proveedor") or r_dict.get("proveedor id") or ""
                    try:
                        prov_id = int(float(prov_id_str)) if prov_id_str and prov_id_str.replace('.','',1).isdigit() else None
                    except ValueError:
                        prov_id = None

                    contacto = r_dict.get("persona de contacto") or r_dict.get("contacto") or ""
                    telefono = r_dict.get("telefono") or ""
                    correo = r_dict.get("correo electronico") or r_dict.get("correo") or r_dict.get("email") or ""
                    desc = r_dict.get("descripcion / notas") or r_dict.get("descripcion") or r_dict.get("notas") or ""

                    if prov_id:
                        cursor.execute("""
                            INSERT OR REPLACE INTO proveedores (id, empresa, contacto, telefono, correo, descripcion, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, (prov_id, empresa, contacto, telefono, correo, desc))
                    else:
                        cursor.execute("""
                            INSERT INTO proveedores (empresa, contacto, telefono, correo, descripcion, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """, (empresa, contacto, telefono, correo, desc))

                    stats["proveedores"] += 1
                break

        # ── 2. CLIENTES ──────────────────────────────────────────────────────
        for key in ["clientes", "cliente"]:
            if key in sheet_map:
                hoja_actual = sheet_map[key]
                df = pd.read_excel(excel_file, sheet_name=hoja_actual).fillna("")
                for idx, row in df.iterrows():
                    num_fila = idx + 2
                    r_dict = {limpiar_clave(k): str(v).strip() for k, v in row.items()}

                    cedula_rif = (r_dict.get("cedula / rif") or r_dict.get("cedula rif") or r_dict.get("cedula") or r_dict.get("rif") or "").strip()
                    nombre = (r_dict.get("razon social / nombre") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()

                    if not cedula_rif and not nombre:
                        continue

                    if not cedula_rif:
                        raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): La Cédula/RIF del cliente no puede estar vacía.")

                    direccion = r_dict.get("direccion") or ""
                    telefono = r_dict.get("telefono") or ""
                    correo = r_dict.get("correo electronico") or r_dict.get("email") or r_dict.get("correo") or ""

                    cursor.execute("""
                        INSERT OR REPLACE INTO clientes (cedula_rif, nombre, direccion, telefono, correo, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (cedula_rif, nombre, direccion, telefono, correo))

                    stats["clientes"] += 1
                break

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

                codigo = (r_dict.get("codigo") or "").strip()
                nombre_corto = (r_dict.get("nombre referencia corto") or r_dict.get("nombre corto") or "").strip()

                # Si no trae código pero tiene descripción o nombre, intentamos usar el código de barras como código
                cod_barras = (r_dict.get("codigo de barra") or r_dict.get("codigo de barras") or r_dict.get("codigo barras") or "").strip()
                if not codigo and cod_barras:
                    codigo = cod_barras

                if not codigo and not nombre_corto:
                    continue

                if not codigo:
                    raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): El Código de producto no puede estar vacío.")

                if not nombre_corto:
                    nombre_corto = codigo[:30]

                referencia = r_dict.get("referencias") or r_dict.get("referencia") or ""
                departamento = r_dict.get("departamento") or r_dict.get("categoria") or "GENERAL"
                desc_gen = r_dict.get("descripcion general") or r_dict.get("descripcion") or ""
                marca = r_dict.get("marca") or ""

                precio_usd_str = r_dict.get("precio usd") or r_dict.get("precio ($)") or r_dict.get("precio") or "0"
                precio_bcv_str = r_dict.get("precio bcv") or r_dict.get("precio (bs bcv)") or "0"
                existencia_str = r_dict.get("existencia") or r_dict.get("stock") or "0"
                prov_id_str = r_dict.get("id proveedor") or r_dict.get("proveedor id") or ""
                prov_nombre = r_dict.get("proveedor") or r_dict.get("proveedor nombre") or ""

                try:
                    # Limpiar caracteres monetarios si los hay (ej: "$ 70.00")
                    precio_usd_str = str(precio_usd_str).replace("$","").replace(" ","").replace(",","").strip()
                    precio_usd = float(precio_usd_str) if precio_usd_str else 0.0
                except ValueError:
                    raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): El precio en USD '{precio_usd_str}' no es un número válido.")

                try:
                    precio_bcv_str = str(precio_bcv_str).replace("Bs","").replace("$","").replace(" ","").replace(",","").strip()
                    precio_bcv = float(precio_bcv_str) if precio_bcv_str else 0.0
                except ValueError:
                    precio_bcv = 0.0

                try:
                    existencia_str = str(existencia_str).replace(" ","").replace(",","").strip()
                    existencia = float(existencia_str) if existencia_str else 0.0
                except ValueError:
                    raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): La existencia '{existencia_str}' no es un número válido.")

                # Resolver Proveedor (por ID numérico o por Nombre)
                prov_id = None
                if prov_id_str and prov_id_str.replace('.','',1).isdigit():
                    prov_id = int(float(prov_id_str))
                elif prov_nombre:
                    # Buscar ID del proveedor por su nombre (empresa) en la BD
                    cursor.execute("SELECT id FROM proveedores WHERE LOWER(TRIM(empresa)) = LOWER(TRIM(?))", (prov_nombre,))
                    p_row = cursor.fetchone()
                    if p_row:
                        prov_id = p_row["id"]

                cursor.execute("""
                    INSERT OR REPLACE INTO productos (
                        codigo, referencia, departamento, descripcion_general, marca,
                        precio_dolares, precio_bcv, proveedor_id, existencia, codigo_barras,
                        nombre_referencia_corto, fecha_ultima_modificacion, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (codigo, referencia, departamento, desc_gen, marca, precio_usd, precio_bcv, prov_id, existencia, cod_barras, nombre_corto))

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

