import enum
import logging
import time
from typing import Optional

import oauthlib.oauth2
from oauthlib.oauth2 import LegacyApplicationClient
from requests_oauthlib import OAuth2Session

from .config import ConfigurationParameters
from .error import MalformedNetilionApiRequest, InvalidNetilionApiState, MalformedNetilionApiResponse
from .model import ClientApplication, WebHook, Asset, AssetValue, Unit, AssetValues, AssetValuesByKey, AssetSystem, \
    AssetHealthCondition, Pagination, NodeSpecification


class NetilionTechnicalApiClient(OAuth2Session):  # pylint: disable=too-many-public-methods
    logger = logging.getLogger(__name__)
    request_timing_logger = logging.getLogger(f"{__name__}.timing")
    __configuration: ConfigurationParameters = None
    __my_application: ClientApplication = None

    class ENDPOINT(enum.Enum):
        UNITS = "/units"
        UNIT = "/units/{unit_id}"
        ASSETS = "/assets"
        ASSET = "/assets/{asset_id}"
        ASSET_VALUES = "/assets/{asset_id}/values"
        ASSET_VALUES_KEY = "/assets/{asset_id}/values/{key}"
        ASSET_SYSTEMS = "/assets/{asset_id}/systems"
        ASSET_HEALTH_CONDITIONS = "/assets/{asset_id}/health_conditions"
        ASSET_HEALTH_CONDITION = "/health_conditions/{health_condition_id}"
        CLIENT_APPLICATIONS = "/client_applications"
        CLIENT_APPLICATION = "/client_applications/{application_id}"
        CLIENT_APPLICATION_CURRENT = "/client_applications/current"
        WEBHOOKS = "/client_applications/{application_id}/webhooks"
        WEBHOOK = "/client_applications/{application_id}/webhooks/{webhook_id}"
        PERMISSIONS = "/permissions"
        NODES = "/nodes"
        NODES_SPECIFICATIONS = "/nodes/{node_id}/specifications"

    def __init__(self, configuration: ConfigurationParameters):
        self.__configuration = configuration
        self.logger.debug(f"Starting Netilion client (-> {self.__configuration.endpoint}): {self.__configuration.client_application_name or 'name n/a'}, {self.__configuration.client_id or 'id n/a'}")
        super().__init__(client=LegacyApplicationClient(self.__configuration.client_id))

        def set_api_header(url, headers, data=None):
            # this is required by the Netilion API
            if not headers:  # pragma: no cover
                headers = {}
            headers["Api-Key"] = self.__configuration.client_id
            return url, headers, data

        self.register_compliance_hook("protected_request", set_api_header)

    def construct_url(self, endpoint: ENDPOINT, values: dict = None) -> str:
        raw = f"{self.__configuration.api_url}{endpoint.value}"
        if values:
            formatted = raw.format(**values)
            return formatted
        else:
            return raw

    # pylint: disable=arguments-differ
    def request(self, method, url, **kwargs):
        if not url.startswith(self.__configuration.endpoint):
            raise RuntimeError(f"Bad request to {url} - not a Netilion URL")
        if url == self.__configuration.oauth_token_url:
            # don't try to obtain tokens when trying to fetch tokens
            return super().request(method, url, **kwargs)
        else:
            if not self.token:
                self.fetch_token(**kwargs)
            else:
                token_expiry = self.token["created_at"] + self.token["expires_in"]
                token_expired = token_expiry <= time.time()
                if token_expired:
                    self.logger.info(f"Refreshing token (expired {int(time.time()) - token_expiry} seconds ago)")
                    self.refresh_token(**kwargs)
                else:  # pragma: no cover
                    self.logger.debug(f"Access token still valid for {token_expiry - int(time.time())} seconds")

        # go back to the original request
        return super().request(method, url, **kwargs)

    # pylint: disable=arguments-differ
    def fetch_token(self, **kwargs) -> oauthlib.oauth2.OAuth2Token:
        self.logger.info("Getting new access token")
        return super().fetch_token(token_url=self.__configuration.oauth_token_url, username=self.__configuration.username,
                                   password=self.__configuration.password, client_secret=self.__configuration.client_secret,
                                   include_client_id=True, **kwargs)

    def get(self, url, **kwargs):
        start = time.time()
        resp = super().get(url, **kwargs)
        end = time.time()
        self.request_timing_logger.debug(f"GET to {url} took {end - start:.2f} seconds")
        return resp

    def post(self, url, **kwargs):
        start = time.time()
        resp = super().post(url, **kwargs)
        end = time.time()
        self.request_timing_logger.debug(f"POST to {url} took {end - start:.2f} seconds")
        return resp

    def refresh_token(self, **kwargs) -> oauthlib.oauth2.OAuth2Token:
        self.logger.info("Refreshing token")
        kwargs["client_id"] = self.__configuration.client_id
        kwargs["client_secret"] = self.__configuration.client_secret
        return super().refresh_token(self.__configuration.oauth_token_url, **kwargs)

    def get_applications(self) -> list[ClientApplication]:
        response = self.get(self.construct_url(self.ENDPOINT.CLIENT_APPLICATIONS))
        return ClientApplication.parse_multiple_from_api(response.json(), "client_applications")

    def get_my_application(self) -> ClientApplication:
        if self.__my_application:
            return self.__my_application
        elif self.__configuration.client_application_id and self.__configuration.client_application_name:
            return ClientApplication(self.__configuration.client_application_name, self.__configuration.client_application_id)
        # we always expect this to return exactly one application since otherwise we'd get a permission denied error.
        response = self.get(self.construct_url(self.ENDPOINT.CLIENT_APPLICATION_CURRENT))
        app = ClientApplication.parse_from_api(response.json())
        self.__my_application = app
        self.logger.info(f"Determined this application to be {app}")
        return app

    def get_application(self, application_id: int) -> ClientApplication:
        response = self.get(self.construct_url(self.ENDPOINT.CLIENT_APPLICATION, {"application_id": application_id}))
        return ClientApplication.parse_from_api(response.json())

    def get_assets(self) -> list[Asset]:
        response = self.get(self.construct_url(self.ENDPOINT.ASSETS))
        return Asset.parse_multiple_from_api(response.json(), "assets")

    def get_asset(self, asset_id: int) -> Asset:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET, {"asset_id": asset_id}))
        return Asset.parse_from_api(response.json())

    def create_asset(self, asset_sn: str, product_id: int) -> Asset:
        body = {"serial_number": asset_sn, "product": {"id": product_id}}
        response = self.post(self.construct_url(self.ENDPOINT.ASSETS), json=body)
        return Asset.parse_from_api(response.json())

    def delete_asset(self, asset_id: int) -> None:
        response = self.delete(self.construct_url(self.ENDPOINT.ASSET, {"asset_id": asset_id}))
        if 400 <= response.status_code < 500:
            raise MalformedNetilionApiRequest(response)
        elif response.status_code != 204:
            raise InvalidNetilionApiState(response)

    def find_asset(self, serial_number: str) -> Optional[Asset]:
        query_params = {"serial_number": serial_number}
        response = self.get(self.construct_url(self.ENDPOINT.ASSETS), params=query_params)
        assets = Asset.parse_multiple_from_api(response.json(), "assets")
        if len(assets) == 0:
            return None
        elif len(assets) > 1:
            raise InvalidNetilionApiState(msg=f"Received {len(assets)} units for serial number {serial_number}")
        return assets[0]

    def set_rw_permissions(self, asset_id: int, user_id: int) -> bool:
        body = {
            "permission_type": ["can_read", "can_update"],
            "assignable": {"id": user_id, "type": "User"},
            # yes, permittable has a typo, but that's how it is in the API
            "permitable": {"id": asset_id, "type": "Asset"}
        }
        response = self.post(self.construct_url(self.ENDPOINT.PERMISSIONS), json=body)
        return response.status_code < 300 and "errors" not in response.json()

    def find_unit(self, unit_code: str) -> Optional[Unit]:
        query_params = {"code": unit_code}
        response = self.get(self.construct_url(self.ENDPOINT.UNITS), params=query_params)
        units = Unit.parse_multiple_from_api(response.json(), "units")
        if len(units) == 0:
            return None
        elif len(units) > 1:
            raise InvalidNetilionApiState(msg=f"Received {len(units)} units for code {unit_code}")
        return units[0]

    def get_unit(self, unit_id: int) -> Unit:
        response = self.get(self.construct_url(self.ENDPOINT.UNIT, {"unit_id": unit_id}))
        return Unit.parse_from_api(response.json())

    def get_asset_values(self, asset_id: int) -> list[AssetValue]:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET_VALUES, {"asset_id": asset_id}))
        return AssetValue.parse_multiple_from_api(response.json(), "values")

    def push_asset_values(self, asset_values: AssetValues):
        self.logger.info(f"POSTing asset values: {asset_values}")
        # we can remove the asset id here since that becomes part of the url
        asset_payload = {"values": asset_values.serialize().get("values", [])}
        self.logger.debug(asset_payload)
        response = self.post(self.construct_url(self.ENDPOINT.ASSET_VALUES, {"asset_id": asset_values.asset.asset_id}), json=asset_payload)
        if response.status_code >= 300:
            self.logger.error(f"Received bad server response: {response.status_code}")
            raise MalformedNetilionApiResponse(response)
        else:
            self.logger.debug(f"POST confirmed: {response.status_code}")

    def get_asset_values_history(self, asset_id: int, key: str, from_date: str, to_date: str, page: int = 1) -> (list[AssetValuesByKey], Pagination):  # pylint: disable=too-many-arguments
        url = self.construct_url(self.ENDPOINT.ASSET_VALUES_KEY, {"asset_id": asset_id, "key": key})
        response = self.get(url, params={"from": from_date, "to": to_date, "page": page, "per_page": 1000})
        asset_history = AssetValuesByKey.parse_multiple_from_api(response.json(), "data")
        pagination = Pagination.parse_from_api(response.json())
        return asset_history, pagination

    def get_last_asset_values(self, asset_id: int, key: str, to_date: str, from_date: Optional[str] = None) -> list[AssetValuesByKey]:
        params = {"to": to_date, "order_by": "-timestamp"}
        if from_date:
            params["from"] = from_date
        url = self.construct_url(self.ENDPOINT.ASSET_VALUES_KEY, {"asset_id": asset_id, "key": key})
        response = self.get(url, params=params)
        return AssetValuesByKey.parse_multiple_from_api(response.json(), "data")

    def get_webhooks(self) -> list[WebHook]:
        application_id = self.get_my_application().api_id
        response = self.get(self.construct_url(self.ENDPOINT.WEBHOOKS, {"application_id": application_id}))
        return WebHook.parse_multiple_from_api(response.json(), "webhooks")

    def set_webhook(self, webhook: WebHook) -> WebHook:
        application_id = self.get_my_application().api_id
        webhook_payload = webhook.serialize()
        response = self.post(self.construct_url(self.ENDPOINT.WEBHOOKS, {"application_id": application_id}), json=webhook_payload)
        if response.status_code >= 300:
            raise MalformedNetilionApiRequest(response)
        return WebHook.parse_from_api(response.json())

    def delete_webhook(self, webhook: WebHook) -> None:
        application_id = self.get_my_application().api_id
        url = self.construct_url(self.ENDPOINT.WEBHOOK, {"application_id": application_id, "webhook_id": webhook.api_id})
        response = self.delete(url)
        if response.status_code >= 300:
            self.logger.error(f"Received bad server response: {response.status_code}")
            raise MalformedNetilionApiResponse(response)
        else:
            self.logger.debug(f"POST confirmed: {response.status_code}")

    def get_webhook(self, webhook_id: int) -> WebHook:
        application_id = self.get_my_application().api_id
        response = self.get(self.construct_url(self.ENDPOINT.WEBHOOK, {"application_id": application_id, "webhook_id": webhook_id}))
        return WebHook.parse_from_api(response.json())

    def get_asset_systems(self, asset_id: int) -> list[AssetSystem]:
        query_params = {"include": "specifications"}
        response = self.get(self.construct_url(self.ENDPOINT.ASSET_SYSTEMS, {"asset_id": asset_id}), params=query_params)
        return AssetSystem.parse_multiple_from_api(response.json(), "systems")

    def get_node_specifications(self, node_name: str) -> list[NodeSpecification]:
        query_params = {"name": node_name,
                        "include": "hidden,specifications"}
        response = self.get(self.construct_url(self.ENDPOINT.NODES), params=query_params)
        return NodeSpecification.parse_multiple_from_api(response.json(), "nodes")

    def post_node(self, node_name: str) -> NodeSpecification:
        node_body = {"name": node_name,
                     "hidden": "true"}
        response = self.post(self.construct_url(self.ENDPOINT.NODES), json=node_body)
        if response.status_code >= 300:
            self.logger.error(f"Received bad server response: {response.status_code}")
            raise MalformedNetilionApiResponse(response)
        else:
            self.logger.debug(f"POST confirmed: {response.status_code}")
            return NodeSpecification.parse_from_api(response.json())

    def patch_node_specification(self, node_id: int, specification_key: str, specification_value: str) -> None:
        specification_body = {specification_key: {
            "value": specification_value
        }}
        url = self.construct_url(self.ENDPOINT.NODES_SPECIFICATIONS, {"node_id": node_id})
        response = self.patch(url, json=specification_body)
        if response.status_code >= 300:
            self.logger.error(f"Received bad server response: {response.status_code}")
            raise MalformedNetilionApiResponse(response)
        else:
            self.logger.debug(f"POST confirmed: {response.status_code}")

    def get_asset_health_conditions(self, asset_id: int) -> list[AssetHealthCondition]:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": asset_id}))
        return AssetHealthCondition.parse_multiple_from_api(response.json(), "health_conditions")

    def get_asset_health_condition(self, health_condition_id: int) -> AssetHealthCondition:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET_HEALTH_CONDITION, {"health_condition_id": health_condition_id}))
        return AssetHealthCondition.parse_from_api(response.json())
