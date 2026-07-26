"""Configuración por entorno: SUPABASE_URL y SUPABASE_KEY.

Las lee, en este orden, de: variables de entorno, `.env` (desarrollo local) y
`st.secrets` (Streamlit Community Cloud, donde no hay `.env` y los secretos se
configuran en su interfaz web). Al ser una fuente más de pydantic-settings, todo
el que ya construye `Settings()` —la CLI, la UI, las pruebas— funciona igual en
los dos entornos sin cambiar una línea.
"""

import sys
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class SecretosDeStreamlit(PydanticBaseSettingsSource):
    """Lee los valores de ``st.secrets``; vacía si la app no corre bajo Streamlit."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        # Solo si el proceso ya importó streamlit (la UI lo hace antes que esto):
        # así la CLI no paga el import, que es lento.
        modulo = sys.modules.get("streamlit")
        if modulo is None:
            return None, field_name, False
        try:
            # st.secrets revienta (no devuelve vacío) si no hay secrets.toml en
            # ningún lado: correr la UI en local sin secretos es normal.
            # Las claves van en mayúsculas (SUPABASE_URL), como en .env.
            valor = modulo.secrets.get(field_name.upper())
        except Exception:
            return None, field_name, False
        return valor, field_name, False

    def __call__(self) -> dict[str, Any]:
        valores: dict[str, Any] = {}
        for nombre, campo in self.settings_cls.model_fields.items():
            valor, clave, complejo = self.get_field_value(campo, nombre)
            if valor is not None:
                valores[clave] = self.prepare_field_value(nombre, campo, valor, complejo)
        return valores


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str
    supabase_key: str

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """`st.secrets` de último: en local siempre gana el `.env` de la máquina."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            SecretosDeStreamlit(settings_cls),
        )
