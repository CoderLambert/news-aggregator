from rest_framework.authentication import SessionAuthentication


class AnonymousCsrfSessionAuthentication(SessionAuthentication):
    """Require a valid CSRF token even when the request has no session user."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return super().authenticate(request)
