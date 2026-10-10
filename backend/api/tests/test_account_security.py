import hashlib
import hmac
import ipaddress
import queue
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections
from django.test import override_settings
from django.utils import timezone as django_timezone
from rest_framework.test import APIClient

from api.models import (
    AuthRateBucket,
    Category,
    News,
    ProviderComparison,
    SignupInvite,
    Source,
)
from api.services import account_security
from api.services.account_security import (
    AuthSecurityBusy,
    InvalidClientAddress,
    RateLimitExceeded,
    RegistrationUnavailable,
    SignupInviteRequired,
    create_registered_user,
    issue_signup_invite,
    reserve_login_attempts,
    reserve_registration_attempts,
)


VALID_PASSWORD = 'Sufficiently-Strong-Passphrase-93!'
DEFAULT_IP = '198.51.100.20'


def _csrf_token(client, *, remote_addr=DEFAULT_IP):
    response = client.get('/api/auth/csrf/', REMOTE_ADDR=remote_addr)
    assert response.status_code == 200
    return response.cookies['csrftoken'].value


def _secure_post(client, path, data, token, *, remote_addr=DEFAULT_IP, **extra):
    return client.post(
        path,
        data,
        format='json',
        secure=True,
        REMOTE_ADDR=remote_addr,
        HTTP_ORIGIN='https://testserver',
        HTTP_X_CSRFTOKEN=token,
        **extra,
    )


def _registration_payload(*, username='account-reader', email='reader@example.test', password=VALID_PASSWORD):
    return {'username': username, 'email': email, 'password': password}


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True)
def test_anonymous_login_requires_csrf_before_rate_reservation_or_password_auth(monkeypatch):
    authenticate = patch('api.views.authenticate')
    with authenticate as mocked_authenticate:
        client = APIClient(enforce_csrf_checks=True)
        rejected_without_cookie = client.post(
            '/api/auth/login/',
            {'username': 'victim', 'password': 'wrong'},
            format='json',
            REMOTE_ADDR=DEFAULT_IP,
        )
        assert rejected_without_cookie.status_code == 403
        register_without_cookie = client.post(
            '/api/auth/register/',
            _registration_payload(username='csrf-blocked-register'),
            format='json',
            REMOTE_ADDR=DEFAULT_IP,
        )
        assert register_without_cookie.status_code == 403

        token = _csrf_token(client)
        rejected_token = _secure_post(
            client,
            '/api/auth/login/',
            {'username': 'victim', 'password': 'wrong'},
            'not-the-cookie-token',
        )
        assert rejected_token.status_code == 403

        rejected_origin = client.post(
            '/api/auth/login/',
            {'username': 'victim', 'password': 'wrong'},
            format='json',
            secure=True,
            REMOTE_ADDR=DEFAULT_IP,
            HTTP_ORIGIN='https://evil.example.test',
            HTTP_X_CSRFTOKEN=token,
        )
        assert rejected_origin.status_code == 403
        register_rejected_origin = client.post(
            '/api/auth/register/',
            _registration_payload(username='csrf-blocked-register'),
            format='json',
            secure=True,
            REMOTE_ADDR=DEFAULT_IP,
            HTTP_ORIGIN='https://evil.example.test',
            HTTP_X_CSRFTOKEN=token,
        )
        assert register_rejected_origin.status_code == 403

    mocked_authenticate.assert_not_called()
    assert AuthRateBucket.objects.count() == 0


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True)
def test_valid_https_origin_login_rotates_session_and_logout_ends_it():
    user = User.objects.create_user(username='session-rotation-user', password=VALID_PASSWORD)
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)

    anonymous_session = client.session
    anonymous_session['pre_auth_marker'] = 'rotate-me'
    anonymous_session.save()
    previous_session_key = anonymous_session.session_key
    client.cookies[settings.SESSION_COOKIE_NAME] = previous_session_key

    logged_in = _secure_post(
        client,
        '/api/auth/login/',
        {'username': user.username, 'password': VALID_PASSWORD},
        token,
    )
    assert logged_in.status_code == 200
    assert client.cookies[settings.SESSION_COOKIE_NAME].value != previous_session_key
    assert client.get('/api/auth/me/').json()['id'] == user.pk

    token = _csrf_token(client)
    logged_out = _secure_post(client, '/api/auth/logout/', {}, token)
    assert logged_out.status_code == 200
    assert client.get('/api/auth/me/').status_code == 403


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True)
def test_login_rate_limit_precedes_authenticate_and_ignores_forwarded_for():
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)
    with patch('api.views.authenticate', return_value=None) as authenticate:
        responses = [
            _secure_post(
                client,
                '/api/auth/login/',
                {'username': 'CaseFoldUser', 'password': 'incorrect'},
                token,
                HTTP_X_FORWARDED_FOR=f'203.0.113.{index}',
            )
            for index in range(1, 7)
        ]

    assert [response.status_code for response in responses] == [401] * 5 + [429]
    assert responses[-1].json()['error_code'] == 'auth_rate_limited'
    assert 1 <= int(responses[-1]['Retry-After']) <= 600
    assert authenticate.call_count == 5
    user_bucket = AuthRateBucket.objects.get(kind='login_ip_username')
    ip_bucket = AuthRateBucket.objects.get(kind='login_ip')
    assert user_bucket.count == ip_bucket.count == 5
    assert len(user_bucket.key) == len(ip_bucket.key) == 64
    assert DEFAULT_IP not in user_bucket.key and 'casefolduser' not in user_bucket.key


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True)
def test_invalid_remote_address_is_rejected_without_forwarded_fallback():
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)
    with patch('api.views.authenticate') as authenticate:
        response = _secure_post(
            client,
            '/api/auth/login/',
            {'username': 'reader', 'password': 'wrong'},
            token,
            remote_addr='',
            HTTP_X_FORWARDED_FOR='203.0.113.20',
        )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'invalid_client_address'
    authenticate.assert_not_called()
    assert AuthRateBucket.objects.count() == 0


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True)
def test_busy_security_lock_returns_503_before_password_authentication(monkeypatch):
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)
    monkeypatch.setattr('api.views.reserve_login_attempts', lambda *_args: (_ for _ in ()).throw(AuthSecurityBusy()))

    with patch('api.views.authenticate') as authenticate:
        response = _secure_post(
            client,
            '/api/auth/login/',
            {'username': 'reader', 'password': 'incorrect'},
            token,
        )

    assert response.status_code == 503
    assert response.json()['error_code'] == 'auth_security_busy'
    authenticate.assert_not_called()


