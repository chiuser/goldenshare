import unittest

from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


class SensorTagsTests(unittest.TestCase):
    def test_build_sensor_tags_uses_registered_enum_values(self) -> None:
        self.assertEqual(
            build_sensor_tags(
                sensor_domain=SensorDomain.QUOTE_DATA,
                target_layer=SensorTargetLayer.RAW_SILVER,
                role=SensorRole.ASSET_UPDATE,
            ),
            {
                SENSOR_DOMAIN_TAG: "quote_data",
                SENSOR_TARGET_LAYER_TAG: "raw_silver",
                SENSOR_ROLE_TAG: "asset_update",
            },
        )

    def test_build_sensor_tags_accepts_registered_string_values(self) -> None:
        self.assertEqual(
            build_sensor_tags(
                sensor_domain="platform_observability",
                target_layer="platform",
                role="run_status_notification",
            ),
            {
                SENSOR_DOMAIN_TAG: "platform_observability",
                SENSOR_TARGET_LAYER_TAG: "platform",
                SENSOR_ROLE_TAG: "run_status_notification",
            },
        )

    def test_build_sensor_tags_rejects_unregistered_values(self) -> None:
        with self.assertRaises(ValueError):
            build_sensor_tags(
                sensor_domain="ad_hoc",
                target_layer=SensorTargetLayer.PLATFORM,
                role=SensorRole.RUN_STATUS_NOTIFICATION,
            )
        with self.assertRaises(ValueError):
            build_sensor_tags(
                sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
                target_layer="ad_hoc",
                role=SensorRole.RUN_STATUS_NOTIFICATION,
            )
        with self.assertRaises(ValueError):
            build_sensor_tags(
                sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
                target_layer=SensorTargetLayer.PLATFORM,
                role="ad_hoc",
            )


if __name__ == "__main__":
    unittest.main()
