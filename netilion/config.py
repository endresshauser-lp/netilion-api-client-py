from typing import Optional


class ConfigurationParameters:
    endpoint = None
    subscription_id = None
    subscription_name = None
    client_id = None
    client_secret = None
    api_url = None
    oauth_token_url = None
    username = None
    password = None

    hit_server_for_tests: bool = False

    def __init__(self, endpoint: str, subscription_id: Optional[str], subscription_name: str, client_id: str, client_secret: str, api_url: str, oauth_token_url: Optional[str], username: str, password: str, hit_server_for_tests: bool = False) -> None:
        super().__init__()
        self.endpoint = endpoint
        self.subscription_id = subscription_id
        self.subscription_name = subscription_name
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_url = api_url
        self.oauth_token_url = oauth_token_url
        self.username = username
        self.password = password
        self.hit_server_for_tests = hit_server_for_tests


class LOGGING:
    @staticmethod
    def configure():
        pass