@pytest.mark.parametrize(
    ('payload',),
    [
        (_registration_payload(username='has whitespace'),),
        (_registration_payload(email='not-an-email'),),
        (_registration_payload(password='short'),),
        (_registration_payload(password='p' * 1025),),
        ({'username': ['not', 'text'], 'email': 'reader@example.test', 'password': VALID_PASSWORD},),
    ],
)
@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='development')
def test_invalid_registration_is_rejected_by_django_validators_before_user_creation(payload):
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)
    response = _secure_post(client, '/api/auth/register/', payload, token)

    assert response.status_code == 400
    assert response.json()['error_code'] == 'invalid_registration'
    assert not User.objects.filter(username='account-reader').exists()


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='development')
def test_development_signup_remains_open_but_uses_csrf_password_validation_and_rate_limit():
    client = APIClient(enforce_csrf_checks=True)
    token = _csrf_token(client)
    response = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='development-signup-reader'),
        token,
    )

    assert response.status_code == 201
    assert User.objects.filter(username='development-signup-reader').exists()
    assert AuthRateBucket.objects.get(kind='register_ip').count == 1
    assert AuthRateBucket.objects.get(kind='register_global').count == 1


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='production')
def test_production_invite_is_email_bound_atomic_and_consumed_once():
    email = 'invited-reader@example.test'
    token = issue_signup_invite(email, 24)
    client = APIClient(enforce_csrf_checks=True)
    csrf = _csrf_token(client)

    missing = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='missing-invite', email=email),
        csrf,
    )
    wrong_email = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='wrong-email', email='other@example.test') | {'invite_token': token},
        csrf,
    )
    wrong_token = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='wrong-token', email=email) | {'invite_token': 'not-a-valid-token'},
        csrf,
    )
    assert missing.status_code == wrong_email.status_code == wrong_token.status_code == 403
    assert missing.json()['error_code'] == wrong_email.json()['error_code'] == wrong_token.json()['error_code'] == 'invite_required'

    legacy_field = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='legacy-invite-field', email=email) | {'invite': token},
        csrf,
        remote_addr='198.51.100.21',
    )
    assert legacy_field.status_code == 403
    assert legacy_field.json()['error_code'] == 'invite_required'
    assert not User.objects.filter(username='legacy-invite-field').exists()

    accepted = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='invited-reader', email=email) | {'invite_token': token},
        csrf,
    )
    assert accepted.status_code == 201
    user = User.objects.get(username='invited-reader')
    invite = SignupInvite.objects.get()
    assert invite.consumed_at is not None
    assert invite.consumed_by_id == user.pk
    assert invite.token_digest == hashlib.sha256(token.encode()).hexdigest()
    assert token not in invite.token_digest

    csrf = _csrf_token(client)
    reuse = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='invitation-reuse', email=email) | {'invite_token': token},
        csrf,
    )
    assert reuse.status_code == 403
    assert reuse.json()['error_code'] == 'invite_required'
    assert not User.objects.filter(username='invitation-reuse').exists()


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='production')
def test_duplicate_username_has_uniform_error_and_does_not_consume_invite():
    User.objects.create_user(username='already-registered', password=VALID_PASSWORD)
    email = 'new-person@example.test'
    token = issue_signup_invite(email, 24)
    client = APIClient(enforce_csrf_checks=True)
    csrf = _csrf_token(client)

    response = _secure_post(
        client,
        '/api/auth/register/',
        _registration_payload(username='already-registered', email=email) | {'invite_token': token},
        csrf,
    )

    assert response.status_code == 400
    assert response.json()['error_code'] == 'registration_unavailable'
    assert 'already-registered' not in response.content.decode()
    assert SignupInvite.objects.get().consumed_at is None


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='production')
def test_expired_and_consumed_invites_share_the_invite_required_response():
    expired = issue_signup_invite('expired@example.test', 1)
    expired_invite = SignupInvite.objects.get()
    expired_invite.expires_at = django_timezone.now() - timedelta(seconds=1)
    expired_invite.save(update_fields=['expires_at'])
    consumed = issue_signup_invite('consumed@example.test', 24)
    consumed_invite = SignupInvite.objects.get(token_digest=hashlib.sha256(consumed.encode()).hexdigest())
    consumed_invite.consumed_at = django_timezone.now()
    consumed_invite.save(update_fields=['consumed_at'])

    client = APIClient(enforce_csrf_checks=True)
    csrf = _csrf_token(client)
    for index, (email, token) in enumerate(
        [('expired@example.test', expired), ('consumed@example.test', consumed)],
    ):
        response = _secure_post(
            client,
            '/api/auth/register/',
            _registration_payload(username=f'invalid-invite-{index}', email=email) | {'invite_token': token},
            csrf,
        )
        assert response.status_code == 403
        assert response.json()['error_code'] == 'invite_required'
    assert User.objects.filter(username__startswith='invalid-invite-').count() == 0


