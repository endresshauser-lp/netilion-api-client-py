from typing import Optional


class ConfigurationParameters:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
    endpoint = None
    client_application_id = None
    client_application_name = None
    client_id = None
    client_secret = None
    api_url = None
    oauth_token_url = None
    username = None
    password = None

    @classmethod
    def get_empty(cls):
        return cls("", "", "", "", "")

    # pylint: disable=too-many-arguments
    def __init__(self,
                 endpoint: str,
                 client_id: str,
                 client_secret: str,
                 username: str,
                 password: str,
                 client_application_id: Optional[str] = None,
                 client_application_name: Optional[str] = None,
                 api_url: Optional[str] = None,
                 oauth_token_url: Optional[str] = None):
        super().__init__()
        self.endpoint = endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.client_application_id = client_application_id
        self.client_application_name = client_application_name
        self.api_url = api_url or f"{endpoint}/v1/"
        self.oauth_token_url = oauth_token_url or f"{endpoint}/oauth/token/"
