import pytest
from rest_framework.test import APIRequestFactory

from api.rss.http import RssAPIView
from api.rss.operations import OperationError


@pytest.mark.parametrize('code', [
    'source_collection_not_permitted', 'full_content_policy_not_permitted',
    'unsupported_association_policy', 'full_content_disabled',
])
def test_collection_policy_refusals_are_safe_forbidden_responses(code):
    class RefusedView(RssAPIView):
        personal = False

        def get(self, request):
            raise OperationError(code)

    response = RefusedView.as_view()(APIRequestFactory().get('/api/rss/policy-test/'))
    assert response.status_code == 403
    assert response.data['error'] == {
        'code': code, 'message': '当前策略不允许此操作。', 'retryable': False,
    }
    assert response['Cache-Control'] == 'private, no-store'