@pytest.mark.django_db
def test_invite_command_prints_single_token_and_validates_expiry():
    from io import StringIO

    output = StringIO()
    call_command(
        'create_signup_invite',
        '--email', 'operator@example.test',
        '--expires-hours', '24',
        stdout=output,
    )
    token = output.getvalue().strip()
    invite = SignupInvite.objects.get()
    assert token
    assert output.getvalue() == f'{token}\n'
    assert invite.token_digest == hashlib.sha256(token.encode()).hexdigest()
    assert invite.email == 'operator@example.test'
    assert django_timezone.now() < invite.expires_at <= django_timezone.now() + timedelta(hours=24, seconds=2)


@pytest.mark.parametrize('hours', [0, 169])
@pytest.mark.django_db
def test_invite_command_rejects_expiration_outside_one_to_168_hours(hours):
    from io import StringIO

    with pytest.raises(CommandError, match='1 to 168'):
        call_command(
            'create_signup_invite',
            '--email', 'operator@example.test',
            '--expires-hours', str(hours),
            stdout=StringIO(),
        )
    assert SignupInvite.objects.count() == 0


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_SIGNUP_ENABLED=True, DJANGO_ENV='production')
def test_session_failure_rolls_back_new_user_and_invite_consumption(monkeypatch):
    email = 'rollback@example.test'
    token = issue_signup_invite(email, 24)
    client = APIClient(enforce_csrf_checks=True)
    csrf = _csrf_token(client)

    def fail_session_save(*_args, **_kwargs):
        raise RuntimeError('session save failure')

    monkeypatch.setattr('django.contrib.sessions.backends.db.SessionStore.save', fail_session_save)

    with pytest.raises(RuntimeError, match='session save failure'):
        _secure_post(
            client,
            '/api/auth/register/',
            _registration_payload(username='rolled-back-user', email=email) | {'invite_token': token},
            csrf,
        )

    assert not User.objects.filter(username='rolled-back-user').exists()
    assert SignupInvite.objects.get().consumed_at is None


