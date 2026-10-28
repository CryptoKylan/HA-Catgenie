"""Config flow for CatGenie A.I. (phone number + SMS code login)."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from catgenie import CatGenieAuth, CatGenieAuthenticationError, CatGenieException
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult

from .const import (
    CONF_ACCOUNT_ID,
    CONF_CODE,
    CONF_COUNTRY_CODE,
    CONF_PHONE,
    CONF_REFRESH_TOKEN,
    CONF_TENANT_ID,
    CONF_USER_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_COUNTRY_CODE): str,
        vol.Required(CONF_PHONE): str,
    }
)
CODE_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


class CatGenieConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the CatGenie A.I. login flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._country_code: int | None = None
        self._phone: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the phone number and trigger the SMS."""
        errors: dict[str, str] = {}
        if user_input is not None:
            country = re.sub(r"\D", "", user_input[CONF_COUNTRY_CODE])
            # National trunk prefixes (a leading 0) are not part of the number
            # the app sends.
            phone = re.sub(r"\D", "", user_input[CONF_PHONE]).lstrip("0")
            if not country or not phone:
                errors["base"] = "invalid_phone"
            else:
                auth = CatGenieAuth()
                try:
                    await auth.request_login_code(int(country), phone)
                except CatGenieException:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Unexpected error requesting login code")
                    errors["base"] = "unknown"
                finally:
                    await auth.async_close()
                if not errors:
                    self._country_code = int(country)
                    self._phone = phone
                    return await self.async_step_code()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_code(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange the SMS code for credentials."""
        errors: dict[str, str] = {}
        if user_input is not None and self._country_code and self._phone:
            auth = CatGenieAuth()
            creds = None
            try:
                creds = await auth.login(
                    self._country_code, self._phone, user_input[CONF_CODE].strip()
                )
            except CatGenieAuthenticationError:
                errors["base"] = "invalid_auth"
            except CatGenieException:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during login")
                errors["base"] = "unknown"
            finally:
                await auth.async_close()

            if creds is not None:
                unique_id = creds.account_id or creds.user_id
                if not creds.refresh_token or not unique_id:
                    errors["base"] = "invalid_auth"
                else:
                    data = {
                        CONF_REFRESH_TOKEN: creds.refresh_token,
                        CONF_ACCOUNT_ID: creds.account_id,
                        CONF_USER_ID: creds.user_id,
                        CONF_TENANT_ID: creds.tenant_id,
                    }
                    await self.async_set_unique_id(unique_id)
                    if self.source == SOURCE_REAUTH:
                        self._abort_if_unique_id_mismatch(reason="wrong_account")
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(), data_updates=data
                        )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="CatGenie A.I.", data=data)

        return self.async_show_form(
            step_id="code", data_schema=CODE_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication when the stored login stops working."""
        return await self.async_step_user()
