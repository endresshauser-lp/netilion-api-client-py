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
            if hasattr(self.__response, "headers") and \
                    isinstance(self.__response.headers, dict) and \
                    'application/json' in self.__response.headers.get('Content-Type'):
                return f"{self.__class__.__name__}: {self.__response.json()}"
            else:
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