@pytest.mark.django_db
def test_fixed_windows_and_hmac_buckets_do_not_store_raw_identifiers():
    start = datetime(2026, 1, 2, 3, 40, tzinfo=timezone.utc)
    reserve_login_attempts('203.0.113.50', 'CaseSensitiveUser', now=start)
    first = AuthRateBucket.objects.get(kind='login_ip_username')
    expected = hmac.new(
        settings.SECRET_KEY.encode(),
        b'login_ip_username\0' + b'203.0.113.50\0casesensitiveuser',
        hashlib.sha256,
    ).hexdigest()
    assert first.key == expected
    assert first.window_start == datetime(2026, 1, 2, 3, 40, tzinfo=timezone.utc)
    assert '203.0.113.50' not in first.key and 'casesensitiveuser' not in first.key

    reserve_login_attempts('203.0.113.50', 'casesensitiveuser', now=start + timedelta(seconds=599))
    assert AuthRateBucket.objects.get(kind='login_ip_username', window_start=first.window_start).count == 2
    reserve_login_attempts('203.0.113.50', 'casesensitiveuser', now=start + timedelta(seconds=600))
    assert AuthRateBucket.objects.filter(kind='login_ip_username').count() == 2
    assert sorted(AuthRateBucket.objects.filter(kind='login_ip_username').values_list('count', flat=True)) == [1, 2]


@pytest.mark.django_db
def test_registration_fixed_window_caps_ip_and_global_buckets():
    for _ in range(5):
        reserve_registration_attempts('198.51.100.70')
    with pytest.raises(RateLimitExceeded) as limited_ip:
        reserve_registration_attempts('198.51.100.70')
    assert 1 <= limited_ip.value.retry_after <= 3600
    assert AuthRateBucket.objects.get(kind='register_ip').count == 5

    for index in range(95):
        address = str(ipaddress.IPv4Address(int(ipaddress.IPv4Address('192.0.2.101')) + index))
        reserve_registration_attempts(address)
    with pytest.raises(RateLimitExceeded) as limited_global:
        reserve_registration_attempts('203.0.113.240')
    assert 1 <= limited_global.value.retry_after <= 3600
    global_bucket = AuthRateBucket.objects.get(kind='register_global')
    assert global_bucket.count == 100


@pytest.mark.django_db
def test_sqlite_busy_retries_are_bounded_and_fail_closed(monkeypatch):
    attempts = []
    sleeps = []

    def busy_lock():
        attempts.append(1)
        raise account_security.OperationalError('database is locked')

    monkeypatch.setattr(account_security, '_write_security_lock', busy_lock)
    monkeypatch.setattr(account_security.time, 'sleep', sleeps.append)
    with pytest.raises(AuthSecurityBusy):
        account_security.run_with_security_lock(lambda: pytest.fail('operation ran without the lock'))

    assert len(attempts) == 3
    assert sleeps == [0.02, 0.04]


@pytest.mark.django_db(transaction=True)
def test_concurrent_login_bucket_reservations_never_exceed_limit():
    workers = 8
    gate = threading.Barrier(workers)
    outcomes = queue.Queue()

    def reserve():
        close_old_connections()
        try:
            gate.wait(timeout=5)
            reserve_login_attempts('203.0.113.88', 'same-account')
            outcomes.put('allowed')
        except RateLimitExceeded:
            outcomes.put('limited')
        except AuthSecurityBusy:
            outcomes.put('busy')
        except Exception as error:  # Preserve unexpected thread errors for the main assertion.
            outcomes.put(error)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=reserve) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)

    assert all(not thread.is_alive() for thread in threads)
    results = [outcomes.get_nowait() for _ in threads]
    assert all(result in {'allowed', 'limited', 'busy'} for result in results)
    allowed = results.count('allowed')
    assert allowed <= 5

    extra_allowed = 0
    rate_limited = False
    for _ in range(6):
        try:
            reserve_login_attempts('203.0.113.88', 'same-account')
            extra_allowed += 1
        except RateLimitExceeded:
            rate_limited = True
            break
    assert rate_limited
    assert allowed + extra_allowed == 5
    assert AuthRateBucket.objects.get(kind='login_ip_username').count == 5


