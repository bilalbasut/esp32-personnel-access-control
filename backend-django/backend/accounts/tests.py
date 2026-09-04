"""JWT auth round trip. Deliberately not AuthenticatedAPITestCase - force_authenticate() would
skip the real token minting/sending/rejection these tests need to exercise."""
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Operator


class JWTAuthFlowTests(APITestCase):
    def setUp(self):
        self.password = "s3cure-test-pw!"
        self.operator = Operator.objects.create_user(username="jwt-tester", password=self.password)

    def _login(self):
        return self.client.post(
            "/api/auth/login", {"username": "jwt-tester", "password": self.password}, format="json"
        )

    def test_login_returns_access_and_refresh_tokens(self):
        response = self._login()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_with_wrong_password_returns_401(self):
        response = self.client.post(
            "/api/auth/login", {"username": "jwt-tester", "password": "wrong-password"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_access_token_authenticates_a_protected_endpoint(self):
        access = self._login().data["access"]

        response = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["username"], "jwt-tester")

    def test_protected_endpoint_without_token_returns_401(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_with_garbage_token_returns_401(self):
        response = self.client.get("/api/auth/me", HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_returns_a_new_access_token(self):
        refresh = self._login().data["refresh"]

        response = self.client.post("/api/auth/refresh", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)  # ROTATE_REFRESH_TOKENS: fresh one differs from spent
        self.assertNotEqual(response.data["refresh"], refresh)

    def test_rotated_refresh_token_replaces_the_original(self):
        first_refresh = self._login().data["refresh"]
        second_refresh = self.client.post(
            "/api/auth/refresh", {"refresh": first_refresh}, format="json"
        ).data["refresh"]

        # BLACKLIST_AFTER_ROTATION: original is spent the moment it's rotated.
        reuse_response = self.client.post(
            "/api/auth/refresh", {"refresh": first_refresh}, format="json"
        )
        self.assertEqual(reuse_response.status_code, status.HTTP_401_UNAUTHORIZED)

        retry_response = self.client.post(  # new one it handed back still works
            "/api/auth/refresh", {"refresh": second_refresh}, format="json"
        )
        self.assertEqual(retry_response.status_code, status.HTTP_200_OK)

    def test_logout_blacklists_the_refresh_token(self):
        refresh = self._login().data["refresh"]

        logout_response = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)

        response = self.client.post("/api/auth/refresh", {"refresh": refresh}, format="json")  # must no longer mint tokens
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_token_returns_400(self):
        response = self.client.post("/api/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_with_already_invalid_refresh_token_still_succeeds(self):
        # LogoutView swallows TokenError - already-invalid token means the goal is already met.
        response = self.client.post("/api/auth/logout", {"refresh": "not-a-real-token"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_with_no_authorization_header_succeeds(self):
        # AllowAny - reachable with no access token, same as api.js's bare fetch() logout call.
        refresh = self._login().data["refresh"]
        response = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_with_an_invalid_access_token_header_returns_401_not_the_view(self):
        """DRF authenticates BEFORE checking permissions - a bad access token 401s
        before AllowAny/LogoutView.post() is ever reached, refresh token never blacklisted."""
        refresh = self._login().data["refresh"]
        response = self.client.post(
            "/api/auth/logout", {"refresh": refresh}, format="json",
            HTTP_AUTHORIZATION="Bearer not-a-real-access-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        retry = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")  # untouched by failed attempt
        self.assertEqual(retry.status_code, status.HTTP_200_OK)
