from typing import Optional, Any


class ConfigurationParameters(dict):
    __params = {}
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
        self.__params["endpoint"] = endpoint
        self.__params["subscription_id"] = subscription_id
        self.__params["subscription_name"] = subscription_name
        self.__params["client_id"] = client_id
        self.__params["client_secret"] = client_secret
        self.__params["api_url"] = api_url
        self.__params["oauth_token_url"] = oauth_token_url
        self.__params["username"] = username
        self.__params["password"] = password
        self.__params["hit_server_for_tests"] = hit_server_for_tests

    def __getattribute__(self, name: str) -> Any:
        return self.__params.get(name)

    def __setattr__(self, name: str, value: Any) -> None:
        return self.__params.__setattr__(name, value)


class LOGGING:
    @staticmethod
    def configure():
        pass