@pytest.mark.django_db(transaction=True)
def test_concurrent_invite_consumption_creates_at_most_one_user():
    email = 'race-invite@example.test'
    token = issue_signup_invite(email, 24)
    workers = 2
    gate = threading.Barrier(workers)
    outcomes = queue.Queue()

    def register(index):
        close_old_connections()
        try:
            gate.wait(timeout=5)
            user = create_registered_user(
                username=f'invite-race-{index}',
                email=email,
                password=VALID_PASSWORD,
                invite_token=token,
                require_invite=True,
            )
            outcomes.put(('created', user.pk))
        except (SignupInviteRequired, AuthSecurityBusy) as error:
            outcomes.put(('rejected', type(error).__name__))
        except Exception as error:
            outcomes.put(error)
        finally:
            close_old_connections()

    threads = [threading.Thread(target=register, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=8)

    assert all(not thread.is_alive() for thread in threads)
    results = [outcomes.get_nowait() for _ in threads]
    assert all(isinstance(result, tuple) for result in results)
    created = [result for result in results if result[0] == 'created']
    assert len(created) <= 1

    if not created:
        winner = create_registered_user(
            username='invite-race-serial-winner',
            email=email,
            password=VALID_PASSWORD,
            invite_token=token,
            require_invite=True,
        )
        created = [('created', winner.pk)]

    with pytest.raises(SignupInviteRequired):
        create_registered_user(
            username='invite-race-late-user',
            email=email,
            password=VALID_PASSWORD,
            invite_token=token,
            require_invite=True,
        )
    invite = SignupInvite.objects.get()
    assert User.objects.filter(username__startswith='invite-race-').count() == 1
    assert invite.consumed_by_id == created[0][1]
    assert invite.consumed_at is not None


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='full', PUBLIC_AI_ENABLED=True)
def test_provider_comparisons_require_an_active_superuser_without_leaking_diagnostics(monkeypatch):
    category = Category.objects.create(name='Security category', slug='security-category')
    source = Source.objects.create(name='Security source', url='https://source.example.test')
    news = News.objects.create(
        title='Sensitive comparison article',
        content='summary',
        publish_time=django_timezone.now(),
        source=source,
        category=category,
        url='https://news.example.test/sensitive-article',
    )
    comparison = ProviderComparison.objects.create(
        run_id='a0f84cc1-0cb0-4b09-bf5b-f12364835c3c',
        news=news,
        url='https://news.example.test/private-diagnostic-path',
        provider='private-provider',
        ok=False,
        error='private-provider-error-detail',
    )
    retest = patch(
        'api.services.article_fetcher.comparison.retest_comparison',
        return_value=(comparison.run_id, [comparison]),
    )
    with retest as mocked_retest:
        anonymous = APIClient()
        ordinary_user = User.objects.create_user(username='ordinary-reader', password=VALID_PASSWORD)
        ordinary = APIClient()
        ordinary.force_login(ordinary_user)
        inactive_admin = User.objects.create_superuser(
            username='inactive-diagnostic-admin',
            email='inactive@example.test',
            password=VALID_PASSWORD,
        )
        inactive_admin.is_active = False
        inactive_admin.save(update_fields=['is_active'])
        inactive = APIClient()
        inactive.force_login(inactive_admin)

        paths = [
            '/api/provider-comparisons/',
            f'/api/provider-comparisons/{comparison.pk}/',
            f'/api/provider-comparisons/{comparison.pk}/retest/',
        ]
        for client in (anonymous, ordinary, inactive):
            for path in paths:
                response = client.post(path, {}, format='json') if path.endswith('/retest/') else client.get(path)
                assert response.status_code == 403
                assert 'private-provider-error-detail' not in response.content.decode()
                assert 'private-diagnostic-path' not in response.content.decode()

        admin = User.objects.create_superuser(
            username='active-diagnostic-admin',
            email='active@example.test',
            password=VALID_PASSWORD,
        )
        admin_client = APIClient()
        admin_client.force_login(admin)
        assert admin_client.get(paths[0]).status_code == 200
        assert admin_client.get(paths[1]).status_code == 200
        allowed_retest = admin_client.post(paths[2], {}, format='json')
        assert allowed_retest.status_code == 201
        mocked_retest.assert_called_once_with(comparison)


@pytest.mark.django_db
@override_settings(PUBLIC_SITE_MODE='read_only', PUBLIC_AI_ENABLED=True)
def test_read_only_policy_still_blocks_provider_diagnostics_for_active_superuser():
    admin = User.objects.create_superuser(
        username='readonly-admin', email='readonly@example.test', password=VALID_PASSWORD,
    )
    client = APIClient()
    client.force_login(admin)
    response = client.get('/api/provider-comparisons/')
    assert response.status_code == 403
    assert response.json()['error_code'] == 'public_read_only'

