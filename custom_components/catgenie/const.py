"""Constants for the CatGenie A.I. integration."""

from datetime import timedelta

DOMAIN = "catgenie"

CONF_COUNTRY_CODE = "country_code"
CONF_PHONE = "phone"
CONF_CODE = "code"

CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCOUNT_ID = "account_id"
CONF_USER_ID = "user_id"
CONF_TENANT_ID = "tenant_id"

# Poll slowly while idle and faster while a cycle is running so progress
# stays reasonably current without hammering the vendor's cloud.
SCAN_INTERVAL_IDLE = timedelta(seconds=60)
SCAN_INTERVAL_ACTIVE = timedelta(seconds=15)
