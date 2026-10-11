"""Small allowlist of provider endpoints exposed by the BYOK settings UI."""

PROVIDER_PROFILES = (
    {
        'provider_id': 'openai',
        'provider_name': 'OpenAI',
        'profile_id': 'openai_default',
        'region_name': '官方端点',
        'base_url': 'https://api.openai.com/v1',
        'version': 1,
    },
    {
        'provider_id': 'anthropic',
        'provider_name': 'Claude',
        'profile_id': 'anthropic_default',
        'region_name': '官方端点',
        'base_url': 'https://api.anthropic.com',
        'version': 1,
    },
    {
        'provider_id': 'deepseek',
        'provider_name': 'DeepSeek',
        'profile_id': 'deepseek_default',
        'region_name': '通用 API',
        'base_url': 'https://api.deepseek.com',
        'version': 1,
    },
    {
        'provider_id': 'glm',
        'provider_name': 'GLM',
        'profile_id': 'glm_cn',
        'region_name': '中国大陆',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4/',
        'version': 1,
    },
    {
        'provider_id': 'zai',
        'provider_name': 'Z.AI',
        'profile_id': 'zai_global',
        'region_name': '国际',
        'base_url': 'https://api.z.ai/api/paas/v4/',
        'version': 1,
    },
    {
        'provider_id': 'qwen',
        'provider_name': 'Qwen',
        'profile_id': 'qwen_beijing',
        'region_name': '北京',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'version': 1,
    },
    {
        'provider_id': 'qwen',
        'provider_name': 'Qwen',
        'profile_id': 'qwen_singapore',
        'region_name': '新加坡',
        'base_url': 'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
        'version': 1,
    },
    {
        'provider_id': 'kimi',
        'provider_name': 'Kimi',
        'profile_id': 'kimi_global',
        'region_name': '国际',
        'base_url': 'https://api.moonshot.ai/v1',
        'version': 1,
    },
)

PROFILES_BY_ID = {profile['profile_id']: profile for profile in PROVIDER_PROFILES}


def provider_catalog():
    """Return public endpoint metadata; no user-controlled URL is accepted."""
    return [dict(profile) for profile in PROVIDER_PROFILES]


def get_profile(provider_id, profile_id):
    profile = PROFILES_BY_ID.get(profile_id)
    if profile is None or profile['provider_id'] != provider_id:
        return None
    return profile
