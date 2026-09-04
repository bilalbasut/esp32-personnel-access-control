"""Backend test suite - JWT auth round trip (accounts/views.py, config/urls.py,
config/settings.py SIMPLE_JWT).

Covers the piece the manager specifically asked for: access+refresh tokens,
and logout actually discarding the refresh token (via simplejwt's
token_blacklist app) rather than just telling the frontend to forget it.
Deliberately does NOT use AuthenticatedAPITestCase (core/test_utils.py) -
that shortcuts real authentication via force_authenticate(), which is
exactly what these tests need to NOT do; here the token itself has to be
minted, sent, and (in the logout tests) actually rejected afterwards.
"""
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
        # ROTATE_REFRESH_TOKENS=True (config/settings.py SIMPLE_JWT) - a fresh
        # refresh token comes back too, and it must differ from the one spent.
        self.assertIn("refresh", response.data)
        self.assertNotEqual(response.data["refresh"], refresh)

    def test_rotated_refresh_token_replaces_the_original(self):
        first_refresh = self._login().data["refresh"]
        second_refresh = self.client.post(
            "/api/auth/refresh", {"refresh": first_refresh}, format="json"
        ).data["refresh"]

        # BLACKLIST_AFTER_ROTATION=True - the original refresh token is spent
        # the moment it's rotated, not just "superseded".
        reuse_response = self.client.post(
            "/api/auth/refresh", {"refresh": first_refresh}, format="json"
        )
        self.assertEqual(reuse_response.status_code, status.HTTP_401_UNAUTHORIZED)

        # ...while the new one it handed back still works.
        retry_response = self.client.post(
            "/api/auth/refresh", {"refresh": second_refresh}, format="json"
        )
        self.assertEqual(retry_response.status_code, status.HTTP_200_OK)

    def test_logout_blacklists_the_refresh_token(self):
        refresh = self._login().data["refresh"]

        logout_response = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)

        # The blacklisted refresh token must no longer mint new access tokens.
        response = self.client.post("/api/auth/refresh", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_token_returns_400(self):
        response = self.client.post("/api/auth/logout", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout_with_already_invalid_refresh_token_still_succeeds(self):
        # LogoutView deliberately swallows TokenError (accounts/views.py) -
        # logout's goal ("this token can't be used again") is already true
        # for a token that's bogus/expired/already blacklisted, so this is a
        # success, not a 400.
        response = self.client.post("/api/auth/logout", {"refresh": "not-a-real-token"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_with_no_authorization_header_succeeds(self):
        # LogoutView.permission_classes = [AllowAny] (accounts/views.py) -
        # reachable with no access token attached at all, which is exactly
        # how the Vue frontend calls it now (src/api.js api.logout(), a raw
        # fetch() with no Authorization header - see the comment there for why).
        refresh = self._login().data["refresh"]
        response = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_with_an_invalid_access_token_header_returns_401_not_the_view(self):
        """Regression test for a real bug this suite caught: LogoutView being
        AllowAny does NOT make it reachable with a garbage/expired access
        token in the Authorization header. DRF authenticates BEFORE checking
        permissions (Request._authenticate() -> perform_authentication(),
        called from APIView.initial() ahead of check_permissions()) - if
        JWTAuthentication.authenticate() raises on a bad token, that 401
        short-circuits the request and LogoutView.post() (and its AllowAny)
        is never reached at all, so the refresh token would NOT get
        blacklisted. This is exactly why api.js's logout() deliberately
        sends a bare fetch() with no Authorization header instead of going
        through the normal authedFetch() helper - see the comment there."""
        refresh = self._login().data["refresh"]
        response = self.client.post(
            "/api/auth/logout", {"refresh": refresh}, format="json",
            HTTP_AUTHORIZATION="Bearer not-a-real-access-token",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        # Confirms the refresh token was untouched by the failed attempt above.
        retry = self.client.post("/api/auth/logout", {"refresh": refresh}, format="json")
        self.assertEqual(retry.status_code, status.HTTP_200_OK)
