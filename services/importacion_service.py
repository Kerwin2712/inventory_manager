import os
import pandas as pd
from core.database import get_connection

def procesar_importacion_excel(ruta_archivo: str) -> dict:
    """
    Procesa un archivo Excel (.xlsx / .xls) de forma defensiva y transaccional (ACID).
    Busca pestañas 'Productos', 'Clientes' y 'Proveedores' (insensible a mayúsculas).
    Si ocurre algún error en cualquier fila o pestaña, ejecuta ROLLBACK y retorna detalles del error.
    Si todo es correcto, ejecuta COMMIT y retorna las estadísticas de renglones procesados.
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

    # Mapa de hojas insensible a mayúsculas
    sheet_map = {str(s).lower().strip(): s for s in sheet_names}

    conn = get_connection()
    conn.isolation_level = None  # Raw control de transacciones explícitas
    cursor = conn.cursor()

    hoja_actual = None
    num_fila = 0

    try:
        cursor.execute("BEGIN TRANSACTION")
        stats = {"productos": 0, "clientes": 0, "proveedores": 0}

        # ── 1. PROVEEDORES (Se procesa primero por Foreign Keys) ─────────────
        for key in ["proveedores", "proveedor"]:
            if key in sheet_map:
                hoja_actual = sheet_map[key]
                df = pd.read_excel(excel_file, sheet_name=hoja_actual).fillna("")
                for idx, row in df.iterrows():
                    num_fila = idx + 2  # Fila 1 es el encabezado de Excel
                    r_dict = {str(k).lower().strip(): str(v).strip() for k, v in row.items()}
                    
                    empresa = (r_dict.get("razón social / empresa") or r_dict.get("empresa") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()
                    if not empresa:
                        continue  # Omitir filas vacías

                    prov_id_str = r_dict.get("id") or r_dict.get("id proveedor") or r_dict.get("proveedor_id") or ""
                    try:
                        prov_id = int(float(prov_id_str)) if prov_id_str and prov_id_str.replace('.','',1).isdigit() else None
                    except ValueError:
                        prov_id = None

                    contacto = r_dict.get("persona de contacto") or r_dict.get("contacto") or ""
                    telefono = r_dict.get("teléfono") or r_dict.get("telefono") or ""
                    correo = r_dict.get("correo electrónico") or r_dict.get("correo") or r_dict.get("email") or ""
                    desc = r_dict.get("descripción / notas") or r_dict.get("descripcion") or r_dict.get("notas") or ""

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
                    r_dict = {str(k).lower().strip(): str(v).strip() for k, v in row.items()}

                    cedula_rif = (r_dict.get("cédula / rif") or r_dict.get("cedula / rif") or r_dict.get("cedula_rif") or r_dict.get("cedula") or r_dict.get("rif") or "").strip()
                    nombre = (r_dict.get("razón social / nombre") or r_dict.get("razon_social") or r_dict.get("razon social") or r_dict.get("nombre") or "").strip()

                    if not cedula_rif and not nombre:
                        continue

                    if not cedula_rif:
                        raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): La Cédula/RIF del cliente no puede estar vacía.")

                    direccion = r_dict.get("dirección") or r_dict.get("direccion") or ""
                    telefono = r_dict.get("teléfono") or r_dict.get("telefono") or ""
                    correo = r_dict.get("correo electrónico") or r_dict.get("email") or r_dict.get("correo") or ""

                    cursor.execute("""
                        INSERT OR REPLACE INTO clientes (cedula_rif, nombre, direccion, telefono, correo, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (cedula_rif, nombre, direccion, telefono, correo))

                    stats["clientes"] += 1
                break

        # ── 3. PRODUCTOS ─────────────────────────────────────────────────────
        for key in ["productos", "producto", "inventario"]:
            if key in sheet_map:
                hoja_actual = sheet_map[key]
                df = pd.read_excel(excel_file, sheet_name=hoja_actual).fillna("")
                for idx, row in df.iterrows():
                    num_fila = idx + 2
                    r_dict = {str(k).lower().strip(): str(v).strip() for k, v in row.items()}

                    codigo = (r_dict.get("código") or r_dict.get("codigo") or "").strip()
                    nombre_corto = (r_dict.get("nombre referencia corto") or r_dict.get("nombre_referencia_corto") or r_dict.get("nombre corto") or "").strip()

                    if not codigo and not nombre_corto:
                        continue

                    if not codigo:
                        raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): El Código de producto no puede estar vacío.")

                    if not nombre_corto:
                        nombre_corto = codigo

                    referencia = r_dict.get("referencia") or ""
                    departamento = r_dict.get("departamento") or r_dict.get("categoría") or r_dict.get("categoria") or "GENERAL"
                    desc_gen = r_dict.get("descripción general") or r_dict.get("descripcion general") or r_dict.get("descripcion") or ""
                    marca = r_dict.get("marca") or ""
                    cod_barras = r_dict.get("código barras") or r_dict.get("codigo_barras") or r_dict.get("codigo barras") or ""

                    precio_usd_str = r_dict.get("precio ($)") or r_dict.get("precio_dolares") or r_dict.get("precio") or "0"
                    precio_bcv_str = r_dict.get("precio (bs bcv)") or r_dict.get("precio_bcv") or "0"
                    existencia_str = r_dict.get("existencia") or r_dict.get("stock") or "0"
                    prov_id_str = r_dict.get("id proveedor") or r_dict.get("proveedor_id") or ""

                    try:
                        precio_usd = float(precio_usd_str) if precio_usd_str else 0.0
                    except ValueError:
                        raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): El precio en USD '{precio_usd_str}' no es un valor numérico válido.")

                    try:
                        precio_bcv = float(precio_bcv_str) if precio_bcv_str else 0.0
                    except ValueError:
                        precio_bcv = 0.0

                    try:
                        existencia = float(existencia_str) if existencia_str else 0.0
                    except ValueError:
                        raise ValueError(f"Hoja '{hoja_actual}' (Fila {num_fila}): La existencia/stock '{existencia_str}' no es un valor numérico válido.")

                    prov_id = None
                    if prov_id_str and prov_id_str.replace('.','',1).isdigit():
                        prov_id = int(float(prov_id_str))

                    cursor.execute("""
                        INSERT OR REPLACE INTO productos (
                            codigo, referencia, departamento, descripcion_general, marca,
                            precio_dolares, precio_bcv, proveedor_id, existencia, codigo_barras,
                            nombre_referencia_corto, fecha_ultima_modificacion, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """, (codigo, referencia, departamento, desc_gen, marca, precio_usd, precio_bcv, prov_id, existencia, cod_barras, nombre_corto))

                    stats["productos"] += 1
                break

        cursor.execute("COMMIT")
        conn.close()
        excel_file.close()

        total = stats["productos"] + stats["clientes"] + stats["proveedores"]
        if total == 0:
            return {
                "exito": True,
                "mensaje": "El archivo se leyó correctamente, pero no se encontraron pestañas o filas de datos válidos para procesar ('Productos', 'Clientes' o 'Proveedores').",
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

