from dataclasses import dataclass, field
from datetime import datetime

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

        self.telefono = tel
        self.nombre_empresa = empresa if empresa else None
        self.agente_contacto = agente if agente else None
        if self.email:
            self.email = self.email.strip()
        if self.categoria_descripcion:
            self.categoria_descripcion = self.categoria_descripcion.strip()

        # Condición A: Nombre Empresa Y Teléfono
        condicion_a = bool(empresa and tel)
        # Condición B: Agente Contacto Y Teléfono
        condicion_b = bool(agente and tel)

        if not tel or not (condicion_a or condicion_b):
            raise ValueError(
                "ERR_PROV_INS_INVALID: RNO-PROV-01 incumplida. "
                "Se requiere el número de teléfono y al menos el Nombre de la Empresa o del Agente de Contacto."
            )


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

        if not self.fecha_ultima_modificacion:
            self.fecha_ultima_modificacion = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 7. Precio en BCV ($) - Campo calculado dinámicamente en tiempo de ejecución
    def calcular_precio_bcv(self, tasa_bcv: float) -> float:
        """Calcula el precio del producto en Bolívares / Tasa BCV dinámicamente."""
        if tasa_bcv <= 0:
            return 0.0
        return round(self.precio_dolares * tasa_bcv, 2)
