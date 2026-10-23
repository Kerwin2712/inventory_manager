"""Pruebas unitarias para la opción 'Recordar usuario' en LoginView."""
import pytest
from unittest.mock import patch, MagicMock

from core.database import set_setting, get_setting
from ui.views.login_view import LoginView


def test_login_view_defecto_sin_usuario_guardado(db_temporal):
    """Si no hay usuario guardado, el campo usuario está vacío y tiene autofocus."""
    set_setting("login_remember_user", "1")
    set_setting("login_last_username", "")

    login = LoginView()
    body = login.get_body()

    assert login.username_input.value == ""
    assert login.username_input.autofocus is True
    assert login.password_input.autofocus is False
    assert login.recordar_checkbox.value is True


def test_login_view_con_usuario_guardado_pone_foco_en_clave(db_temporal):
    """Si hay usuario recordado, lo precarga y pone el foco automáticamente en la clave."""
    set_setting("login_remember_user", "1")
    set_setting("login_last_username", "admin_caja")

    login = LoginView()
    body = login.get_body()

    assert login.username_input.value == "admin_caja"
    assert login.username_input.autofocus is False
    assert login.password_input.autofocus is True
    assert login.recordar_checkbox.value is True


def test_handle_login_guarda_usuario_si_recordar_activo(db_temporal):
    """Al iniciar sesión exitosamente con checkbox activo, guarda el usuario."""
    login = LoginView()
    login.get_body()
    login.username_input.value = "cajero_1"
    login.password_input.value = "clave123"
    login.recordar_checkbox.value = True

    with patch("ui.views.login_view.authenticate_user", return_value={"username": "cajero_1", "role": "Vendedor"}):
        login.handle_login(MagicMock())

    assert get_setting("login_remember_user") == "1"
    assert get_setting("login_last_username") == "cajero_1"
    assert login.username_input.value == "cajero_1"
    assert login.password_input.value == ""


def test_handle_login_olvida_usuario_si_recordar_inactivo(db_temporal):
    """Al iniciar sesión con checkbox desmarcado, limpia el usuario recordado."""
    set_setting("login_remember_user", "1")
    set_setting("login_last_username", "usuario_viejo")

    login = LoginView()
    login.get_body()
    login.username_input.value = "nuevo_usuario"
    login.password_input.value = "clave123"
    login.recordar_checkbox.value = False

    with patch("ui.views.login_view.authenticate_user", return_value={"username": "nuevo_usuario", "role": "Vendedor"}):
        login.handle_login(MagicMock())

    assert get_setting("login_remember_user") == "0"
    assert get_setting("login_last_username") == ""
    assert login.username_input.value == ""
    assert login.password_input.value == ""
