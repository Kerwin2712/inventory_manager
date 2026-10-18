"""Diálogo genérico de confirmación por clave del usuario.

Toda acción destructiva o sensible debería poder exigir la clave de la cuenta
con la que está abierta la sesión. Para que no haya un diálogo de clave por
acción (y seis sitios donde olvidarse de enmascarar el campo), este componente
es agnóstico de la acción: recibe el título, el mensaje que ENUNCIA qué se va a
hacer, el verificador y el callback de éxito.

La verificación entra por INYECCIÓN (`verificar_clave`), igual que las fuentes
de datos de `selector_departamentos`: el componente no sabe de usuarios ni de
base de datos, así que se puede probar con un verificador falso y la vista
cablea el real (`services.user_service.authenticate_user`, que compara con
`core.security.verify_password` contra el `password_hash` almacenado).

REGLA DE SEGURIDAD — la clave tecleada NO SE REGISTRA EN NINGÚN LADO: no se
escribe en un log, ni en un snackbar, ni en el texto de un error, ni se guarda
en un atributo del componente más allá del propio campo de texto, que además se
vacía después de cada intento. El mensaje de error es siempre el mismo texto
genérico (`MENSAJE_ERROR_GENERICO`): no se distingue "clave vacía" de "clave
equivocada" de "usuario sin sesión", porque cada distinción le dice algo a
quien está probando claves ajenas.
"""
import flet as ft

# Único mensaje de error del diálogo (ver la regla de seguridad del encabezado).
MENSAJE_ERROR_GENERICO = "Clave incorrecta"


class DialogoClave:
    """Pide la clave del usuario y, solo si es correcta, ejecuta la acción.

    Parámetros:
      - `titulo` / `mensaje`: qué se va a hacer, en palabras del usuario. El
        mensaje debe enunciar el objeto exacto (el código del ítem, o cuántos
        ítems tiene el lote) para que nadie entregue su clave a ciegas.
      - `verificar_clave`: callable `(clave: str) -> bool`. Cualquier excepción
        que lance se trata como clave incorrecta (criterio fail-closed: ante un
        fallo de la verificación no se borra nada).
      - `on_exito`: callable `(e)` con la acción ya autorizada.
      - `on_cerrar`: callable `(e)` que cierra el diálogo en la pila de la
        página. Lo invoca el componente al cancelar y antes del éxito, porque
        el cierre es responsabilidad de quien apiló el diálogo (en Flet 0.86 va
        por `page.pop_dialog()`, ver `InventarioView._close_dialog`).
    """

    def __init__(
        self,
        titulo: str,
        mensaje: str,
        verificar_clave,
        on_exito,
        on_cerrar=None,
        paleta: dict | None = None,
        etiqueta_confirmar: str = "Confirmar",
        icono=ft.Icons.LOCK_OUTLINE_ROUNDED,
        color_confirmar=None,
    ):
        p = paleta or {}
        texto = p.get("texto", ft.Colors.BLACK)
        subtexto = p.get("subtexto", ft.Colors.GREY_600)
        borde = p.get("borde", ft.Colors.GREY_400)
        acento = p.get("acento", ft.Colors.BLUE_600)
        fondo = p.get("fondo")

        self._verificar_clave = verificar_clave
        self._on_exito = on_exito
        self._on_cerrar = on_cerrar

        # Campo enmascarado con opción de revelar: el usuario necesita poder
        # comprobar lo que escribió sin que la clave quede a la vista por
        # defecto en una pantalla de mostrador.
        self.campo = ft.TextField(
            label="Clave de su usuario",
            password=True,
            can_reveal_password=True,
            autofocus=True,
            width=320,
            color=texto, border_color=borde, focused_border_color=acento,
            border_radius=12,
            on_submit=self.confirmar,
        )
        self.error = ft.Text("", color=ft.Colors.RED_400, size=12, weight=ft.FontWeight.BOLD)

        self.boton_cancelar = ft.TextButton("Cancelar", on_click=self.cancelar)
        self.boton_confirmar = ft.Button(
            etiqueta_confirmar,
            style=ft.ButtonStyle(
                bgcolor=color_confirmar or ft.Colors.RED_600,
                color=ft.Colors.WHITE,
                shape=ft.RoundedRectangleBorder(radius=12),
            ),
            on_click=self.confirmar,
        )

        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(icono, color=ft.Colors.RED_400),
                ft.Text(titulo, color=texto),
            ], spacing=10),
            content=ft.Column([
                ft.Text(mensaje, color=texto, size=13, no_wrap=False),
                ft.Text(
                    "Escriba la clave de la cuenta con la que inició sesión para autorizar la acción.",
                    color=subtexto, size=12, no_wrap=False,
                ),
                self.campo,
                self.error,
            ], spacing=10, tight=True, width=360),
            actions=[self.boton_cancelar, self.boton_confirmar],
            bgcolor=fondo,
            # El componente viaja pegado a su diálogo para que la vista (y las
            # pruebas) puedan llegar al campo desde el control apilado.
            data=self,
        )

    # ── Acciones ─────────────────────────────────────────────────────────────
    def confirmar(self, e=None):
        """Verifica la clave: si es correcta cierra y ejecuta; si no, se queda
        abierto con el mensaje genérico. Devuelve True si autorizó."""
        clave = self.campo.value or ""
        try:
            autorizado = bool(self._verificar_clave(clave))
        except Exception:
            # Fail-closed: si la verificación no se pudo completar, no se
            # autoriza nada. Tampoco se expone el motivo (ni la clave).
            autorizado = False

        # El valor tecleado se descarta en cuanto se usó, en los dos caminos:
        # no debe quedar residiendo en el árbol de controles.
        self._olvidar_clave()

        if not autorizado:
            self.error.value = MENSAJE_ERROR_GENERICO
            self._refrescar(e)
            return False

        self.error.value = ""
        if self._on_cerrar is not None:
            self._on_cerrar(e)
        if self._on_exito is not None:
            self._on_exito(e)
        return True

    def cancelar(self, e=None):
        """Cancelar cierra sin ejecutar nada."""
        self._olvidar_clave()
        self.error.value = ""
        if self._on_cerrar is not None:
            self._on_cerrar(e)

    # ── Internos ─────────────────────────────────────────────────────────────
    def _olvidar_clave(self):
        self.campo.value = ""

    def _refrescar(self, e=None):
        """Repinta el diálogo sin exigir una `page` viva (modo headless)."""
        try:
            self.dialogo.update()
        except (RuntimeError, AttributeError, AssertionError):
            pass


def construir_dialogo_clave(**kwargs) -> ft.AlertDialog:
    """Atajo para quien solo quiere el `AlertDialog` listo para apilar.

    El componente queda accesible en `dialogo.data` (mismo objeto que devolver
    `DialogoClave`), por si hace falta llegar al campo o forzar `confirmar()`.
    """
    return DialogoClave(**kwargs).dialogo
