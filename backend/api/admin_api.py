"""Shared administration permission and error payload; no collector imports."""
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

class IsActiveSuperuser(BasePermission):
    message = '只有超级管理员可以访问管理功能。'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def error_response(code, message, http_status=status.HTTP_400_BAD_REQUEST, *, fields=None):
    payload = {'code': code, 'message': message}
    if fields:
        payload['fields'] = fields
    return Response(payload, status=http_status)
