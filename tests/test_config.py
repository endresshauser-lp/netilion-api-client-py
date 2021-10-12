
from netilion.config import ConfigurationParameters


class TestConfiguration:
    def test_empty_configuration_parameters(self):
        empty = ConfigurationParameters.get_empty()
        for name in ("endpoint", "client_application_id", "client_application_name", "client_id", "client_secret", "api_url",
                     "oauth_token_url", "username", "password"):
            assert getattr(empty, name) == ""
