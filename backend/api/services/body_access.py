"""Grantable reader access, independent of publisher contracts and site switches."""
PERMISSION = 'api.view_article_body'

def can_view_article_body(user):
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(PERMISSION))
