import logging
import math
import json
import time
import urllib.parse
from unittest.mock import patch, MagicMock

import responses
import pytest

from netilion.client import NetilionTechnicalApiClient
from netilion.config import ConfigurationParameters
from netilion.error import MalformedNetilionApiResponse, BadNetilionApiPermission, GenericNetilionApiError, \
    QuotaExceeded, MalformedNetilionApiRequest, InvalidNetilionApiState

from netilion.model import ClientApplication, WebHook, Asset, AssetValue, AssetValues, Unit


class TestMockedNetilionApiClient:

    @staticmethod
    def _add_pagination_info(data: dict, data_key: str = None, per_page: int = 10, on_page: int = 1) -> dict:
        assert (data_key or len(data.keys()) == 1), "Unable to determine object to calculate pagination"
        if not data_key:
            data_key = next(iter(data))
        total_count = len(data[data_key])
        page_count = max(math.floor((float(total_count) + per_page - 1) // per_page), 1)
        return {
            **data,
            "pagination": {
                "total_count": total_count,
                "page_count": page_count,
                "per_page": per_page,
                "page": on_page
            }
        }

    @pytest.fixture()
    def configuration(self):
        return ConfigurationParameters(
            "https://host.local",
            "1",
            "app1",
            "id",
            "secret",
            "https://host.local/v9000",
            "https://host.local/oauth/token",
            "user",
            "pass"
        )

    @pytest.fixture()
    def api_client(self, configuration):
        return NetilionTechnicalApiClient(configuration)

    @pytest.fixture()
    def capture_oauth_token(self, configuration):
        self._capture_oauth_token(configuration)

    @pytest.fixture()
    def client_application_response(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATIONS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "client_applications": [
                {
                    "name": configuration.subscription_name,
                    "id": 1,
                    "contact_person": {
                        "id": 1,
                        "href": ""
                    }
                }]
        }))

    def _capture_oauth_token(self, configuration,
                             access_tok_created_at=int(time.time()),
                             access_tok_expires_in=1000):
        # Note: if the client attempts a request not exactly matching the one below, responses will throw an error.
        responses.add(responses.POST,
                      configuration.oauth_token_url,
                      body=json.dumps({
                          "access_token": "acctok",
                          "refresh_token": "reftok",
                          "created_at": access_tok_created_at,
                          "expires_in": access_tok_expires_in}),
                      match=[
                          # convert the following params to a string-encoded request body
                          responses.urlencoded_params_matcher({
                              "client_id": "id",
                              "client_secret": "secret",
                              "username": "user",
                              "password": "pass",
                              "grant_type": "password"
                          })
                      ])
        responses.add(responses.POST,
                      configuration.oauth_token_url,
                      # the API does *NOT* support the refresh_token grant type
                      body=json.dumps({
                          'error': 'invalid_grant',
                          'error_description': 'The provided authorization grant is invalid, expired, revoked, does not match the redirection URI used in the authorization request, or was issued to another client.'
                      }),
                      match=[
                          # convert the following params to a string-encoded request body
                          responses.urlencoded_params_matcher({
                              "grant_type": "refresh_token",
                              "refresh_token": "reftok"
                          })
                      ])

    def test_self_pagination_with_key(self):
        original_data = {"something": ["x", "y", "z"], "something_else": [1, 2]}
        data = self._add_pagination_info(original_data, "something_else")
        assert data == {
            **original_data,
            "pagination": {
                "total_count": 2,
                "page_count": 1,
                "per_page": 10,
                "page": 1
            }
        }

    @pytest.mark.parametrize("total_count,page_count", [(0, 1), (1, 1), (10, 1), (11, 2)])
    def test_self_pagination(self, total_count, page_count):
        original_data = {"something": ["item%d" % x for x in range(total_count)]}
        data = self._add_pagination_info(original_data)
        assert data == {
            **original_data,
            "pagination": {
                "total_count": total_count,
                "page_count": page_count,
                "per_page": 10,
                "page": 1
            }
        }

    @responses.activate
    def test_adds_oauth_body(self, configuration, api_client, capture_oauth_token):
        url = configuration.endpoint
        responses.add(responses.GET, url, status=200)

        api_client.get(url)
        assert len(responses.calls) == 2, "Missing API call"
        assert responses.calls[0].request.url == configuration.oauth_token_url, "Missing call to API to obtain OAuth token"
        assert api_client.authorized, "No access token obtained"

    @responses.activate
    def test_rejects_non_netilion_url(self, api_client):
        url = "https://www.google.com"
        responses.add(responses.GET, url, status=200)
        with pytest.raises(RuntimeError):
            api_client.get(url)

    @responses.activate
    def test_refreshes_expired_token(self, configuration, api_client):
        expiry = 1000
        now = int(time.time())
        access_token_expired_ts = expiry + now + 1
        self._capture_oauth_token(configuration, now, expiry)

        target_url = configuration.endpoint
        if not target_url.endswith("/"):  # pragma: no cover -- this is basically a configuration artifact from base.py
            # the requests library adds a trailing slash to requests so we have to add them too if we check for equality
            target_url += "/"
        responses.add(responses.GET, target_url, status=200)

        api_client.get(target_url)

        assert responses.calls[0].request.url == configuration.oauth_token_url
        assert responses.calls[1].request.url == target_url

        # expire the token by forwarding the clock
        with patch('netilion.client.time') as time_mock:
            time_mock.time = MagicMock(return_value=access_token_expired_ts)
            api_client.get(target_url)
            assert responses.calls[2].request.url == configuration.oauth_token_url, "Should have requested new token"
            assert responses.calls[3].request.url == target_url

            # return the time to reality
            time_mock.time = MagicMock(return_value=time.time())
            # check this to make sure we don't immediately ask again for a new token
            api_client.get(target_url)
            assert responses.calls[4].request.url == target_url

    @responses.activate
    def test_get_applications(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATIONS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "client_applications": [{
                "name": "app1",
                "id": 1,
                "contact_person": {
                    "id": 1,
                    "href": ""
                }
            }]
        }))
        apps = api_client.get_applications()
        assert isinstance(apps, list), "No client applications received"
        assert len(apps) == 1, "No client applications received"
        assert apps[0].name == "app1", "Wrong client application returned"
        assert apps[0].api_id == 1, "Wrong client application returned"

    @responses.activate
    def test_get_my_application_without_id_env(self, configuration, api_client, capture_oauth_token):
        configuration.subscription_id = None
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATIONS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "client_applications": [
                {
                    "name": configuration.subscription_name[::-1],
                    "id": 2,
                    "contact_person": {
                        "id": 1,
                        "href": ""
                    }
                }, {
                    "name": configuration.subscription_name,
                    "id": 1,
                    "contact_person": {
                        "id": 1,
                        "href": ""
                    }
            }]
        }))
        me = api_client.get_my_application()
        assert isinstance(me, ClientApplication)
        assert me.name == configuration.subscription_name

        # a second call to my_application must return a cached value and not hit the API again
        api_client.get_my_application()
        assert len(responses.calls) == 2  # 1 token + 1 client_applications request

    @responses.activate
    def test_get_my_application_no_request_if_id_env(self, configuration, api_client, capture_oauth_token):
        configuration.subscription_id = "1"
        me = api_client.get_my_application()
        assert isinstance(me, ClientApplication)
        assert me.name == "app1"
        assert me.api_id == "1"

    @responses.activate
    def test_get_application(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATION, {"application_id": 1})
        responses.add(responses.GET, url, json={
            "name": "app1",
            "id": 1,
            "contact_person": {
                "id": 1,
                "href": ""
            }
        })
        app = api_client.get_application(1)
        assert isinstance(app, ClientApplication)
        assert app.name == "app1"
        assert app.api_id == 1

    @responses.activate
    def test_get_assets(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "assets": [{
                "serial_number": "asset_1",
                "id": 1
            }, {
                "serial_number": "asset_2",
                "id": 2
            }]
        }))
        assets = api_client.get_assets()
        assert isinstance(assets, list)
        assert len(assets) == 2

    @responses.activate
    def test_get_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 1})
        responses.add(responses.GET, url, json={"id": 1, "serial": 0xdeadbeef})

        asset = api_client.get_asset(1)
        assert isinstance(asset, Asset)

    @responses.activate
    def test_get_asset_values(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET_VALUES, {"asset_id": 1})
        responses.add(responses.GET, url, json={
            "values": [
                {
                    "key": "valkey1",
                    "unit": {
                        "id": 12345
                    },
                    "value": 0xff,
                }, {
                    "key": "valkey2",
                    "unit": {
                        "id": 12346
                    },
                    "value": 0xaa
                }
            ]
        })

        asset_values = api_client.get_asset_values(1)
        assert isinstance(asset_values, list)
        assert len(asset_values) == 2
        assert all(isinstance(value, AssetValue) for value in asset_values)
        keys = [value.key for value in asset_values]
        assert "valkey1" in keys
        assert "valkey2" in keys

    @responses.activate
    def test_get_webhooks(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "webhooks": [{
                "url": "http://host.local",
                "id": 1,
                "event_types": ["asset_value_created"]
            }]
        }))
        hooks = api_client.get_webhooks()
        assert isinstance(hooks, list)
        assert len(hooks) == 1
        assert hooks[0].api_id == 1
        assert hooks[0].url == "http://host.local"

    @responses.activate
    def test_get_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOK, {"application_id": 1, "webhook_id": 1})
        responses.add(responses.GET, url, json={
            "id": 1,
            "url": "http://host.local",
            "event_types": ["asset_value_created"]
        })
        webhook = api_client.get_webhook(1)
        assert isinstance(webhook, WebHook)
        assert webhook.api_id == 1
        assert webhook.url == "http://host.local"
        assert webhook.event_types == ["asset_value_created"]

    @responses.activate
    def test_set_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.POST, url, json={
            "id": 2,
            "url": "http://host2.local",
            "event_types": ["asset_values_created"]
        })
        webhook = WebHook("http://host2.local", ["asset_values_created"])
        new_webhook = api_client.set_webhook(webhook)
        assert isinstance(new_webhook, WebHook)
        assert new_webhook.url == webhook.url
        assert new_webhook.event_types == webhook.event_types
        assert new_webhook.api_id

    @responses.activate
    def test_find_unit(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNITS)
        params = urllib.parse.urlencode({"code": "absorbance_unit"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "units": [
                {
                    "id": 8409,
                    "code": "absorbance_unit",
                    "symbol": "AU",
                    "name": "absorbance unit"
                }
            ],
        }))
        unit = api_client.find_unit("absorbance_unit")
        assert unit.code == "absorbance_unit"

    @responses.activate
    def test_find_unit_inexistent(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNITS)
        params = urllib.parse.urlencode({"code": "elbows"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "units": [],
        }))
        unit = api_client.find_unit("elbows")
        assert unit is None

    @responses.activate
    def test_get_unit(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNIT, {"unit_id": 8409})
        responses.add(responses.GET, url, json={
                "id": 8409,
                "code": "absorbance_unit",
                "symbol": "AU",
                "name": "absorbance unit"
            })
        unit = api_client.get_unit(8409)
        assert unit.code == "absorbance_unit"

    @responses.activate
    def test_get_unit_minimal_response_id(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNIT, {"unit_id": 1111})
        responses.add(responses.GET, url, json={
                "id": 1111,
            })
        unit = api_client.get_unit(1111)
        assert unit.unit_id == 1111

    @responses.activate
    def test_get_unit_minimal_response_code(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNIT, {"unit_id": 2222})
        responses.add(responses.GET, url, json={
                "code": "absorbance_unit",
            })
        unit = api_client.get_unit(2222)
        assert unit.code == "absorbance_unit"

    @responses.activate
    def test_push_asset_values_unit_id(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET_VALUES, {"asset_id": 1})
        responses.add(responses.POST, url, json=[{
            "key": "valkey1",
            "unit": {
                "id": 12345
            },
            "value": 0xff,
        }], match=[
            responses.json_params_matcher({
                "values": [{
                    "key": "valkey1",
                    "unit": {
                        "id": 12345
                    },
                    "data": [{
                        "value": 0xff
                    }]
                }]
            })
        ])
        asset = AssetValue("valkey1", unit=Unit(12345), value=0xff)
        asset_values = AssetValues(Asset(1), [asset])
        api_client.push_asset_values(asset_values)

    @responses.activate
    def test_push_asset_values_unit_code(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET_VALUES, {"asset_id": 1})
        responses.add(responses.POST, url, json=[{
            "key": "valkey1",
            "unit": {
                "code": "kermit"
            },
            "value": 0xff,
        }], match=[
            responses.json_params_matcher({
                "values": [{
                    "key": "valkey1",
                    "unit": {
                        "code": "kermit"
                    },
                    "data": [{
                        "value": 0xff
                    }]
                }]
            })
        ])
        asset = AssetValue("valkey1", unit=Unit(code="kermit"), value=0xff)
        asset_values = AssetValues(Asset(1), [asset])
        api_client.push_asset_values(asset_values)

    @responses.activate
    def test_bad_api_response_applications(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATIONS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "client_applications": [{
                "name": "app1"
            }]
        }))
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_applications()

    @responses.activate
    def test_bad_api_response_application(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATION, {"application_id": 1})
        responses.add(responses.GET, url, json={
            # id missing
            "name": "app1"
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_application(1)

    @responses.activate
    def test_bad_api_response_assets(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "assets": [{
                # id missing
                "serial": 0xdeadbeef
            }]
        }))
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_assets()

    @responses.activate
    def test_bad_api_response_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 1})
        responses.add(responses.GET, url, json={
            # id missing
            "serial": 0xdeadbeef
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_asset(1)

    @responses.activate
    def test_bad_api_response_asset_values(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET_VALUES, {"asset_id": 1})
        responses.add(responses.GET, url, json={
            "values": [{
                "key": "k1",
                # unit missing
                "value": 0xff
            }]
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_asset_values(1)

    @responses.activate
    def test_bad_api_response_get_webhooks(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "webhooks": [{
                "url": "http://host.local",
                "id": 1,
                # event types missing
            }]
        }))
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_webhooks()

    @responses.activate
    def test_bad_api_response_get_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOK, {"application_id": 1, "webhook_id": 1})
        responses.add(responses.GET, url, json={
            "id": 1,
            "url": "http://host.local",
            # event types missing
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_webhook(1)

    @responses.activate
    def test_bad_api_response_set_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.POST, url, json={
            "id": 2,
            "url": "http://host2.local",
            # event types missing
        })
        webhook = WebHook("http://host2.local", ["asset_values_created"])
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.set_webhook(webhook)

    @responses.activate
    def test_bad_api_request_set_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.POST, url, status=400, body=json.dumps({
            'errors': [
                {'type': 'n/a', 'message': "don't know yet what this might be, be we check for the status code anyway"}
            ]
        }))
        webhook = WebHook("http://host2.local", ["asset_values_created"])
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.set_webhook(webhook)

    @responses.activate
    def test_bad_api_response_get_unit(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNIT, {"unit_id": 1})
        responses.add(responses.GET, url, json={
            # id and code missing
            "name": "näme"
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_unit(1)

    @responses.activate
    def test_bad_api_response_find_unit_multiple(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.UNITS)
        params = urllib.parse.urlencode({"code": "absorbance_unit"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "units": [
                # duplicate unit
                {
                    "id": 8409,
                    "code": "absorbance_unit",
                    "symbol": "AU",
                    "name": "absorbance unit"
                }, {
                    "id": 8409,
                    "code": "absorbance_unit",
                    "symbol": "AU",
                    "name": "absorbance unit"
                }
            ],
        }))
        with pytest.raises(InvalidNetilionApiState):
            api_client.find_unit("absorbance_unit")

    @responses.activate
    def test_api_error_response(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.GET, url, json={
            'errors': [
                # an unknown error message
                {'message': 'I AM BATMAN', 'type': 'batman'}
            ]
        })
        with pytest.raises(GenericNetilionApiError):
            api_client.get_webhooks()

    @responses.activate
    def test_api_error_unspecified_error(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.GET, url, json={
            'errors': [
                # an unknown error state if errors are not even proper errors anymore
                {'something': "this doesn't have a type field"}
            ]
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_webhooks()

    @responses.activate
    def test_api_no_permission_response(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.WEBHOOKS, {"application_id": 1})
        responses.add(responses.GET, url, json={
            'errors': [
                {'message': 'not found or no permission', 'type': 'not_found_no_permission'}
            ]
        })
        with pytest.raises(BadNetilionApiPermission):
            api_client.get_webhooks()

    @responses.activate
    def test_api_bad_request(self, configuration, api_client, capture_oauth_token, client_application_response):
        asset_values = [AssetValue("k", {'id': 1}, 1)]
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET_VALUES, {"asset_id": 1})
        responses.add(responses.POST, url, status=400, body=json.dumps({
            'errors': [
                {'type': 'n/a', 'message': "don't know yet what this might be, be we check for the status code anyway"}
            ]
        }))
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.push_asset_values(AssetValues(Asset(1), asset_values))

    @responses.activate
    def test_api_quota_exceeded(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATIONS, {"application_id": 1})
        responses.add(responses.GET, url, json={
            'errors': [
                {'type': 'quota_exceeded',
                 'message': 'Your subscription limit is reached, please upgrade your plan'}
            ]
        })
        with pytest.raises(QuotaExceeded):
            api_client.get_applications()

"""
@pytest.mark.skipif(not config.NETILION.HIT_SERVER_FOR_TESTS, reason="Real-world API usage is disabled")
class TestLiveNetilionApiClient:  # pragma: no cover
    @pytest.fixture()
    def logger(self):
        return logging.getLogger(__name__)

    @pytest.fixture()
    def api_client(self):
        return NetilionTechnicalApiClient()

    def test_get_applications(self, api_client, logger):
        apps = api_client.get_applications()
        assert isinstance(apps, list)
        assert len(apps) > 0, "No client application returned"
        for app in apps:
            logger.info(app)
            assert isinstance(app, ClientApplication)

    def test_get_webhooks(self, api_client, logger):
        webhooks = api_client.get_webhooks()
        assert isinstance(webhooks, list)
        if len(webhooks) > 0:
            for webhook in webhooks:
                logger.info(webhook)
                assert isinstance(webhook, WebHook)
        else:
            logger.warning("No webhooks returned")

    def test_refresh_token(self, api_client, logger):
        api_client.get_applications()
        assert api_client.authorized
        token1 = api_client.token
        # the logic of when to refresh the token is covered in TestMockedNetilionApiClient::test_refreshes_expired_token
        api_client.refresh_token()
        token2 = api_client.token
        assert token1 != token2, "Did not receive a new token"

    def test_find_unit(self, api_client, logger):
        unit = api_client.find_unit("degree_celsius")
        assert unit.unit_id
        logger.info(unit)

    def test_get_assets(self, api_client, logger):
        assets = api_client.get_assets()
        assert isinstance(assets, list)
        if not assets:
            logger.warning("No assets returned")
        else:
            for asset in assets:
                logger.info(asset)
                assert isinstance(asset, Asset)

    def test_get_asset(self, api_client, logger):
        asset = api_client.get_asset(4955906)
        assert isinstance(asset, Asset)
        logger.info(asset)

    def test_get_asset_values(self, api_client, logger):
        asset_values = api_client.get_asset_values(4955906)
        assert isinstance(asset_values, list)
        if not asset_values:
            logger.warning("No asset values returned")
        else:
            for asset_value in asset_values:
                logger.info(asset_value)
                assert isinstance(asset_value, AssetValue)
"""