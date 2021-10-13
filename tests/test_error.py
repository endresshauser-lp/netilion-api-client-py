from netilion.error import *
from requests import Response


class TestError:
    def test_generic_error_without_message(self):
        err = GenericNetilionApiError()
        assert str(err) == ''

    def test_generic_error_with_json_response(self):
        resp = Response()
        resp.status_code = 400
        resp.headers = {"Content-Type": "application/json"}
        resp._content = b'{"errors": [{"type": "error_type"}]}'

        err = GenericNetilionApiError(resp)

        assert str(err) == "GenericNetilionApiError: [{'type': 'error_type'}]"

    def test_generic_error_with_non_json_response(self):
        resp = Response()
        resp.status_code = 400
        resp.headers = {"Content-Type": "application/xml"}
        resp._content = b'<html></html>'

        err = GenericNetilionApiError(resp)

        assert str(err) == "GenericNetilionApiError: <Response [400]>"

    def test_malformed_api_response_with_json_response(self):
        resp = Response()
        resp.status_code = 400
        resp.headers = {"Content-Type": "application/json"}
        resp._content = b'{"errors": [{"type": "error_type"}]}'

        err = MalformedNetilionApiResponse(resp)

        assert str(err) == "MalformedNetilionApiResponse: [{'type': 'error_type'}]"
