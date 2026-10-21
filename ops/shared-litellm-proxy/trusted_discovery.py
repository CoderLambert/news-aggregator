"""Protected catalog-only extension, registered by LiteLLM's native startup hook."""
import importlib.metadata

from fastapi import Depends, HTTPException, Request
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth

from trusted_chat import admit_request, execution_for, finish_request
from trusted_transport import EgressDenied, OneShotClient, strict_json

PATH = '/newshub/models/discover'


async def discover(request: Request, identity=Depends(user_api_key_auth)):
    data = None
    try:
        raw = await request.body()
        if len(raw) > 8192:
            raise EgressDenied()
        data = strict_json(raw)
        if type(data) is not dict or set(data) != {'model', 'api_key', 'metadata'}:
            raise EgressDenied()
        # Reuse the Proxy's key/model policy. The custom path must also be
        # explicitly granted in this project's allowed_routes.
        from litellm.proxy import proxy_server
        from litellm.proxy.auth.auth_checks import can_key_call_model
        await can_key_call_model(model=data['model'], llm_model_list=proxy_server.llm_model_list,
                                 valid_token=identity, llm_router=proxy_server.llm_router)
        data['messages'] = [{'role': 'user', 'content': 'catalog-only operation'}]
        admit_request(data)
        state = execution_for(data)
        state.client = OneShotClient(state.profile, provider_key=state.provider_key,
                                     model_id=state.model_id, check_current=state.check_current)
        return await state.client.get_models()
    except Exception:
        raise HTTPException(status_code=400, detail={'code': 'BYOK_MODEL_DISCOVERY_UNAVAILABLE'}) from None
    finally:
        if data is not None:
            await finish_request(data)


def register():
    if importlib.metadata.version('litellm') != '1.105.0':
        raise EgressDenied()
    from litellm.proxy.proxy_server import app
    for route in app.routes:
        if getattr(route, 'path', None) == PATH:
            if getattr(route, 'endpoint', None) is not discover:
                raise EgressDenied()
            return
    app.add_api_route(PATH, discover, methods=['POST'], include_in_schema=False)
