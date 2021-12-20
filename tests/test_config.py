
from netilion.config import ConfigurationParameters


class TestConfiguration:
    def test_empty_configuration_parameters(self):
        empty = ConfigurationParameters.get_empty()
        for name in ("endpoint",
                     "client_application_id",
                     "client_application_name",
                     "client_id",
                     "client_secret",
                     "username",
                     "password"):
            assert getattr(empty, name) in ("", None)

    def test_auto_api_url(self):
        conf = ConfigurationParameters("https://host.local", "clientid", "clientsecret", "user", "pass")
        assert conf.api_url == "https://host.local/v1/"

    def test_auto_oauth_token_url(self):
        conf = ConfigurationParameters("https://host.local", "clientid", "clientsecret", "user", "pass")
        assert conf.oauth_token_url == "https://host.local/oauth/token/"
