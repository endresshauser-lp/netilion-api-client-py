from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import TypeVar, Generic, Optional, Union

from .error import MalformedNetilionApiResponse, BadNetilionApiPermission, GenericNetilionApiError, QuotaExceeded

# pylint: disable=invalid-name
T = TypeVar("T")


class NetilionObject(Generic[T]):
    logger = logging.getLogger(__name__)

    @classmethod
    def deserialize(cls, body) -> T:
        raise NotImplementedError

    def serialize(self) -> dict:
        raise NotImplementedError

    @classmethod
    def raise_errors(cls, payload: dict) -> None:
        if "errors" not in payload:
            return
        if not all("type" in error_entry for error_entry in payload["errors"]):
            raise MalformedNetilionApiResponse(msg=payload)
        error_types = [error["type"] for error in payload["errors"]]
        # certainly others, extend as needed
        if "not_found_no_permission" in error_types:
            raise BadNetilionApiPermission()
        elif "quota_exceeded" in error_types:
            raise QuotaExceeded(msg=payload)
        else:
            raise GenericNetilionApiError(msg=payload)

    @classmethod
    def parse_from_api(cls, response_body: dict) -> T:
        cls.raise_errors(response_body)
        try:
            return cls.deserialize(response_body)
        except KeyError as key_err:
            cls.logger.warning(f"Unable to deserialize {cls.__name__}, missing key: {key_err} :: {response_body}")
            raise MalformedNetilionApiResponse from key_err
        except Exception as err:
            cls.logger.error(err)
            raise

    @classmethod
    def parse_multiple_from_api(cls, response_body: dict, under_key: str) -> list[T]:
        cls.raise_errors(response_body)
        try:
            return [cls.parse_from_api(response_item) for response_item in response_body[under_key]]
        except Exception as err:
            cls.logger.error(err)
            raise


class ClientApplication(NetilionObject):
    name: str = None
    api_id = None

    def __init__(self, name, api_id):
        self.name = name
        self.api_id = api_id

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["name"], body["id"])

    def serialize(self) -> dict:
        return {"name": self.name, "id": self.api_id}

    def __str__(self):  # pragma: no cover
        return f"Client Application \"{self.name}\""

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.name == other.name and self.api_id == other.api_id
        elif isinstance(other, dict):
            return self.name == other.get("name") and self.api_id == other.get("id")
        else:
            return False


class WebHook(NetilionObject):
    api_id = None
    webhook_id = None
    url: str = None
    event_types: list[str] = None
    secret: str = None

    def __init__(self, url, event_types, api_id=None, secret=None):
        self.url = url
        self.event_types = event_types
        self.api_id = api_id
        self.secret = secret

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["url"], body["event_types"], body["id"], body.get("secret"))

    def serialize(self) -> dict:
        return {"url": self.url, "event_types": self.event_types}

    def __str__(self):  # pragma: no cover
        return f"WebHook <{self.url}> (events {','.join(event_type for event_type in self.event_types)})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.url == other.url and self.event_types == other.event_types
        elif isinstance(other, dict):
            return self.url == other.get("url") and self.event_types == other.get("event_types")
        else:
            return False


class Asset(NetilionObject):
    asset_id = None
    serial_number: str = None

    def __init__(self, asset_id, serial_number=None):
        self.asset_id = asset_id
        self.serial_number = serial_number

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["id"], body.get("serial_number", None))

    def serialize(self) -> dict:
        return {"id": self.asset_id}

    def __str__(self):  # pragma: no cover
        return f"Asset {self.asset_id} (serial number {self.serial_number or 'n/a'})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.asset_id == other.asset_id
        elif isinstance(other, dict):
            return self.asset_id == other.get("id")
        else:
            return False


class Unit(NetilionObject):
    unit_id: Optional[int] = None
    code: Optional[str] = None
    name: Optional[str] = None

    __allowed_units = {"degree_celsius", "metre_per_second", "gram_per_cubic_centimetre", "percent_mass",
                       "percent_volume", "degree_plato", "percent", "millimetre", "millipascal_second"}

    def __init__(self, unit_id: Optional[int] = None, code: Optional[str] = None, name: Optional[str] = None):
        if not unit_id and not code:
            raise MalformedNetilionApiResponse(msg="Requires either either ID or code to construct unit")
        self.unit_id = unit_id
        self.code = code
        self.name = name

    @classmethod
    def unit_by_code(cls, code: str) -> Optional[Unit]:
        if code in cls.__allowed_units:
            return cls(code=code)
        else:
            return None

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body.get("id", None), body.get("code", None), body.get("name", None))

    def serialize(self) -> dict:
        # prefer human-readable codes over arbitrary ids.
        if self.code:
            return {"code": self.code}
        else:
            return {"id": self.unit_id}

    def __str__(self):  # pragma: no cover
        return f"Unit {self.unit_id or 'id n/a'}, {self.code or 'code n/a'} ({self.name or 'name n/a'})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.unit_id == other.unit_id and self.code == other.code
        elif isinstance(other, dict):
            return self.unit_id == other.get("id") and self.code == other.get("code")
        else:
            return False


