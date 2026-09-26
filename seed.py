import sys
from core.database import init_db
from services.bcv_service import actualizar_tasa
from services.cartera_service import crear_proveedor, crear_cliente
from services.inventario_service import crear_producto

def run_seed():
    print("[INFO] Inicializando base de datos SQLite...")
    init_db()

    # 1. Establecer Tasa BCV Inicial (732.48)
    tasa_inicial = 732.48
    actualizar_tasa(tasa_inicial)
    print(f"[OK] Tasa BCV establecida en: {tasa_inicial:.2f}")

    # 2. Registrar Proveedores (RNO-PROV-01)
    print("[INFO] Registrando proveedores de prueba...")
    prov_data = [
        {
            "empresa": "Distribuidora Central C.A.",
            "rif": "J-301234567",
            "contacto": "Carlos Pérez",
            "telefono": "0414-1234567",
            "correo": "ventas@distribuidoracentral.com",
            "descripcion": "Proveedor principal de ferretería y herramientas"
        },
        {
            "empresa": "Importadora Electrónica Oriente",
            "rif": "J-309876543",
            "contacto": "Ana Gómez",
            "telefono": "0424-9876543",
            "correo": "contacto@ieoriente.com",
            "descripcion": "Distribuidor de componentes electrónicos y accesorios"
        },
        {
            "empresa": "Suministros Industriales del Sur",
            "rif": "J-305551234",
            "contacto": "Roberto Mendoza",
            "telefono": "0412-5551234",
            "correo": "info@suministrossur.com",
            "descripcion": "Suministros de papelería, empaques y consumo masivo"
        }
    ]

    proveedores = []
    for p in prov_data:
        try:
            prov = crear_proveedor(
                empresa=p["empresa"],
                contacto=p["contacto"],
                telefono=p["telefono"],
                correo=p["correo"],
                descripcion=p["descripcion"],
                rif=p["rif"],
            )
            proveedores.append(prov)
            print(f"  + Proveedor creado: ID {prov['id']} - {prov['empresa']}")
        except Exception as e:
            print(f"  - Aviso Proveedor {p['empresa']}: {e}")

    # Recuperar IDs de proveedores creados
    # Sin este cuidado, un fallo al crear proveedores degeneraba en IDs
    # inventados [1, 2, 3] que no existen: cada producto moria despues con
    # "FOREIGN KEY constraint failed" y la base quedaba sin inventario.
    p_ids = [p["id"] for p in proveedores] if proveedores else [None, None, None]

    # 3. Registrar Clientes (RNO-CLI-01)
    print("[INFO] Registrando clientes de prueba...")
    cli_data = [
        {
            "cedula_rif": "J-304567890",
            "nombre": "Inversiones El Sol C.A.",
            "direccion": "Av. Bolívar #45, Valencia",
            "telefono": "0414-1112233",
            "correo": "contacto@elsol.com"
        },
        {
            "cedula_rif": "V-14589632",
            "nombre": "Juan Alberto Morales",
            "direccion": "Urb. Los Rosales Calle 3, Caracas",
            "telefono": "0424-2223344",
            "correo": "jmorales@gmail.com"
        },
        {
            "cedula_rif": "J-401239876",
            "nombre": "Comercializadora Los Andes",
            "direccion": "Zona Industrial II, Maracay",
            "telefono": "0412-3334455",
            "correo": "ventas@losandes.com"
        },
        {
            "cedula_rif": "V-18965412",
            "nombre": "María Fernanda Silva",
            "direccion": "Av. Principal Colinas, Barquisimeto",
            "telefono": "0416-4445566",
            "correo": "mfsilva@hotmail.com"
        },
        {
            "cedula_rif": "G-200987654",
            "nombre": "Fundación Salud y Vida",
            "direccion": "Calle 10, San Cristóbal",
            "telefono": "0276-5556677",
            "correo": "contacto@saludyvida.org"
        }
    ]

    for c in cli_data:
        try:
            cli = crear_cliente(
                nombre=c["nombre"],
                cedula_rif=c["cedula_rif"],
                direccion=c["direccion"],
                telefono=c["telefono"],
                correo=c["correo"]
            )
            print(f"  + Cliente creado: {cli['cedula_rif']} - {cli['nombre']}")
        except Exception as e:
            print(f"  - Aviso Cliente {c['cedula_rif']}: {e}")

    # 4. Registrar Productos (15 productos variados)
    print("[INFO] Registrando productos variados de prueba...")
    prod_data = [
        {
            "codigo": "PROD-001",
            "referencia": "TAL-12V",
            "descripcion_general": "Taladro Inalámbrico 12V con 2 baterías de litio y cargador rápido",
            "departamento": "FERRETERIA",
            "marca": "DeWalt",
            "precio_dolares": 85.00,
            "existencia": 12.0,
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Taladro Inalámbrico 12V"
        },
        {
            "codigo": "PROD-002",
            "referencia": "JGO-DEST-6P",
            "descripcion_general": "Juego de destornilladores de precisión aislados 6 piezas",
            "departamento": "FERRETERIA",
            "marca": "Stanley",
            "precio_dolares": 15.50,
            "existencia": 25.0,
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Juego Destornilladores 6P"
        },
        {
            "codigo": "PROD-003",
            "referencia": "DISC-CORTE-4.5",
            "descripcion_general": "Disco de corte para metal 4.5 pulgadas fino extra resistente",
            "departamento": "FERRETERIA",
            "marca": "Bosch",
            "precio_dolares": 2.20,
            "existencia": 100.0,
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Disco Corte Metal 4.5 In"
        },
        {
            "codigo": "PROD-004",
            "referencia": "CINT-MET-5M",
            "descripcion_general": "Cinta métrica profesional de 5 metros con freno automático",
            "departamento": "FERRETERIA",
            "marca": "Lufkin",
            "precio_dolares": 6.80,
            "existencia": 0.0,  # Sin stock para pruebas
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Cinta Métrica 5M Prof."
        },
        {
            "codigo": "PROD-005",
            "referencia": "MULT-DIG-830",
            "descripcion_general": "Multímetro digital portátil con pantalla LCD retroiluminada",
            "departamento": "ELECTRONICA",
            "marca": "Truper",
            "precio_dolares": 18.00,
            "existencia": 8.0,
            "proveedor_id": p_ids[1],
            "nombre_referencia_corto": "Multímetro Digital LCD"
        },
        {
            "codigo": "PROD-006",
            "referencia": "CAUT-60W",
            "descripcion_general": "Cautín tipo lápiz 60W para soldadura de circuitos",
            "departamento": "ELECTRONICA",
            "marca": "Solderking",
            "precio_dolares": 9.50,
            "existencia": 15.0,
            "proveedor_id": p_ids[1],
            "nombre_referencia_corto": "Cautín Lápiz 60W"
        },
        {
            "codigo": "PROD-007",
            "referencia": "CAB-HDMI-4K-2M",
            "descripcion_general": "Cable HDMI 2.0 trenzado 4K de alta velocidad 2 metros",
            "departamento": "ELECTRONICA",
            "marca": "Ugreen",
            "precio_dolares": 5.00,
            "existencia": 40.0,
            "proveedor_id": p_ids[1],
            "nombre_referencia_corto": "Cable HDMI 4K 2M"
        },
        {
            "codigo": "PROD-008",
            "referencia": "TECL-MEC-RGB",
            "descripcion_general": "Teclado mecánico RGB gamer switches azules en español",
            "departamento": "ELECTRONICA",
            "marca": "Redragon",
            "precio_dolares": 45.00,
            "existencia": 0.0,  # Sin stock para pruebas
            "proveedor_id": p_ids[1],
            "nombre_referencia_corto": "Teclado Mecánico RGB"
        },
        {
            "codigo": "PROD-009",
            "referencia": "RES-RES-500",
            "descripcion_general": "Resma de papel tamaño carta 500 hojas 75g de alta blancura",
            "departamento": "PAPELERIA",
            "marca": "Chamex",
            "precio_dolares": 4.50,
            "existencia": 150.0,
            "proveedor_id": p_ids[2],
            "nombre_referencia_corto": "Resma Papel Carta 500H"
        },
        {
            "codigo": "PROD-010",
            "referencia": "BOL-AZU-12P",
            "descripcion_general": "Caja de bolígrafos tinta azul 1.0mm trazo suave 12 unidades",
            "departamento": "PAPELERIA",
            "marca": "Kilometrico",
            "precio_dolares": 3.00,
            "existencia": 60.0,
            "proveedor_id": p_ids[2],
            "nombre_referencia_corto": "Caja Bolígrafos Azul 12P"
        },
        {
            "codigo": "PROD-011",
            "referencia": "CARP-ARCH-OFI",
            "descripcion_general": "Carpeta archivadora oficio lomo ancho plastificada negra",
            "departamento": "PAPELERIA",
            "marca": "Norma",
            "precio_dolares": 3.80,
            "existencia": 30.0,
            "proveedor_id": p_ids[2],
            "nombre_referencia_corto": "Carpeta Archivador Oficio"
        },
        {
            "codigo": "PROD-012",
            "referencia": "CINT-EMBAL-100M",
            "descripcion_general": "Cinta transparente para embalaje pesado 48mm x 100m",
            "departamento": "EMPAQUE",
            "marca": "Tesa",
            "precio_dolares": 1.90,
            "existencia": 80.0,
            "proveedor_id": p_ids[2],
            "nombre_referencia_corto": "Cinta Embalaje 48x100M"
        },
        {
            "codigo": "PROD-013",
            "referencia": "BOMB-LED-12W",
            "descripcion_general": "Bombillo LED 12W luz blanca 6500K rosca E27 ahorrador",
            "departamento": "ILUMINACION",
            "marca": "Sylvania",
            "precio_dolares": 1.50,
            "existencia": 200.0,
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Bombillo LED 12W Blanco"
        },
        {
            "codigo": "PROD-014",
            "referencia": "REF-LED-50W",
            "descripcion_general": "Reflector LED 50W para exteriores IP66 luz fría super brillante",
            "departamento": "ILUMINACION",
            "marca": "Philips",
            "precio_dolares": 16.00,
            "existencia": 0.0,  # Sin stock para pruebas
            "proveedor_id": p_ids[0],
            "nombre_referencia_corto": "Reflector LED 50W Exterior"
        },
        {
            "codigo": "PROD-015",
            "referencia": "DISP-JABON-1L",
            "descripcion_general": "Dispensador de jabón líquido de pared 1000ml acero inoxidable",
            "departamento": "HIGIENE",
            "marca": "Kimberly",
            "precio_dolares": 22.00,
            "existencia": 10.0,
            "proveedor_id": p_ids[2],
            "nombre_referencia_corto": "Dispensador Jabón 1L"
        }
    ]

    for p in prod_data:
        try:
            prod = crear_producto(
                codigo=p["codigo"],
                referencia=p["referencia"],
                descripcion_general=p["descripcion_general"],
                departamento=p["departamento"],
                marca=p["marca"],
                precio_dolares=p["precio_dolares"],
                proveedor_id=p["proveedor_id"],
                existencia=p["existencia"],
                nombre_referencia_corto=p["nombre_referencia_corto"],
                # Todo producto con existencia exige Costo USD Efectivo; para
                # los datos de prueba se estima un margen del 30% sobre venta.
                costo_usd_efectivo=round(p["precio_dolares"] * 0.70, 2),
                rol_usuario="superadmin",
            )
            print(f"  + Producto creado: {prod['codigo']} - {prod['nombre_referencia_corto']} (Stock: {prod['existencia']}, Price $: {prod['precio_dolares']:.2f}, Bs: {prod['precio_bcv']:.2f})")
        except Exception as e:
            print(f"  - Aviso Producto {p['codigo']}: {e}")

    print("\n[ÉXITO] Base de datos poblada satisfactoriamente con datos de prueba realistas.")

if __name__ == "__main__":
    run_seed()
