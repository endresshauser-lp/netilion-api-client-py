import datetime
import unittest

import pytest

from netilion.model import NetilionObject, ClientApplication, WebHook, AssetValue, Asset, AssetValues, Unit


class TestModel:

    @pytest.fixture()
    def asset_values_created_webhook_payload(self):
        return {
            "asset": {
                "id": 1
            },
            "values": [
                {
                    "key": "k1",
                    "data": [
                        {
                            "value": 1,
                            "timestamp": "2021-09-13T09:44:21.296Z"
                        },
                        {
                            "value": 2,
                            "timestamp": "2021-09-13T09:44:21.296Z"
                        }
                    ],
                    "unit": {
                        "id": 1,
                    }
                },
                {
                    "key": "k2",
                    "data": [
                        {
                            "value": 3,
                        },
                    ],
                    "unit": {
                        "id": 2,
                    }
                },
            ]
        }

    def test_error_on_parsing_abstract_base_class(self):
        with pytest.raises(NotImplementedError):
            NetilionObject.parse_from_api({})

    def test_error_on_serializing_abstract_base_class(self):
        with pytest.raises(NotImplementedError):
            NetilionObject().serialize()

    def test_client_equality_object(self):
        app1 = ClientApplication("name", 42)
        app2 = ClientApplication("name", 42)
        assert app1 == app2

    def test_client_equality_raw(self):
        raw = {"name": "name", "id": 42, "something": -1}
        app = ClientApplication.deserialize(raw)
        assert raw == app

    def test_client_serialization(self):
        app = ClientApplication("name", 42)
        raw = {"name": "name", "id": 42}
        assert app.serialize() == raw

    def test_client_inequality_foreign_object(self):
        client = ClientApplication("name", 42)
        not_a_client = WebHook("http://host.local", ["event_a", "event_b"])
        assert client != not_a_client

    def test_asset_equality_object(self):
        asset1 = Asset(12, "abcd")
        asset2 = Asset(12, "efgh")
        assert asset1 == asset2

    def test_asset_equality_raw(self):
        asset = Asset(12, "abcd")
        raw1 = {"id": 12, "serial_number": "czs"}
        raw2 = {"id": 12}
        assert asset == raw1
        assert asset == raw2

    def test_asset_inequality_foreign_object(self):
        asset = Asset(12, "abcd")
        hook = WebHook("http://", [])
        assert asset != hook

    def test_asset_serialization(self):
        asset = Asset(12, "abcd")
        assert asset.serialize() == {"id": 12}

    def test_webhook_equality_object(self):
        hook1 = WebHook("http://host.local", ["event_a", "event_b"], api_id=42)
        hook2 = WebHook("http://host.local", ["event_a", "event_b"], api_id=42)
        assert hook1 == hook2

    def test_webhook_equality_raw(self):
        raw = {"url": "http://host.local", "event_types": ["event_a", "event_b"], "id": 42, "something": -1}
        hook = WebHook.deserialize(raw)
        assert raw == hook

    def test_webhook_equality_without_id(self):
        hook1 = WebHook("http://host.local", ["event_a", "event_b"])
        hook2 = WebHook.deserialize({"url": "http://host.local", "event_types": ["event_a", "event_b"], "id": 42})
        assert hook1 == hook2

    def test_webhook_inequality_foreign_object(self):
        hook = WebHook("http://host.local", ["event_a", "event_b"])
        not_a_hook = ClientApplication("name", 42)
        assert hook != not_a_hook

    def test_unit_serialization(self):
        unit = Unit(unit_id=123, code="parsec", name="Parsecs")
        assert unit.serialize() == {"code": "parsec"}

    def test_unit_serialization_id_only(self):
        unit = Unit(unit_id=123)
        assert unit.serialize() == {"id": 123}

    def test_unit_deserialization(self):
        unit1 = Unit.deserialize({"id": 123, "code": "parsec", "name": "Parsecs"})
        assert unit1 == Unit(unit_id=123, code="parsec", name="Parsecs")

    def test_unit_unit_by_code(self):
        unit = Unit.unit_by_code("metre_per_second")
        assert unit.code == "metre_per_second"

    def test_unit_unknown_unit_by_code(self):
        unit = Unit.unit_by_code("XYZ")
        assert unit is None

    def test_unit_equality_code(self):
        assert Unit(12) == Unit(unit_id=12)

    def test_unit_equality_id(self):
        assert Unit(code="a") == Unit(code="a")

    def test_unit_equality(self):
        unit1 = Unit.deserialize({"id": 123, "code": "parsec", "name": "Parsecs"})
        unit2 = Unit.deserialize({"id": 123, "code": "parsec", "name": "Parsècks"})
        assert unit1 == unit2

    def test_unit_inequality_id(self):
        unit1 = Unit.deserialize({"id": 123, "code": "m/s", "name": "Speed"})
        unit2 = Unit.deserialize({"id": 124, "code": "m/s", "name": "Speed"})
        assert unit1 != unit2

    def test_unit_inequality_code(self):
        unit1 = Unit.deserialize({"id": 123, "code": "m/s", "name": "Speed"})
        unit2 = Unit.deserialize({"id": 123, "code": "ft/s", "name": "Speed"})
        assert unit1 != unit2

    def test_unit_inequality(self):
        assert Unit(1) != WebHook("https://host.local", [])

    def test_unit_raises_without_id_and_code(self):
        with pytest.raises(Exception):
            Unit(None, None)

    def test_assetvalue_with_unit_instance(self):
        asset_value = AssetValue("k", Unit(1), 42)
        assert asset_value.serialize() == {"key": "k", "unit": {"id": 1}, "value": 42}

    def test_assetvalue_with_unit_raw(self):
        asset_value = AssetValue.deserialize({"key": "k", "unit": {"id": 1, "code": "code", "name": "name"}, "value": 42})
        assert asset_value.unit == Unit(1, "code", "name")

    def test_assetvalue_without_timestamp(self):
        asset_value = AssetValue("k", {"id": 1}, 42)
        assert asset_value.serialize() == {"key": "k", "unit": {"id": 1}, "value": 42}

    def test_assetvalue_with_timestamp(self):
        ts: datetime = datetime.datetime.strptime("2020-12-24T23:59:59.123Z", "%Y-%m-%dT%H:%M:%S.%f%z")
        asset_value = AssetValue("k", {"id": 1}, 42, timestamp=ts)
        assert asset_value.serialize() == {"key": "k", "unit": {"id": 1}, "value": 42, "timestamp": "2020-12-24T23:59:59.123Z"}

    def test_assetvalue_deserialization_with_timestamp(self):
        asset_value = AssetValue.deserialize({"key": "k", "unit": {"id": 1}, "value": 1, "timestamp": "2021-09-13T08:33:05.178Z"})
        assert asset_value.timestamp == datetime.datetime(2021, 9, 13, 8, 33, 5, 178000, tzinfo=datetime.timezone.utc)

    def test_assetvalue_deserialization_with_bad_timestamp(self):
        # no timezone
        asset_value = AssetValue.deserialize({"key": "k", "unit": {"id": 1}, "value": 1, "timestamp": "2021-09-13T08:33:05.178"})
        assert asset_value.timestamp is None

    def test_assetvalue_deserialize_timestamp(self):
        assert AssetValue.deserialize_timestamp("2021-09-13T08:33:05.178Z") == datetime.datetime(2021, 9, 13, 8, 33, 5, 178000, tzinfo=datetime.timezone.utc)

    def test_assetvalue_deserialize_empty_timestamp(self):
        assert AssetValue.deserialize_timestamp(None) is None

    def test_assetvalue_equality_raw(self):
        assert AssetValue("key1", {"id": 1234, "code": "c", "name": "n"}, 15) == \
               {"key": "key1", "unit": {"id": 1234, "code": "c", "name": "n"}, "value": 15}

    def test_assetvalue_equality(self):
        av1 = AssetValue("k", {"id": 1234, "code": "c", "name": "n"}, 42)
        av2 = AssetValue("k", {"id": 1234, "code": "c", "name": "n"}, 42)
        assert av1 == av2

    def test_assetvalue_inequality(self):
        assert AssetValue("key", Unit(1, "c", "n"), 42) != WebHook("https://", ["event"])

    def test_assetvalue_inequality_unit(self):
        av1 = AssetValue("k", {"id": 5678, "code": "c1", "name": "n"}, 42)
        av2 = AssetValue("k", {"id": 1234, "code": "c2", "name": "ñ"}, 42)
        assert av1 != av2

    def test_incomingassetvalues_serialize_empty_values(self):
        incoming = AssetValues(Asset(1), [])
        assert incoming.serialize() == {"asset": {"id": 1}, "values": []}

    def test_incomingassetvalues_serialize(self, asset_values_created_webhook_payload):
        # 2021-09-13T09:44:21.296Z
        true_ts = datetime.datetime(2021, 9, 13, 9, 44, 21, 296*1000, tzinfo=datetime.timezone.utc)
        incoming = AssetValues(Asset(1), [
                                            AssetValue("k1", {'id': 1}, 1, true_ts),
                                            AssetValue("k1", {'id': 1}, 2, true_ts),
                                            AssetValue("k2", {'id': 2}, 3, None)
        ])
        assert incoming.serialize() == asset_values_created_webhook_payload

    def test_incomingassetvalues_deserialize(self, asset_values_created_webhook_payload):
        incoming = AssetValues.parse_from_api({"content": asset_values_created_webhook_payload})
        assert Asset(1) == incoming.asset

        assert AssetValue("k1", {"id": 1}, 1) in incoming.values
        assert AssetValue("k1", {"id": 1}, 2) in incoming.values
        assert AssetValue("k2", {"id": 2}, 3) in incoming.values