class AssetValue(NetilionObject):
    key: str = None
    unit: Unit = None
    value: any = None
    timestamp: Optional[datetime] = None

    def __init__(self, key: str, unit: Union[Unit, dict], value: Union[int, float], timestamp: Optional[datetime] = None):
        self.key = key
        self.value = value
        self.timestamp: Optional[datetime] = timestamp
        if isinstance(unit, Unit):
            self.unit = unit
        else:
            assert isinstance(unit, dict)
            self.unit = Unit.deserialize(unit)

    @classmethod
    def deserialize(cls, body) -> T:
        ts = None
        if "timestamp" in body:
            ts = cls.deserialize_timestamp(body.get("timestamp"))
        return cls(body["key"], body["unit"], body["value"], timestamp=ts)

    @classmethod
    def deserialize_timestamp(cls, timestamp: Optional[str]) -> Optional[datetime]:
        if not timestamp:
            return None
        try:
            if "." in timestamp:
                day_time_format = "%Y-%m-%dT%H:%M:%S.%f%z"
            else:
                day_time_format = "%Y-%m-%dT%H:%M:%S%z"
            return datetime.strptime(timestamp, day_time_format)
        except ValueError as val_err:  # pragma: no cover
            cls.logger.error(f"Unknown datetime format: {timestamp}: {val_err}")
            return None

    def serialize(self) -> dict:
        j = {"key": self.key, "unit": self.unit.serialize(), "value": self.value}
        if self.timestamp:
            utc_ts = self.timestamp.astimezone(timezone.utc)
            # python's strftime/strptime use microseconds, Netilion milliseconds
            time_to_seconds = utc_ts.strftime("%Y-%m-%dT%H:%M:%S")
            milliseconds = int(utc_ts.strftime("%f")) // 1000
            # since we convert to UTC first, we can hardcode the TZ code -- Z == "UTC"
            j["timestamp"] = f"{time_to_seconds}.{milliseconds}Z"
        return j

    def __str__(self):  # pragma: no cover
        return f"AssetValue {self.key}: {self.value} ({self.unit}, {self.timestamp or 'timestamp n/a'})"

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.key == other.key and self.unit == other.unit and self.value == other.value and self.unit == other.unit
        elif isinstance(other, dict):
            return self.key == other.get("key") and self.unit == other.get("unit") and self.value == other.get("value") and self.unit == other.get("unit")
        else:
            return False


class AssetValues(NetilionObject):
    asset: Asset = None
    values: list[AssetValue] = None

    def __init__(self, asset, values: list[AssetValue]):
        self.asset = asset
        self.values = values

    @classmethod
    def deserialize(cls, body) -> T:
        content = body["content"]
        asset = Asset(content["asset"]["id"], content["asset"].get("serial_number"))
        asset_values: list[AssetValue] = []
        for value in content["values"]:
            value_key = value["key"]
            value_datas = value["data"]
            value_unit = value["unit"]
            for value_data in value_datas:
                if "timestamp" in value_data:
                    timestamp = AssetValue.deserialize_timestamp(value_data.get("timestamp"))
                else:
                    timestamp = None
                asset_values.append(AssetValue(value_key, value_unit, value_data["value"], timestamp=timestamp))

        return cls(asset, values=asset_values)

    def serialize(self) -> dict:
        keys = {asset_value.key for asset_value in self.values}
        values = []
        # Note: this is sorted() because that makes the key order deterministic for unit-testing purposes.
        for key in sorted(keys):
            # there should now always be at least one AssetValue for this key since that's where we got the key from
            asset_values = [asset_value for asset_value in self.values if asset_value.key == key]
            key_unit = asset_values[0].unit
            key_value_data = []
            for asset_value in asset_values:
                d = {"value": asset_value.value}
                if asset_value.timestamp:
                    d["timestamp"] = asset_value.serialize().get("timestamp")
                key_value_data.append(d)
            key_values = {
                "key": key,
                "data": key_value_data,
                "unit": key_unit.serialize()
            }
            values.append(key_values)
        return {"asset": self.asset.serialize(), "values": values}

    def __str__(self):  # pragma: no cover
        return f"AssetValues ({self.asset}), {len(self.values)} values contained"

    def __eq__(self, other):
        # we assume for the moment that value order matters
        if isinstance(other, AssetValues):
            return self.asset == other.asset and self.values == other.values
        else:
            return False


class AssetValuesByKey(NetilionObject):
    value: any = None
    timestamp: datetime = None

    def __init__(self, value: Union[int, float], timestamp: datetime = None):
        self.value = value
        self.timestamp:datetime = timestamp

    @classmethod
    def deserialize(cls, body) -> T:
        ts = cls.deserialize_timestamp(body.get("timestamp"))
        return cls(body["value"], timestamp=ts)

    @classmethod
    def deserialize_timestamp(cls, timestamp: str) -> datetime:
        if "." in timestamp:
            day_time_format = "%Y-%m-%dT%H:%M:%S.%f%z"
        else:
            day_time_format = "%Y-%m-%dT%H:%M:%S%z"
        return datetime.strptime(timestamp, day_time_format)

    def serialize(self) -> dict:
        j = {"value": self.value}
        utc_ts = self.timestamp.astimezone(timezone.utc)
        # python's strftime/strptime use microseconds, Netilion milliseconds
        time_to_seconds = utc_ts.strftime("%Y-%m-%dT%H:%M:%S")
        milliseconds = int(utc_ts.strftime("%f")) // 1000
        # since we convert to UTC first, we can hardcode the TZ code -- Z == "UTC"
        j["timestamp"] = f"{time_to_seconds}.{milliseconds}Z"
        return j

    def __str__(self):  # pragma: no cover
        return f"AssetValue {self.value}, {self.timestamp or 'timestamp n/a'})"


