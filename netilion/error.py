import json
from typing import Optional

from requests import Response


class GenericNetilionApiError(Exception):
    __response: Optional[Response] = None

    def __init__(self, response: Optional[Response] = None) -> None:
        if response:
            super().__init__(response)
        else:
            super().__init__()
        self.__response = response

    def __str__(self) -> str:
        if self.__response is not None:
            try:
                return f"{self.__class__.__name__}: {self.__response.json()['errors']}"
            except (AttributeError, json.JSONDecodeError, KeyError):
                return f"{self.__class__.__name__}: {self.__response}"
        else:
            return super().__str__()


class MalformedNetilionApiResponse(GenericNetilionApiError):
    pass


class InvalidNetilionApiState(GenericNetilionApiError):
    pass


class MalformedNetilionApiRequest(GenericNetilionApiError):
    pass


class BadNetilionApiPermission(GenericNetilionApiError):
    pass


class QuotaExceeded(GenericNetilionApiError):
    pass
