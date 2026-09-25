from dataclasses import dataclass, field
from datetime import datetime


# ─── Normalizadores compartidos de los campos nuevos de inventario ───────────
# Viven en el dominio (`core`) para que el servicio y la dataclass apliquen
# exactamente las mismas reglas sin que `core` dependa de `services`.

def normalizar_costo(valor, etiqueta: str = "costo") -> float | None:
    """Normaliza un COSTO del negocio (distinto del precio de venta).

    `None` y la cadena vacía significan "sin costo registrado" → `None`.
    Acepta int/float/str (con coma o punto decimal). Rechaza no numéricos y
    negativos con `ValueError` de prefijo `ERR_PROD_COSTO`.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ValueError(f"ERR_PROD_COSTO: El {etiqueta} debe ser un número válido.")
    if isinstance(valor, str):
        crudo = valor.strip().replace(",", ".")
        if not crudo:
            return None
        valor = crudo
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"ERR_PROD_COSTO: El {etiqueta} debe ser un número válido.")
    if numero < 0:
        raise ValueError(f"ERR_PROD_COSTO: El {etiqueta} no puede ser negativo.")
    return numero


def validar_costo_obligatorio(existencia, costo_usd_efectivo) -> None:
    """Regla de negocio: todo producto con existencia (>= 1 unidad) debe tener
    registrado su Costo USD Efectivo. `costo_usd_bcv` es siempre opcional."""
    try:
        cantidad = float(existencia or 0.0)
    except (TypeError, ValueError):
        cantidad = 0.0
    if cantidad >= 1 and costo_usd_efectivo is None:
        raise ValueError(
            "ERR_PROD_COSTO: El producto tiene existencia, por lo que un "
            "administrador debe registrar el Costo USD Efectivo antes de guardarlo."
        )


def normalizar_alerta_stock_minimo(valor) -> int | None:
    """Normaliza el umbral de alerta propio del producto: entero >= 0 o `None`.

    Acepta enteros y cadenas enteras (`"5"`). Rechaza decimales no enteros,
    texto no numérico y negativos con `ValueError` de prefijo `ERR_PROD_ALERTA`.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ValueError("ERR_PROD_ALERTA: La alerta de stock mínimo debe ser un número entero.")
    if isinstance(valor, str):
        crudo = valor.strip().replace(",", ".")
        if not crudo:
            return None
        valor = crudo
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError("ERR_PROD_ALERTA: La alerta de stock mínimo debe ser un número entero.")
    if numero != int(numero):
        raise ValueError(
            "ERR_PROD_ALERTA: La alerta de stock mínimo debe ser un número entero, sin decimales."
        )
    entero = int(numero)
    if entero < 0:
        raise ValueError("ERR_PROD_ALERTA: La alerta de stock mínimo no puede ser negativa.")
    return entero

@dataclass
class Cliente:
    """Modelo de dominio para la Cartera de Clientes (Sección 1.2 ERS)."""
    nombre_razon_social: str
    cedula_rif: str
    direccion: str = ""
    telefono: str = ""
    email: str | None = None
    id: int | None = None

    def __post_init__(self):
        self.validar_reglas_negocio()

    def validar_reglas_negocio(self):
        """Aplica la Regla de Negocio Obligatoria RNO-CLI-01."""
        self.nombre_razon_social = (self.nombre_razon_social or "").strip()
        self.cedula_rif = (self.cedula_rif or "").strip()
        self.direccion = (self.direccion or "").strip()
        self.telefono = (self.telefono or "").strip()
        if self.email:
            self.email = self.email.strip()

        if not self.nombre_razon_social or not self.cedula_rif:
            raise ValueError(
                "RNO-CLI-01: El cliente no contiene datos válidos. "
                "Los campos Nombre/Razón Social y Cédula/RIF no pueden estar vacíos."
            )


