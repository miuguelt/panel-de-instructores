"""Verifica la política de edición de cortes con identidades de prueba."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.permisos import puede_gestionar_corte


@pytest.mark.parametrize(
    'autenticado,administrador,propietario,activo,existe,permitido',
    [
        (False, False, True, True, True, False),
        (True, False, True, True, False, False),
        (True, False, True, True, True, True),
        (True, False, False, True, True, False),
        (True, True, False, True, True, True),
        (True, False, True, False, True, False),
        (True, True, False, False, True, False),
    ],
)
def test_solo_el_responsable_o_administrador_edita_un_corte_activo(
    autenticado, administrador, propietario, activo, existe, permitido,
):
    usuario = SimpleNamespace(id=1, is_authenticated=autenticado, es_admin=administrador)
    corte = SimpleNamespace(instructor_id=1 if propietario else 2, esta_activo=activo)
    with patch('app.services.permisos.current_user', usuario):
        assert puede_gestionar_corte(corte if existe else None) is permitido
