import enum
import logging
import time
from typing import Optional

import oauthlib.oauth2
from oauthlib.oauth2 import LegacyApplicationClient
from requests_oauthlib import OAuth2Session

from .config import ConfigurationParameters
from .error import MalformedNetilionApiRequest, InvalidNetilionApiState, MalformedNetilionApiResponse
from .model import ClientApplication, WebHook, Asset, AssetValue, Unit, AssetValues


class NetilionTechnicalApiClient(OAuth2Session):
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
        CLIENT_APPLICATIONS = "/client_applications"
        CLIENT_APPLICATION = "/client_applications/{application_id}"
        WEBHOOKS = "/client_applications/{application_id}/webhooks"
        WEBHOOK = "/client_applications/{application_id}/webhooks/{webhook_id}"

    def __init__(self, configuration: ConfigurationParameters):
        self.__configuration = configuration
        self.logger.debug(f"Starting Netilion client (-> {self.__configuration.endpoint}): {self.__configuration.client_application_name}, {self.__configuration.client_id}")
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
                self.fetch_token()
            else:
                token_expiry = self.token["created_at"] + self.token["expires_in"]
                token_expired = token_expiry <= time.time()
                if token_expired:
                    self.logger.info(f"Refreshing token (expired {int(time.time()) - token_expiry} seconds ago)")
                    self.refresh_token()
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
        resp = super().get(url,**kwargs)
        end = time.time()
        self.request_timing_logger.debug(f"GET to {url} took {end - start:.2f} seconds")
        return resp

    def post(self, url, **kwargs):
        start = time.time()
        resp = super().post(url,**kwargs)
        end = time.time()
        self.request_timing_logger.debug(f"POST to {url} took {end - start:.2f} seconds")
        return resp

    # pylint: disable=arguments-differ
    def refresh_token(self, **kwargs):
        self.logger.debug("Refreshing token")
        # the Netilion API does *not* support refreshing tokens:
        # return super().refresh_token(token_url=self.__configuration.oauth_token_url, **kwargs)
        # instead we can just get a new one from scratch:
        return self.fetch_token()

    def get_applications(self) -> list[ClientApplication]:
        response = self.get(self.construct_url(self.ENDPOINT.CLIENT_APPLICATIONS))
        try:
            return ClientApplication.parse_multiple_from_api(response.json(), "client_applications")
        except Exception as err:
            self.logger.error(err)
            raise

    def get_my_application(self) -> ClientApplication:
        if self.__my_application:
            return self.__my_application
        elif self.__configuration.client_application_id and self.__configuration.client_application_name:
            return ClientApplication(self.__configuration.client_application_name, self.__configuration.client_application_id)
        # we always expect this to return exactly one application since otherwise we'd get a permission denied error.
        apps = self.get_applications()
        app = next(filter(lambda app: app.name == self.__configuration.client_application_name, apps))
        self.__my_application = app
        self.logger.info(f"Determined this application to be {app}")
        return app

    def get_application(self, application_id: int) -> ClientApplication:
        response = self.get(self.construct_url(self.ENDPOINT.CLIENT_APPLICATION, {"application_id": application_id}))
        try:
            return ClientApplication.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise

    def get_assets(self) -> list[Asset]:
        response = self.get(self.construct_url(self.ENDPOINT.ASSETS))
        try:
            return Asset.parse_multiple_from_api(response.json(), "assets")
        except Exception as err:
            self.logger.error(err)
            raise

    def get_asset(self, asset_id: int) -> Asset:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET, {"asset_id": asset_id}))
        try:
            return Asset.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise

    def create_asset(self, asset_sn: str, product_id: int) -> Asset:
        body = {"serial_number": asset_sn, "product": {"id": product_id}}
        response = self.post(self.construct_url(self.ENDPOINT.ASSETS), json=body)
        try:
            return Asset.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise

    def delete_asset(self, asset_id: int) -> None:
        response = self.delete(self.construct_url(self.ENDPOINT.ASSET, {"asset_id": asset_id}))
        if 400 <= response.status_code < 500:
            raise MalformedNetilionApiRequest(response)
        elif response.status_code != 204:
            raise InvalidNetilionApiState(response)

    def find_unit(self, unit_code: str) -> Optional[Unit]:
        query_params = {"code": unit_code}
        response = self.get(self.construct_url(self.ENDPOINT.UNITS), params=query_params)
        try:
            units = Unit.parse_multiple_from_api(response.json(), "units")
            if len(units) == 0:
                return None
            elif len(units) > 1:
                raise InvalidNetilionApiState(f"Received {len(units)} units for code {unit_code}")
            return units[0]
        except Exception as err:
            self.logger.error(err)
            raise

    def get_unit(self, unit_id: int) -> Unit:
        response = self.get(self.construct_url(self.ENDPOINT.UNIT, {"unit_id": unit_id}))
        try:
            return Unit.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise

    def get_asset_values(self, asset_id: int) -> list[AssetValue]:
        response = self.get(self.construct_url(self.ENDPOINT.ASSET_VALUES, {"asset_id": asset_id}))
        try:
            return AssetValue.parse_multiple_from_api(response.json(), "values")
        except Exception as err:
            self.logger.error(err)
            raise

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

    def get_webhooks(self) -> list[WebHook]:
        application_id = self.get_my_application().api_id
        response = self.get(self.construct_url(self.ENDPOINT.WEBHOOKS, {"application_id": application_id}))
        try:
            return WebHook.parse_multiple_from_api(response.json(), "webhooks")
        except Exception as err:
            self.logger.error(err)
            raise

    def set_webhook(self, webhook: WebHook) -> WebHook:
        application_id = self.get_my_application().api_id
        webhook_payload = webhook.serialize()
        response = self.post(self.construct_url(self.ENDPOINT.WEBHOOKS, {"application_id": application_id}), json=webhook_payload)
        if response.status_code >= 300:
            raise MalformedNetilionApiRequest(response)
        try:
            return WebHook.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise

    def get_webhook(self, webhook_id: int) -> WebHook:
        application_id = self.get_my_application().api_id
        response = self.get(self.construct_url(self.ENDPOINT.WEBHOOK, {"application_id": application_id, "webhook_id": webhook_id}))
        try:
            return WebHook.parse_from_api(response.json())
        except Exception as err:
            self.logger.error(err)
            raise
