import dataclasses
import random
import time

import mock
import pytest
import requests
import requests_mock as req_mock

from up42.http import config, oauth

HTTP_TIMEOUT = 10
TOKEN_VALUE = "some-token"
TOKEN_URL = "https://localhost/oauth/token"
account_credentials = config.AccountCredentialsSettings(username="some-user", password="some-pass")


def match_account_authentication_request_body(request):
    return request.text == (
        "grant_type=password&" f"username={account_credentials.username}&" f"password={account_credentials.password}"
    )


class TestAccountTokenRetriever:
    def test_should_retrieve(self, requests_mock: req_mock.Mocker):
        retrieve = oauth.AccountTokenRetriever(account_credentials)
        requests_mock.post(
            TOKEN_URL,
            json={"access_token": TOKEN_VALUE},
            request_headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            additional_matcher=match_account_authentication_request_body,
        )
        assert retrieve(requests.Session(), TOKEN_URL, HTTP_TIMEOUT) == TOKEN_VALUE
        assert requests_mock.called_once

    def test_fails_to_retrieve_for_bad_response(self, requests_mock: req_mock.Mocker):
        retrieve = oauth.AccountTokenRetriever(account_credentials)
        requests_mock.post(
            TOKEN_URL,
            status_code=random.randint(400, 599),
            request_headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            additional_matcher=match_account_authentication_request_body,
        )
        with pytest.raises(oauth.WrongCredentials):
            retrieve(requests.Session(), TOKEN_URL, HTTP_TIMEOUT)
        assert requests_mock.called_once


mock_request = mock.MagicMock()
mock_request.headers = {}
token_settings = config.TokenProviderSettings(
    token_url=TOKEN_URL,
    duration=2,
    timeout=HTTP_TIMEOUT,
)


class TestUp42Auth:
    def test_should_fetch_token_when_created(self):
        retrieve = mock.MagicMock(return_value=TOKEN_VALUE)
        up42_auth = oauth.Up42Auth(retrieve=retrieve, token_settings=token_settings)
        up42_auth(mock_request)
        assert mock_request.headers["Authorization"] == f"Bearer {TOKEN_VALUE}"
        assert up42_auth.token.access_token == TOKEN_VALUE
        retrieve.assert_called_once()
        assert TOKEN_URL, HTTP_TIMEOUT == retrieve.call_args.args[1:]

    def test_should_fetch_token_when_expired(self):
        second_token = "token2"
        retrieve = mock.MagicMock(side_effect=["token1", second_token])
        up42_auth = oauth.Up42Auth(retrieve=retrieve, token_settings=token_settings)
        time.sleep(token_settings.duration + 1)
        up42_auth(mock_request)

        assert mock_request.headers["Authorization"] == f"Bearer {second_token}"
        assert up42_auth.token.access_token == second_token
        assert TOKEN_URL, HTTP_TIMEOUT == retrieve.call_args.args[1:]
        assert retrieve.call_count == 2


class TestDetectSettings:
    def test_should_detect_account_credentials(self):
        assert oauth.detect_settings(dataclasses.asdict(account_credentials)) == account_credentials

    def test_should_accept_empty_credentials(self):
        credentials = {"username": None, "password": None}
        assert not oauth.detect_settings(credentials)

    def test_should_accept_missing_credentials(self):
        assert not oauth.detect_settings(None)

    def test_fails_if_credentials_are_incomplete(self):
        credentials = {"key1": "value1", "key2": None}
        with pytest.raises(oauth.IncompleteCredentials):
            oauth.detect_settings(credentials)

    def test_fails_if_credentials_are_invalid(self):
        credentials = {"key1": "value1", "key2": "value2"}
        with pytest.raises(oauth.InvalidCredentials):
            oauth.detect_settings(credentials)


class TestDetectRetriever:
    def test_should_detect_account_retriever(self):
        assert isinstance(oauth.detect_retriever(account_credentials), oauth.AccountTokenRetriever)

    def test_fails_if_settings_are_not_recognized(self):
        credentials = mock.MagicMock()
        with pytest.raises(oauth.UnsupportedSettings) as exc_info:
            oauth.detect_retriever(credentials)
        assert str(credentials) in str(exc_info.value)
