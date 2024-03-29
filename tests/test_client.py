# pylint: skip-file
import json
import math
import time
import urllib.parse
from unittest.mock import patch, MagicMock

import pytest
import responses

from netilion.client import NetilionTechnicalApiClient
from netilion.config import ConfigurationParameters
from netilion.error import MalformedNetilionApiResponse, BadNetilionApiPermission, GenericNetilionApiError, \
    QuotaExceeded, MalformedNetilionApiRequest, InvalidNetilionApiState
from netilion.model import ClientApplication, WebHook, Asset, AssetValue, AssetValues, AssetValuesByKey, Unit, \
    DocumentClassification, DocumentStatus, Specification


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
            endpoint="https://host.local",
            client_id="id",
            client_secret="secret",
            username="user",
            password="pass",
            client_application_id="1",
            client_application_name="app1",
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
                    "name": configuration.client_application_name,
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
                      body=json.dumps({
                          "access_token": "acctok",
                          "refresh_token": "reftok",
                          "created_at": access_tok_created_at,
                          "expires_in": access_tok_expires_in}),
                      match=[
                          # convert the following params to a string-encoded request body
                          responses.urlencoded_params_matcher({
                              "grant_type": "refresh_token",
                              "refresh_token": "reftok",
                              "client_id": "id",
                              "client_secret": "secret"
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
        configuration.client_application_id = None
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATION_CURRENT)
        responses.add(responses.GET, url, json={
            "name": "app1",
            "id": 1,
            "contact_person": {
                "id": 1,
                "href": ""
            }
        })
        me = api_client.get_my_application()
        assert isinstance(me, ClientApplication)
        assert me.name == configuration.client_application_name

        # a second call to my_application must return a cached value and not hit the API again
        api_client.get_my_application()
        assert len(responses.calls) == 2  # 1 token + 1 client_applications request
        assert responses.calls[1].request.path_url.endswith(NetilionTechnicalApiClient.ENDPOINT.CLIENT_APPLICATION_CURRENT.value)

    @responses.activate
    def test_get_my_application_no_request_if_id_env(self, configuration, api_client, capture_oauth_token):
        configuration.client_application_id = "1"
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
    def test_create_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        responses.add(responses.POST, url,
                      json={"id": 1, "serial_number": "0xdeadbeef"},
                      match=[
                        responses.json_params_matcher({
                            "serial_number": "0xdeadbeef",
                            "product": {
                                "id": 428865
                            }
                        })]
                      )
        asset = api_client.create_asset("0xdeadbeef", product_id=428865)
        assert isinstance(asset, Asset)
        assert asset.serial_number == "0xdeadbeef"

    @responses.activate
    def test_delete_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 1})
        asset = Asset(1)
        responses.add(responses.DELETE, url, status=204)
        api_client.delete_asset(asset.asset_id)
        # 0 is token call
        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "DELETE"

    @responses.activate
    def test_find_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        params = urllib.parse.urlencode({"serial_number": "0xdeadbeef"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "assets": [
                {
                    "id": 1,
                    "serial_number": "0xdeadbeef",
                    "product": {"id": 1000},
                }
            ],
        }))
        asset = api_client.find_asset("0xdeadbeef")
        assert asset.serial_number == "0xdeadbeef"

    @responses.activate
    def test_find_asset_inexistent(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        params = urllib.parse.urlencode({"serial_number": "the restaurant at the end of the universe"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "assets": [],
        }))
        asset = api_client.find_asset("the restaurant at the end of the universe")
        assert asset is None

    @responses.activate
    def test_set_permissions(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.PERMISSIONS)
        responses.add(responses.POST, url, json={}, match=[
            responses.json_params_matcher({
                "permission_type": ["can_read", "can_update"],
                "assignable": {"id": 666, "type": "User"},
                "permitable": {"id": 47, "type": "Asset"}
            })]
        )

        ok = api_client.set_rw_permissions(asset_id=Asset(47).asset_id, user_id=666)
        assert ok

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
    def test_get_asset_values_history(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = "https://host.local/v1//assets/1/values/alcohol?from=2022-01-19T14:00:00&to=2022-01-24T09:00:00&page=1&per_page=1000"
        responses.add(responses.GET, url, json={
            "key": "alcohol_balling",
            "unit": {
                "id": 8612,
                "href": "https://api.staging-env.netilion.endress.com/v1/units/8612"
            },
            "latest": -0.17572078817507417,
            "min": -3.1412830460507917,
            "max": 43.639857800823826,
            "mean": 11.63084701425248,
            "data": [
                {
                    "timestamp": "2022-01-19T14:00:15.202Z",
                    "value": 43.639857800823826
                },
                {
                    "timestamp": "2022-01-19T14:21:17.211Z",
                    "value": -3.1412830460507917
                },
                {
                    "timestamp": "2022-01-19T14:22:17.24Z",
                    "value": 28.460037110165224
                },
                {
                    "timestamp": "2022-01-19T14:38:43.294Z",
                    "value": 6.331548934579579
                },
                {
                    "timestamp": "2022-01-19T14:40:29.1Z",
                    "value": 7.179125310495604
                },
            ],
            "pagination": {
                "page_count": 4,
                "per_page": 500,
                "page": 1
            }
        })

        asset_values_history, pagination = api_client.get_asset_values_history(1, "alcohol", "2022-01-19T14:00:00",
                                                                               "2022-01-24T09:00:00")
        assert isinstance(asset_values_history, list)
        assert len(asset_values_history) == 5
        assert all(isinstance(value, AssetValuesByKey) for value in asset_values_history)
        values = [value.value for value in asset_values_history]
        assert 43.639857800823826 in values
        assert -3.1412830460507917 in values
        assert 28.460037110165224 in values
        assert 6.331548934579579 in values
        assert 7.179125310495604 in values
        assert pagination.page_count == 4
        assert pagination.per_page == 500
        assert pagination.page == 1

    @responses.activate
    def test_get_last_asset_values(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = "https://host.local/v1//assets/1/values/alcohol?to=2022-01-24T09:00:00&order_by=-timestamp"
        responses.add(responses.GET, url, json={
            "key": "alcohol_balling",
            "unit": {
                "id": 8612,
                "href": "https://api.staging-env.netilion.endress.com/v1/units/8612"
            },
            "latest": -0.17572078817507417,
            "min": -3.1412830460507917,
            "max": 43.639857800823826,
            "mean": 11.63084701425248,
            "data": [
                {
                    "timestamp": "2022-01-19T14:00:15.202Z",
                    "value": 43.639857800823826
                },
                {
                    "timestamp": "2022-01-19T14:21:17.211Z",
                    "value": -3.1412830460507917
                },
                {
                    "timestamp": "2022-01-19T14:22:17.24Z",
                    "value": 28.460037110165224
                },
                {
                    "timestamp": "2022-01-19T14:38:43.294Z",
                    "value": 6.331548934579579
                },
                {
                    "timestamp": "2022-01-19T14:40:29.1Z",
                    "value": 7.179125310495604
                },
            ],
            "pagination": {
                "page_count": 4,
                "per_page": 500,
                "page": 1
            }
        })

        asset_values_history = api_client.get_last_asset_values(1, "alcohol", "2022-01-24T09:00:00")
        assert isinstance(asset_values_history, list)
        assert len(asset_values_history) == 5
        assert all(isinstance(value, AssetValuesByKey) for value in asset_values_history)
        values = [value.value for value in asset_values_history]
        assert 43.639857800823826 in values
        assert -3.1412830460507917 in values
        assert 28.460037110165224 in values
        assert 6.331548934579579 in values
        assert 7.179125310495604 in values

    @responses.activate
    def test_get_last_asset_values_with_from(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = "https://host.local/v1//assets/1/values/alcohol?to=2022-01-24T09:00:00&order_by=-timestamp&from=2022-01-19T14:00:00"
        responses.add(responses.GET, url, json={
            "key": "alcohol_balling",
            "unit": {
                "id": 8612,
                "href": "https://api.staging-env.netilion.endress.com/v1/units/8612"
            },
            "latest": -0.17572078817507417,
            "min": -3.1412830460507917,
            "max": 43.639857800823826,
            "mean": 11.63084701425248,
            "data": [
                {
                    "timestamp": "2022-01-19T14:00:15.202Z",
                    "value": 43.639857800823826
                },
                {
                    "timestamp": "2022-01-19T14:21:17.211Z",
                    "value": -3.1412830460507917
                },
                {
                    "timestamp": "2022-01-19T14:22:17.24Z",
                    "value": 28.460037110165224
                },
                {
                    "timestamp": "2022-01-19T14:38:43.294Z",
                    "value": 6.331548934579579
                },
                {
                    "timestamp": "2022-01-19T14:40:29.1Z",
                    "value": 7.179125310495604
                },
            ],
            "pagination": {
                "page_count": 4,
                "per_page": 500,
                "page": 1
            }
        })

        asset_values_history = api_client.get_last_asset_values(1, "alcohol", "2022-01-24T09:00:00", "2022-01-19T14:00:00")
        assert isinstance(asset_values_history, list)
        assert len(asset_values_history) == 5
        assert all(isinstance(value, AssetValuesByKey) for value in asset_values_history)
        values = [value.value for value in asset_values_history]
        assert 43.639857800823826 in values
        assert -3.1412830460507917 in values
        assert 28.460037110165224 in values
        assert 6.331548934579579 in values
        assert 7.179125310495604 in values

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
    def test_delete_webhook(self, configuration, api_client, capture_oauth_token, client_application_response):
        webhook = WebHook("https://test.com", ["event_a", "event_b"], 99)
        url = api_client.construct_url(api_client.ENDPOINT.WEBHOOK, {"application_id": 1, "webhook_id": 99})
        responses.add(responses.DELETE, url, status=204)
        api_client.delete_webhook(webhook)
        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "DELETE"

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
    def test_get_asset_systems(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(api_client.ENDPOINT.ASSET_SYSTEMS, {"asset_id": 99})
        params = urllib.parse.urlencode({"include": "specifications"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, match_querystring=True, json=self._add_pagination_info({
            "systems": [
                {"id": 0xc0fefe, "specifications": [
                    {"id": 1, "thinga": "magicks"}
                ]}
            ]
        }))
        systems = api_client.get_asset_systems(99)
        assert len(systems) == 1
        assert systems[0].system_id == 0xc0fefe
        assert systems[0].specifications[0].get("id") == 1

    @responses.activate
    def test_get_node_specifications(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(api_client.ENDPOINT.NODES)
        query_params = urllib.parse.urlencode({"name": "node_name", "include": "hidden,specifications"})
        url = f"{base_url}?{query_params}"
        responses.add(responses.GET, url, match_querystring=True, json=self._add_pagination_info({
            "nodes": [
                {
                    "name": "node_name",
                    "id": 99,
                    "hidden": "true",
                    "specifications":
                        {"secret": {
                            "value": "1234"
                        }}
                }
            ]
        }))
        node_specifications = api_client.get_node_specifications("node_name")
        assert len(node_specifications) == 1
        assert node_specifications[0].node_id == 99
        assert node_specifications[0].specifications["secret"]["value"] == "1234"

    @responses.activate
    def test_push_node(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.NODES)
        responses.add(responses.POST, url, json={
            "name": "test_node",
            "id": 99,
            "hidden": "true"
        }, match=[
            responses.json_params_matcher({
                "name": "test_node",
                "hidden": "true"
            })
        ])
        node = api_client.post_node("test_node")
        assert node.hidden
        assert node.node_id == 99

    @responses.activate
    def test_patch_node_specification(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.NODES_SPECIFICATIONS, {"node_id": 99})
        responses.add(responses.PATCH, url, match=[responses.json_params_matcher({"specification_key": {
            "value": "specification_value"
        }})])
        api_client.patch_node_specification(99, "specification_key", "specification_value")

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "PATCH"

    @responses.activate
    def test_get_health_conditions(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": 0xa1})
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "health_conditions": [{
                "id": 0xc0,
                "diagnosis_code": "T001",
                "asset_status": {
                    "id": 0xa51,
                    "href": "https://"
                }, "links": {
                    "causes": {
                        "href": "https://"}
                }
            }]
        }))
        health_conditions = api_client.get_asset_health_conditions(0xa1)
        assert len(health_conditions) == 1
        assert health_conditions[0].diagnosis_code == "T001"

    @responses.activate
    def test_get_health_condition(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITION, {"health_condition_id": 0xc0})
        responses.add(responses.GET, url, json={
            "id": 0xc0, "diagnosis_code": "T001", "protocol": "OTHERS",
            "rules": [{"type": "integer", "value": value} for value in range(1000, 1100)],
            "product_identifier": "0xQWX4",
            "hidden": False,
            "asset_status": {"id": 0xa51, "href": "https://"},
            "tenant": {"id": 1, "href": "https://"},
            "links": {"causes": {"href": "https://"}},
            "device_ident": "0xQWX4"
        })
        cond = api_client.get_asset_health_condition(0xc0)
        assert cond.diagnosis_code == "T001"

    @responses.activate
    def test_post_health_conditions_success(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": 1234})
        responses.add(responses.POST, url, status=204, match=[responses.json_params_matcher({
            "health_conditions": [
                {"id": 9999},
                {"id": 100}
            ]
        })])

        api_client.post_asset_health_conditions(1234, [9999, 100])

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "POST"

    @responses.activate
    def test_post_health_conditions_failure(self, configuration, api_client, capture_oauth_token,
                                            client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": 1234})
        responses.add(responses.POST, url, status=400, match=[responses.json_params_matcher({
            "health_conditions": [
                {"id": 9999},
                {"id": 100}
            ]
        })])

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.post_asset_health_conditions(1234, [9999, 100])

    @responses.activate
    def test_delete_health_conditions_success(self, configuration, api_client, capture_oauth_token,
                                            client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": 1234})
        responses.add(responses.DELETE, url, status=204, match=[responses.json_params_matcher({
            "health_conditions": [
                {"id": 9999},
                {"id": 100}
            ]
        })])

        api_client.delete_asset_health_conditions(1234, [9999, 100])

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "DELETE"

    @responses.activate
    def test_delete_health_conditions_failure(self, configuration, api_client, capture_oauth_token,
                                            client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_HEALTH_CONDITIONS, {"asset_id": 1234})
        responses.add(responses.DELETE, url, status=400, match=[responses.json_params_matcher({
            "health_conditions": [
                {"id": 9999},
                {"id": 100}
            ]
        })])

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.delete_asset_health_conditions(1234, [9999, 100])

    @responses.activate
    def test_bad_api_response_post_node(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(api_client.ENDPOINT.NODES)
        responses.add(responses.POST, url, status=400)
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.post_node("node_name")

    @responses.activate
    def test_bad_api_response_patch_node_specification(self, configuration, api_client, capture_oauth_token):
        url = api_client.construct_url(api_client.ENDPOINT.NODES_SPECIFICATIONS, {"node_id": 99})
        responses.add(responses.PATCH, url, status=400)
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.patch_node_specification(99, "key", "value")

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
    def test_bad_api_response_get_assets(self, configuration, api_client, capture_oauth_token, client_application_response):
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
    def test_bad_api_response_get_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 1})
        responses.add(responses.GET, url, json={
            # id missing
            "serial": 0xdeadbeef
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_asset(1)

    @responses.activate
    def test_bad_api_response_create_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        responses.add(responses.POST, url, json={
            # id missing
            "serial": 0xdeadbeef
        })
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.create_asset("sn", 0x11d)

    @responses.activate
    def test_bad_api_response_delete_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 99999999})
        responses.add(responses.DELETE, url, json={
            # simulate id not found
            "errors": [{"type": "not_found_no_permission"}]
        }, status=404)
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.delete_asset(99999999)

    @responses.activate
    def test_unexpected_api_response_delete_asset(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSET, {"asset_id": 1})
        responses.add(responses.DELETE, url, status=500)
        with pytest.raises(InvalidNetilionApiState):
            api_client.delete_asset(1)

    @responses.activate
    def test_bad_api_response_set_permissions(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.PERMISSIONS)
        responses.add(responses.POST, url, json={
            "errors": [{"type": "taken"}]
        }, match=[
            responses.json_params_matcher({
                "permission_type": ["can_read", "can_update"],
                "assignable": {"id": 666, "type": "User"},
                "permitable": {"id": 47, "type": "Asset"}
            })],
          status=400
        )
        ok = api_client.set_rw_permissions(asset_id=Asset(47).asset_id, user_id=666)
        assert not ok

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
    def test_bad_api_response_delete_webhook(self, configuration, api_client, capture_oauth_token):
        webhook = WebHook("https://test.com", ["event_a", "event_b"], 99)
        url = api_client.construct_url(api_client.ENDPOINT.WEBHOOK, {"application_id": 1, "webhook_id": 99})
        responses.add(responses.DELETE, url, status=400)
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.delete_webhook(webhook)

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
    def test_bad_api_response_find_assets_multiple(self, configuration, api_client, capture_oauth_token, client_application_response):
        base_url = api_client.construct_url(NetilionTechnicalApiClient.ENDPOINT.ASSETS)
        params = urllib.parse.urlencode({"serial_number": "0xdeadbeef"})
        url = f"{base_url}?{params}"
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "assets": [
                # duplicate asset
                {
                    "id": 1,
                    "serial_number": "0xdeadbeef",
                    "product": {"id": 1000},
                },{
                    "id": 1,
                    "serial_number": "0xdeadbeef",
                    "product": {"id": 1000},
                }
            ],
        }))
        with pytest.raises(InvalidNetilionApiState):
            api_client.find_asset("0xdeadbeef")

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
    def test_bad_api_response_get_asset_systems(self, configuration, api_client, capture_oauth_token, client_application_response):
        url = api_client.construct_url(api_client.ENDPOINT.ASSET_SYSTEMS, {"asset_id": 99})
        responses.add(responses.GET, url, json=self._add_pagination_info({
            "systems": [{
                    # no id
                    "specifications": [
                        {"id": 1, "thinga": "magicks"}
                    ]
                }]
        }))
        with pytest.raises(MalformedNetilionApiResponse):
            api_client.get_asset_systems(99)

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
        responses.add(responses.POST, url, status=400, json={
            'errors': [
                {'type': 'n/a', 'message': "messaggio"}
            ]
        })
        with pytest.raises(MalformedNetilionApiResponse) as exc_info:
            api_client.push_asset_values(AssetValues(Asset(1), asset_values))
        assert str(exc_info.value) == "MalformedNetilionApiResponse: [{'type': 'n/a', 'message': 'messaggio'}]"

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

    @responses.activate
    def test_post_document_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//documents"
        responses.add(responses.POST, url, status=201, json={
            "id": 1234,
            "name": "test_document",
            "classification": {
                "id": 1
            },
            "status": {
                "id": 1
            }
        }, match=[responses.json_params_matcher({
            "name": "test_document",
            "classification": {
                "id": 1
            },
            "status": {
                "id": 1
            }
        })])

        created_document = api_client.post_document("test_document", DocumentClassification.UNDEFINED, DocumentStatus.UNDEFINED)

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "POST"
        assert created_document.document_id == 1234

    @responses.activate
    def test_post_document_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//documents"
        responses.add(responses.POST, url, status=400, match=[responses.json_params_matcher({
            "name": "test_document",
            "classification": {
                "id": 1
            },
            "status": {
                "id": 1
            }
        })])

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.post_document("test_document", DocumentClassification.UNDEFINED, DocumentStatus.UNDEFINED)

    @responses.activate
    def test_get_asset_documents_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/documents?include=attachments"
        responses.add(responses.GET, url, status=200, json={
            "documents": [
                {
                    "id": 1234,
                    "name": "test_document",
                    "classification": {
                        "id": 1
                    },
                    "status": {
                        "id": 1
                    },
                    "attachments": [
                        {
                            "id": 98,
                            "file_name": "test_attachment.json",
                            "content_type": "application/json"
                        },
                        {
                            "id": 99,
                            "file_name": "test_attachment_2.json",
                            "content_type": "application/json"
                        }
                    ]
                },
                {
                    "id": 5678,
                    "name": "test_document_2",
                    "classification": {
                        "id": 1
                    },
                    "status": {
                        "id": 1
                    },
                    "attachments": [
                        {
                            "id": 97,
                            "file_name": "test_attachment.json",
                            "content_type": "application/json"
                        }
                    ]
                }
            ]
        })

        documents = api_client.get_asset_documents(99)

        assert len(documents) == 2

    @responses.activate
    def test_get_asset_documents_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/documents?include=attachments"
        responses.add(responses.GET, url, status=400)

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.get_asset_documents(99)

    @responses.activate
    def test_post_asset_document_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/documents"
        responses.add(responses.POST, url, status=204, match=[responses.json_params_matcher({
            "documents": [
                {
                    "id": 1234
                }
            ]
        })])

        api_client.post_asset_document(99, 1234)

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "POST"

    @responses.activate
    def test_post_asset_document_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/documents"
        responses.add(responses.POST, url, status=400, match=[responses.json_params_matcher({
            "documents": [
                {
                    "id": 1234
                }
            ]
        })])

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.post_asset_document(99, 1234)

    @responses.activate
    def test_download_json_attachment_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments/99/download"
        expected_attachment_dict = {
            "test": "testy test",
            "array": [
                {"nested": 1234},
                {"nested_2": "asdf"}
            ]
        }
        responses.add(responses.GET, url, status=200, body=json.dumps(expected_attachment_dict))

        actual_attachment_dict = api_client.download_json_attachment(99)

        assert expected_attachment_dict == actual_attachment_dict

    @responses.activate
    def test_download_json_attachment_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments/99/download"
        responses.add(responses.GET, url, status=400)

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.download_json_attachment(99)

    @responses.activate
    def test_upload_json_attachment_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments"
        attachment = {
            "test": "testy test",
            "array": [
                {"nested": 9876},
                {"nested_2": "asdf"}
            ]
        }
        responses.add(responses.POST, url, status=201, json={
            "id": 98,
            "file_name": "test_attachment.json",
            "content_type": "application/json"
        })

        created_attachment = api_client.upload_json_attachment(attachment, "test_attachment.json", 1234)

        assert created_attachment.attachment_id == 98
        assert created_attachment.file_name == "test_attachment.json"
        assert created_attachment.content_type == "application/json"
        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "POST"

    @responses.activate
    def test_upload_json_attachment_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments"
        attachment = {
            "test": "testy test",
            "array": [
                {"nested": 9876},
                {"nested_2": "asdf"}
            ]
        }
        responses.add(responses.POST, url, status=400)

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.upload_json_attachment(attachment, "test_attachment.json", 1234)

    @responses.activate
    def test_patch_json_attachment_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments/666"
        attachment = {
            "test": "testy test",
            "array": [
                {"nested": 9876},
                {"nested_2": "asdf"}
            ]
        }
        responses.add(responses.PATCH, url, status=204)

        api_client.patch_json_attachment(attachment, 666, "test_attachment.json")

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "PATCH"

    @responses.activate
    def test_patch_json_attachment_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//attachments/666"
        attachment = {
            "test": "testy test",
            "array": [
                {"nested": 9876},
                {"nested_2": "asdf"}
            ]
        }
        responses.add(responses.PATCH, url, status=400)

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.patch_json_attachment(attachment, 666, "test_attachment.json")

    @responses.activate
    def test_get_asset_specifications_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/specifications"
        responses.add(responses.GET, url, status=200, json={
            "eh.pcps.connection.standard": {
                "value": "802.11ax",
                "ui_visible": False,
                "updated_at": "2022-07-06T11:49:57.092Z"
            },
            "eh.pcps.connection.type": {
                "value": "wifi",
                "ui_visible": False,
                "updated_at": "2022-07-06T11:49:57.085Z"
            },
            "eh.pcps.values.exist": {
                "value": "true",
                "ui_visible": False,
                "updated_at": "2021-11-03T12:42:57.298Z"
            }
        })

        specifications = api_client.get_asset_specifications(99)

        assert len(specifications) == 3

    @responses.activate
    def test_get_asset_specifications_invalid_request(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//assets/99/specifications"
        responses.add(responses.GET, url, status=400)

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.get_asset_specifications(99)

    @responses.activate
    def test_patch_asset_specification_success(self, configuration, api_client, capture_oauth_token,
                                      client_application_response):
        url = "https://host.local/v1//assets/99/specifications"
        responses.add(responses.PATCH, url, status=204, match=[responses.json_params_matcher({
            "test_key_1": {
                "value": "test_value_1",
                "unit": "metre_per_second",
                "ui_visible": True
            },
            "test_key_2": {
                "value": "test_value_2",
                "ui_visible": False
            }
        })])
        specifications = [
            Specification("test_key_1", "test_value_1", Unit.unit_by_code("metre_per_second"), True),
            Specification("test_key_2", "test_value_2")
            ]

        api_client.patch_asset_specifications(99, specifications)

        assert responses.calls[1].request.url == url
        assert responses.calls[1].request.method == "PATCH"

    @responses.activate
    def test_patch_asset_specification_failure(self, configuration, api_client, capture_oauth_token,
                                               client_application_response):
        url = "https://host.local/v1//assets/99/specifications"
        responses.add(responses.PATCH, url, status=400, match=[responses.json_params_matcher({})])
        specifications = []

        with pytest.raises(MalformedNetilionApiRequest):
            api_client.patch_asset_specifications(99, specifications)

    @responses.activate
    def test_get_node_assets_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//nodes/99/assets"
        responses.add(responses.GET, url, status=200, json=self._add_pagination_info({
            "assets": [{
                "serial_number": "asset_1",
                "id": 1
            }, {
                "serial_number": "asset_2",
                "id": 2
            }]
        }))
        assets = api_client.get_node_assets(99)
        assert len(assets) == 2

    @responses.activate
    def test_get_node_assets_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//nodes/99/assets"
        responses.add(responses.GET, url, status=400)
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.get_node_assets(99)

    @responses.activate
    def test_get_nodes_success(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//nodes"
        responses.add(responses.GET, url, status=200, json=self._add_pagination_info({
            "nodes": [
                {
                    "name": "node_1",
                    "description": "string",
                    "hidden": "true",
                    "id": 0,
                    "type": {
                        "id": 0,
                        "href": "string"
                    },
                    "parent": {
                        "id": 0,
                        "href": "string"
                    },
                    "tenant": {
                        "id": 0,
                        "href": "string"
                    }
                },
                {
                    "name": "node_1",
                    "description": "string",
                    "hidden": "true",
                    "id": 0,
                    "type": {
                        "id": 0,
                        "href": "string"
                    },
                    "parent": {
                        "id": 0,
                        "href": "string"
                    },
                    "tenant": {
                        "id": 0,
                        "href": "string"
                    }
                }
            ]
        }))
        nodes = api_client.get_nodes()
        assert len(nodes) == 2

    @responses.activate
    def test_get_nodes_failure(self, configuration, api_client, capture_oauth_token):
        url = "https://host.local/v1//nodes"
        responses.add(responses.GET, url, status=400)
        with pytest.raises(MalformedNetilionApiRequest):
            api_client.get_nodes()
