"""Pruebas de la lectura de credenciales según el entorno.

Local (variables de entorno / .env) y Streamlit Community Cloud (st.secrets) sin
cambiar código: lo resuelve la fuente extra `SecretosDeStreamlit`.
"""

import sys
from typing import Any

import pytest
from pydantic import ValidationError

from planeacion.config.settings import Settings


class _SecretsFalso:
    """Imita `st.secrets`: un mapeo que revienta si no hay secrets.toml."""

    def __init__(self, valores: dict[str, str] | None) -> None:
        self._valores = valores

    def get(self, clave: str) -> Any:
        if self._valores is None:
            raise FileNotFoundError("No secrets found")
        return self._valores.get(clave)


class _StreamlitFalso:
    def __init__(self, valores: dict[str, str] | None) -> None:
        self.secrets = _SecretsFalso(valores)


@pytest.fixture
def sin_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin variables de entorno ni .env: el único origen posible es st.secrets."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setattr(Settings, "model_config", {**Settings.model_config, "env_file": None})


@pytest.fixture
def streamlit_falso(monkeypatch: pytest.MonkeyPatch) -> Any:
    def instalar(valores: dict[str, str] | None) -> None:
        monkeypatch.setitem(sys.modules, "streamlit", _StreamlitFalso(valores))

    return instalar


def test_lee_de_st_secrets_cuando_no_hay_entorno(sin_entorno: None, streamlit_falso: Any) -> None:
    streamlit_falso({"SUPABASE_URL": "https://cloud.supabase.co", "SUPABASE_KEY": "clave-cloud"})
    settings = Settings()
    assert settings.supabase_url == "https://cloud.supabase.co"
    assert settings.supabase_key == "clave-cloud"


def test_el_entorno_le_gana_a_st_secrets(
    monkeypatch: pytest.MonkeyPatch, sin_entorno: None, streamlit_falso: Any
) -> None:
    # En local, lo que tenga la máquina manda sobre cualquier secreto colgado.
    monkeypatch.setenv("SUPABASE_URL", "https://local.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "clave-local")
    streamlit_falso({"SUPABASE_URL": "https://cloud.supabase.co", "SUPABASE_KEY": "clave-cloud"})
    assert Settings().supabase_url == "https://local.supabase.co"


def test_sin_streamlit_importado_no_falla(sin_entorno: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # La CLI no importa streamlit: la fuente se salta y falta la credencial.
    monkeypatch.delitem(sys.modules, "streamlit", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_streamlit_sin_secrets_toml_no_rompe(sin_entorno: None, streamlit_falso: Any) -> None:
    # Correr la UI en local sin secrets.toml: st.secrets lanza, y debe dar el
    # error normal de credenciales faltantes, no la excepción de Streamlit.
    streamlit_falso(None)
    with pytest.raises(ValidationError):
        Settings()
