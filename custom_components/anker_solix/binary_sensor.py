"""Binary sensor platform for anker_solix."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from random import randrange
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_EXCLUDE,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALLOW_TESTMODE,
    ATTRIBUTION,
    CREATE_ALL_ENTITIES,
    DOMAIN,
    TEST_NUMBERVARIANCE,
)
from .coordinator import AnkerSolixDataUpdateCoordinator
from .entity import (
    AnkerSolixEntityFeature,
    AnkerSolixEntityRequiredKeyMixin,
    AnkerSolixEntityType,
    get_AnkerSolixAccountInfo,
    get_AnkerSolixDeviceInfo,
    get_AnkerSolixSystemInfo,
)
from .solixapi.apitypes import SolixDeviceType


@dataclass(frozen=True)
class AnkerSolixBinarySensorDescription(
    BinarySensorEntityDescription, AnkerSolixEntityRequiredKeyMixin
):
    """Binary Sensor entity description with optional keys."""

    force_creation: bool = False
    # Use optionally to provide function for value calculation or lookup of nested values
    value_fn: Callable[[dict, str], bool | None] = lambda d, jk: d.get(jk)
    attrib_fn: Callable[[dict], dict | None] = lambda d: None
    exclude_fn: Callable[[set, dict], bool] = lambda s, _: False


DEVICE_SENSORS = [
    AnkerSolixBinarySensorDescription(
        key="wifi_connection",
        translation_key="wifi_connection",
        json_key="wifi_online",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        attrib_fn=lambda d: {
            "wifi_ssid": d.get("wifi_name"),
            "wifi_signal": " ".join([d.get("wifi_signal") or "--", PERCENTAGE]),
            "rssi": " ".join(
                [d.get("rssi") or "--", SIGNAL_STRENGTH_DECIBELS_MILLIWATT]
            ),
            "bt_mac": d.get("bt_ble_mac"),
            "wireless_type": d.get("wireless_type"),
        },
        exclude_fn=lambda s, d: not ({d.get("type")} - s),
    ),
    AnkerSolixBinarySensorDescription(
        key="ota_update",
        translation_key="ota_update",
        json_key="is_ota_update",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=BinarySensorDeviceClass.UPDATE,
        exclude_fn=lambda s, d: not ({d.get("type")} - s),
        attrib_fn=lambda d: {
            "ota_version": d.get("ota_version") or None,
            "ota_components": d.get("ota_children") or [],
        },
    ),
]

SITE_SENSORS = [
    AnkerSolixBinarySensorDescription(
        key="site_admin",
        translation_key="site_admin",
        json_key="site_admin",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    AnkerSolixBinarySensorDescription(
        key="heating",
        translation_key="heating",
        json_key="heating",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda d, jk: (d.get("feature_switch") or {}).get(jk),
        entity_category=EntityCategory.DIAGNOSTIC,
        exclude_fn=lambda s, d: not ({d.get("site_type")} - s),
    ),
    AnkerSolixBinarySensorDescription(
        key="micro_inverter_power_exceed",
        translation_key="micro_inverter_power_exceed",
        json_key="micro_inverter_power_exceed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d, jk: (d.get("feature_switch") or {}).get(jk),
        entity_category=EntityCategory.DIAGNOSTIC,
        exclude_fn=lambda s, d: not ({d.get("site_type")} - s),
    ),
    AnkerSolixBinarySensorDescription(
        key="offgrid_with_micro_inverter_alert",
        translation_key="offgrid_with_micro_inverter_alert",
        json_key="offgrid_with_micro_inverter_alert",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d, jk: (d.get("feature_switch") or {}).get(jk),
        entity_category=EntityCategory.DIAGNOSTIC,
        exclude_fn=lambda s, d: not ({d.get("site_type")} - s),
    ),
]

ACCOUNT_SENSORS = [
    AnkerSolixBinarySensorDescription(
        key="has_unread_msg",
        translation_key="has_unread_msg",
        json_key="has_unread_msg",
        # entity_category=EntityCategory.DIAGNOSTIC,
    ),
    # This should be shown only when testmode is active
    AnkerSolixBinarySensorDescription(
        key="use_files",
        translation_key="use_files",
        json_key="use_files",
        entity_category=EntityCategory.DIAGNOSTIC,
        exclude_fn=lambda d, _: not ALLOW_TESTMODE,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor platform."""

    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    entities = []

    if coordinator and hasattr(coordinator, "data") and coordinator.data:
        # create entity based on type of entry in coordinator data, which consolidates the api.sites, api.devices and api.account dictionaries
        # the coordinator.data dict key is either account nickname, a site_id or device_sn and used as context for the entity to lookup its data
        # manually register parent devices to avoid core warning while processing first component setup with account via device that may not exist yet
        device_registry = dr.async_get(hass)
        for context, data in coordinator.data.items():
            if (data_type := data.get("type")) == SolixDeviceType.SYSTEM.value:
                # Unique key for site_id entry in data
                entity_type = AnkerSolixEntityType.SITE
                entity_list = SITE_SENSORS
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers=(
                        get_AnkerSolixSystemInfo(
                            data, context, coordinator.client.api.apisession.email
                        )
                    ).get("identifiers"),
                )
            elif data_type == SolixDeviceType.ACCOUNT.value:
                # Unique key for account entry in data
                entity_type = AnkerSolixEntityType.ACCOUNT
                entity_list = ACCOUNT_SENSORS
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers=(get_AnkerSolixAccountInfo(data, context)).get(
                        "identifiers"
                    ),
                )
            else:
                # device_sn entry in data
                entity_type = AnkerSolixEntityType.DEVICE
                entity_list = DEVICE_SENSORS
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers=(
                        get_AnkerSolixDeviceInfo(
                            data, context, coordinator.client.api.apisession.email
                        )
                    ).get("identifiers"),
                )

            for description in (
                desc
                for desc in entity_list
                if bool(CREATE_ALL_ENTITIES)
                or (
                    not desc.exclude_fn(set(entry.options.get(CONF_EXCLUDE, [])), data)
                    and (
                        desc.force_creation
                        or desc.value_fn(data, desc.json_key) is not None
                    )
                )
            ):
                entity = AnkerSolixBinarySensor(
                    coordinator, description, context, entity_type
                )
                entities.append(entity)

    # create the entities from the list
    async_add_entities(entities)


class AnkerSolixBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """anker_solix binary_sensor class."""

    coordinator: AnkerSolixDataUpdateCoordinator
    entity_description: AnkerSolixBinarySensorDescription
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _unrecorded_attributes = frozenset(
        {
            "wifi_ssid",
            "wifi_signal",
            "wireless_type",
            "bt_mac",
            "site_admin",
            "rssi",
            "ota_components",
        }
    )

    def __init__(
        self,
        coordinator: AnkerSolixDataUpdateCoordinator,
        description: AnkerSolixBinarySensorDescription,
        context: str,
        entity_type: str,
    ) -> None:
        """Initialize an Anker Solix Device coordinator entity.

        The CoordinatorEntity class provides:
        should_poll
        async_update
        async_added_to_hass
        available
        """
        super().__init__(coordinator, context)

        self._attribute_name = description.key
        self._attr_unique_id = (f"{context}_{description.key}").lower()
        self.entity_description = description
        self.entity_type = entity_type
        self._attr_extra_state_attributes = None

        if self.entity_type == AnkerSolixEntityType.DEVICE:
            # get the device data from device context entry of coordinator data
            data = coordinator.data.get(context) or {}
            self._attr_device_info = get_AnkerSolixDeviceInfo(
                data, context, coordinator.client.api.apisession.email
            )
        elif self.entity_type == AnkerSolixEntityType.ACCOUNT:
            # get the account data from account context entry of coordinator data
            data = coordinator.data.get(context) or {}
            self._attr_device_info = get_AnkerSolixAccountInfo(data, context)
        else:
            # get the site info data from site context entry of coordinator data
            data = (coordinator.data.get(context, {})).get("site_info", {})
            self._attr_device_info = get_AnkerSolixSystemInfo(
                data, context, coordinator.client.api.apisession.email
            )

        self._attr_is_on = None
        self.update_state_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_state_value()
        super()._handle_coordinator_update()

    @property
    def supported_features(self) -> AnkerSolixEntityFeature:
        """Flag supported features."""
        return self._attr_supported_features

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        if (
            self.coordinator
            and (hasattr(self.coordinator, "data"))
            and self.coordinator_context in self.coordinator.data
        ):
            data = self.coordinator.data.get(self.coordinator_context)
            self._attr_extra_state_attributes = self.entity_description.attrib_fn(data)
        return self._attr_extra_state_attributes

    def update_state_value(self):
        """Update the state value of the sensor based on the coordinator data."""
        if self.coordinator and not (hasattr(self.coordinator, "data")):
            self._attr_is_on = None
        elif self.coordinator_context in self.coordinator.data:
            data = self.coordinator.data.get(self.coordinator_context)
            key = self.entity_description.json_key
            self._attr_is_on = self.entity_description.value_fn(data, key)

            # When running in Test mode, simulate some variance for entities with set device class
            if (
                self.coordinator.client.testmode()
                and TEST_NUMBERVARIANCE
                and self._attr_is_on is not None
            ):
                # value fluctuation
                self._attr_is_on = bool(randrange(2))
        else:
            self._attr_is_on = None

        # Mark sensor availability based on a sensore value
        self._attr_available = self._attr_is_on is not None
