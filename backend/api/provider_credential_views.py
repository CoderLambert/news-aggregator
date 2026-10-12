from django.db import transaction
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import UserProviderCredential
from api.services.provider_credentials import (
    PROVIDER_SPECS,
    ProviderCredentialError,
    encrypt_api_key,
    validate_api_key,
)


def _status_payload(credential=None):
    return {
        'configured': credential is not None,
        'provider': credential.provider if credential is not None else None,
        'provider_label': (
            PROVIDER_SPECS[credential.provider]['label']
            if credential is not None and credential.provider in PROVIDER_SPECS
            else None
        ),
        'updated_at': credential.updated_at.isoformat() if credential is not None else None,
    }


class ProviderCredentialView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        credential = UserProviderCredential.objects.filter(user=request.user).first()
        response = Response(_status_payload(credential))
        response['Cache-Control'] = 'no-store'
        return response

    def put(self, request):
        try:
            provider, api_key = validate_api_key(
                request.data.get('provider'), request.data.get('api_key'),
            )
            encrypted = encrypt_api_key(api_key, request.user.pk, provider)
        except ProviderCredentialError as exc:
            return Response(
                {'error_code': 'invalid_provider_credential', 'error': str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            credential, _ = UserProviderCredential.objects.update_or_create(
                user=request.user,
                defaults={'provider': provider, 'encrypted_api_key': encrypted},
            )
        response = Response(_status_payload(credential))
        response['Cache-Control'] = 'no-store'
        return response

    def delete(self, request):
        UserProviderCredential.objects.filter(user=request.user).delete()
        response = Response(_status_payload())
        response['Cache-Control'] = 'no-store'
        return response
