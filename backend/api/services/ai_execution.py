"""T01 transitional consumer fence: new personal connections, no inference yet.

T02 and T03 will bind verified models and task preferences. Until then, an
account with any connection never silently falls back to a site-admin key.
"""
from api.ai_connection_models import UserAIConnection


class PersonalAIUnavailable(RuntimeError):
    pass


def has_personal_connection(user) -> bool:
    return bool(user and getattr(user, 'is_authenticated', False)
                and UserAIConnection.objects.filter(user_id=user.pk,
                    is_deleted=False).exists())


def personal_clients_for_user(user):
    if not has_personal_connection(user):
        return []
    raise PersonalAIUnavailable('个人 AI 连接已保存；请等待模型与用途配置完成。')