@dataclass
class Proveedor:
    """Modelo de dominio para la Cartera de Proveedores (Sección 1.3 ERS)."""
    telefono: str
    nombre_empresa: str | None = None
    agente_contacto: str | None = None
    email: str | None = None
    rif: str | None = None
    categoria_descripcion: str | None = None
    adjuntos_digitales: list[str] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self):
        self.validar_reglas_negocio()

    def validar_reglas_negocio(self):
        """Aplica la Regla de Negocio Obligatoria RNO-PROV-01."""
        tel = (self.telefono or "").strip()
        empresa = (self.nombre_empresa or "").strip()
        agente = (self.agente_contacto or "").strip()
        rif_val = (self.rif or "").strip()

        self.telefono = tel
        self.nombre_empresa = empresa if empresa else None
        self.agente_contacto = agente if agente else None
        self.rif = rif_val if rif_val else None

        if self.email:
            self.email = self.email.strip()
        if self.categoria_descripcion:
            self.categoria_descripcion = self.categoria_descripcion.strip()

        if not self.rif:
            raise ValueError("RNO-PROV-01: El campo Cédula / RIF es obligatorio para el proveedor.")
        if not self.nombre_empresa:
            raise ValueError("RNO-PROV-01: El Nombre / Razón Social de la Empresa es obligatorio.")
        if not self.telefono:
            raise ValueError("RNO-PROV-01: El número de teléfono de contacto es obligatorio.")


@dataclass
class Producto:
    """Modelo de dominio para el Inventario con 12 campos exactos (Sección 2 ERS)."""
    # 1. Código de Producto (Clave Primaria Alfanumérica)
    codigo_producto: str
    # 2. Referencia (Nomenclatura secundaria de fábrica)
    referencia: str
    # 3. Departamento (Categoría macro)
    departamento: str
    # 4. Descripción General (Especificaciones amplias)
    descripcion_general: str
    # 5. Marca (Fabricante o marca comercial)
    marca: str
    # 6. Precio en Dólares ($) (Float / Decimal base)
    precio_dolares: float
    # 8. Proveedor (ID o Llave foránea enlazada)
    proveedor_id: int | str | None = None
    # 9. Fecha de Última Modificación (Timestamp automático)
    fecha_ultima_modificacion: str | None = None
    # 10. Existencia / Stock (Entero o Decimal)
    existencia: float = 0.0
    # 11. Código de Barras (Escáner óptico)
    codigo_barras: str | None = None
    # 12. Nombre de Referencia Corto / Descripción Corta (Máximo 30 caracteres para notas impresas)
    nombre_referencia_corto: str = ""
    # Sub-Departamento (hijo del Departamento en el catálogo jerárquico)
    sub_departamento: str | None = None
    # Costo USD Efectivo: lo que le cuesta al negocio adquirir el producto.
    # NO es un precio de venta; obligatorio si hay existencia (>= 1 unidad).
    costo_usd_efectivo: float | None = None
    # Costo USD BCV: costo de referencia para la vía BCV. Siempre opcional.
    costo_usd_bcv: float | None = None
    # Umbral de alerta de stock propio del producto (entero) o None
    alerta_stock_minimo: int | None = None
    # ID opcional de registro en SQLite
    id: int | None = None

    def __post_init__(self):
        self.validar_campos()

    def validar_campos(self):
        """Valida formatos y trunca nombre_referencia_corto si excede 30 caracteres."""
        self.codigo_producto = (self.codigo_producto or "").strip()
        self.referencia = (self.referencia or "").strip()
        self.departamento = (self.departamento or "").strip()
        self.descripcion_general = (self.descripcion_general or "").strip()
        self.marca = (self.marca or "").strip()
        
        if self.codigo_barras:
            self.codigo_barras = self.codigo_barras.strip()

        # Validación del campo obligatorio de 30 caracteres máximo para notas físicas
        corto = (self.nombre_referencia_corto or "").strip()
        if not corto:
            # Si no se proporciona un nombre corto, tomar los primeros 30 caracteres de la descripción general
            corto = self.descripcion_general[:30].strip()
        elif len(corto) > 30:
            corto = corto[:30].strip()
            
        self.nombre_referencia_corto = corto

        # Jerarquía y campos administrativos nuevos
        sub = (self.sub_departamento or "").strip()
        self.sub_departamento = sub or None
        self.costo_usd_efectivo = normalizar_costo(self.costo_usd_efectivo, "Costo USD Efectivo")
        self.costo_usd_bcv = normalizar_costo(self.costo_usd_bcv, "Costo USD BCV")
        self.alerta_stock_minimo = normalizar_alerta_stock_minimo(self.alerta_stock_minimo)
        validar_costo_obligatorio(self.existencia, self.costo_usd_efectivo)

        if not self.fecha_ultima_modificacion:
            self.fecha_ultima_modificacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 7. Precio en BCV ($) - Campo calculado dinámicamente en tiempo de ejecución
    def calcular_precio_bcv(self, tasa_bcv: float) -> float:
        """Calcula el precio del producto en Bolívares / Tasa BCV dinámicamente."""
        if tasa_bcv <= 0:
            return 0.0
        return round(self.precio_dolares * tasa_bcv, 2)
