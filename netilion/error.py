class GenericNetilionApiError(Exception):
    pass


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