class AssetSystem(NetilionObject):
    system_id = None
    specifications: dict = {}

    def __init__(self, system_id, specifications=None):
        self.system_id = system_id
        self.specifications = specifications or {}

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["id"], body.get("specifications"))

    def serialize(self) -> dict:
        return {"id": self.system_id}

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.system_id == other.system_id
        else:
            return False


class AssetHealthCondition(NetilionObject):

    health_condition_id = None
    diagnosis_code: str = None

    def __init__(self, health_condition_id, diagnosis_code: str):
        self.health_condition_id = health_condition_id
        self.diagnosis_code = diagnosis_code

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["id"], body["diagnosis_code"])

    def serialize(self) -> dict:
        return {"id": self.health_condition_id, "diagnosis_code": self.diagnosis_code}

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.health_condition_id == other.health_condition_id and self.diagnosis_code == other.diagnosis_code
        else:
            return False


class NodeSpecification(NetilionObject):
    node_id = None
    name = None
    specifications: dict = {}
    hidden = False

    def __init__(self, node_id: int, name: str = "", specifications: Optional[dict] = None, hidden: bool = False):
        self.node_id = node_id
        self.name = name
        self.specifications = specifications or {}
        self.hidden = hidden

    @classmethod
    def deserialize(cls, body) -> T:
        return cls(body["id"], body.get("name"), body.get("specifications"), body.get("hidden"))

    def serialize(self) -> dict:
        body = {"id": self.node_id, "name": self.name, "hidden": self.hidden}
        if self.specifications:
            body["specifications"] = self.specifications
        return body

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.node_id == other.node_id
        else:
            return False


class Pagination(NetilionObject):
    page_count: int = None
    per_page: int = None
    page: int = None
    next_url: Optional[str] = None

    def __init__(self, page_count: int, per_page: int, page: int, next_url: Optional[str] = None):
        self.page_count = page_count
        self.per_page = per_page
        self.page = page
        self.next_url = next_url

    @classmethod
    def deserialize(cls, body) -> T:
        pagination = body["pagination"]
        return cls(pagination["page_count"], pagination["per_page"], pagination["page"], pagination.get("next", None))

    def serialize(self) -> dict:
        pagination = {"page_count": self.page_count, "per_page": self.per_page, "page": self.page}
        if self.next_url:
            pagination["next"] = self.next_url
        return pagination


class DocumentClassification(Enum):
    UNDEFINED = 1
    PUBLIC = 2
    INTERNAL = 3
    CONFIDENTIAL = 4


class DocumentStatus(Enum):
    UNDEFINED = 1


class Document(NetilionObject):
    document_id: int = None
    name: str = None
    classification: DocumentClassification = None
    status: DocumentStatus = None
    attachments: list[Attachment]

    def __init__(self, document_id: int, name: str, classification: DocumentClassification,
                 status: DocumentStatus = DocumentStatus.UNDEFINED, attachments: list[Attachment] = None):
        if attachments is None:
            attachments = []

        self.document_id = document_id
        self.name = name
        self.classification = classification
        self.status = status
        self.attachments = attachments

    @classmethod
    def deserialize(cls, body) -> T:
        document_id = int(body["id"])
        name = body["name"]
        classification = DocumentClassification(body["classification"]["id"])
        status = DocumentStatus(body["status"]["id"])
        if body.get("attachments") is not None:
            attachments = Attachment.parse_multiple_from_api(body, "attachments")
        else:
            attachments = []

        return cls(document_id, name, classification, status, attachments)

    def serialize(self) -> dict:
        document = {
            "id": self.document_id,
            "name": self.name,
            "classification": {"id": self.classification.value},
            "status": {"id": self.status.value},
            "attachments": [attachment.serialize() for attachment in self.attachments]
        }
        return document


class Attachment(NetilionObject):
    attachment_id: int = None
    file_name: str = None
    content_type: str = None

    def __init__(self, attachment_id: int, file_name: str, content_type: str):
        self.attachment_id = attachment_id
        self.file_name = file_name
        self.content_type = content_type

    @classmethod
    def deserialize(cls, body) -> T:
        attachment_id = int(body["id"])
        file_name = body["file_name"]
        content_type = body["content_type"]
        return cls(attachment_id, file_name, content_type)

    def serialize(self) -> dict:
        attachment = {
            "id": self.attachment_id,
            "file_name": self.file_name,
            "content_type": self.content_type
        }
        return attachment
