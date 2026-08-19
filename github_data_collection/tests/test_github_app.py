import unittest
from unittest.mock import Mock, patch

import requests

from github_data_collection.github_app import get_authenticated_user


def response(status_code, payload=None):
    result = Mock(status_code=status_code)
    result.json.return_value = payload or {}
    if status_code >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(str(status_code))
    return result


class AuthenticatedUserTests(unittest.TestCase):
    @patch("github_data_collection.github_app.time.sleep")
    @patch("github_data_collection.github_app.requests.get")
    def test_transient_gateway_errors_are_retried_with_same_bearer_token(
        self, get, sleep
    ):
        get.side_effect = [
            response(503), response(502), response(200, {"login": "octocat"})
        ]

        user = get_authenticated_user("user-token")

        self.assertEqual(user, {"login": "octocat"})
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        for call in get.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer user-token")
            self.assertEqual(
                call.kwargs["headers"]["Accept"], "application/vnd.github+json"
            )
            self.assertEqual(
                call.kwargs["headers"]["X-GitHub-Api-Version"], "2022-11-28"
            )

    @patch("github_data_collection.github_app.time.sleep")
    @patch("github_data_collection.github_app.requests.get")
    def test_unauthorized_response_is_not_retried(self, get, sleep):
        get.return_value = response(401)

        with self.assertRaises(requests.HTTPError):
            get_authenticated_user("invalid-token")

        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
