"""Reviewed official feeds, keyed independently even when publishers overlap."""
ENERGY_FEEDS = (
    ('pv_magazine_china', 'PV Magazine 中文版', 'https://www.pv-magazine-china.com/feed/', '光伏、储能', 'domestic', 'zh'),
    ('ithome_energy', 'IT之家', 'https://www.ithome.com/rss/', '新能源相关科技资讯', 'domestic', 'zh'),
    ('electrek', 'Electrek', 'https://electrek.co/feed/', '电动车、储能、光伏', 'international', 'en'),
    ('insideevs', 'InsideEVs', 'https://insideevs.com/rss/news/all/', '电动车', 'international', 'en'),
    ('energy_storage_news', 'Energy-Storage.news', 'https://www.energy-storage.news/feed/', '储能；部分文章付费，仅收录 RSS 摘要', 'international', 'en'),
    ('pv_magazine_global', 'PV Magazine 国际版', 'https://www.pv-magazine.com/feed/', '光伏', 'international', 'en'),
    ('canary_media', 'Canary Media', 'https://www.canarymedia.com/rss.rss', '清洁能源、电网', 'international', 'en'),
    ('electrive', 'Electrive', 'https://www.electrive.com/feed/', '电动车、电池、产业', 'international', 'en'),
    ('verge_transportation', 'The Verge 交通', 'https://www.theverge.com/rss/transportation/index.xml', '电动车、出行科技', 'international', 'en'),
    ('utility_dive', 'Utility Dive', 'https://www.utilitydive.com/feeds/news/', '电网、电力政策', 'international', 'en'),
    ('windpower_monthly', 'Windpower Monthly', 'https://www.windpowermonthly.com/rss/news', '风电；正文付费，仅收录 RSS 标题和摘要', 'international', 'en'),
    ('ifanr_energy', '爱范儿', 'https://www.ifanr.com/feed', '新能源相关科技资讯', 'domestic', 'zh'),
)
MEDICAL_FEEDS = (
    ('stat_news', 'STAT News', 'https://www.statnews.com/feed/', '生物医药、健康政策、医疗科技'),
    ('medtech_dive', 'MedTech Dive', 'https://www.medtechdive.com/feeds/news/', '医疗器械'),
    ('biopharma_dive', 'BioPharma Dive', 'https://www.biopharmadive.com/feeds/news/', '医药研发、交易'),
    ('fda_news', 'FDA 新闻稿', 'https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml', '药品和器械审批、监管；RSS 待验证'),
    ('medcity_news', 'MedCity News', 'https://medcitynews.com/feed/', '健康科技、生物技术'),
    ('fierce_healthcare', 'Fierce Healthcare', 'https://www.fiercehealthcare.com/rss/xml', '医疗行业、数字健康'),
    ('nih_news', 'NIH 新闻稿', 'https://www.nih.gov/news-releases/feed.xml', '官方科研新闻'),
    ('mit_biotechnology', 'MIT 科技评论·生物技术', 'https://www.technologyreview.com/topic/biotechnology/feed', '生物技术、科技与医疗交叉'),
    ('ars_health', 'Ars Technica 健康', 'https://arstechnica.com/health/feed/', '健康和医学科技报道'),
    ('nature_medicine', 'Nature Medicine', 'https://www.nature.com/nm.rss', '医学期刊；仅收录标题和摘要'),
    ('nejm', 'NEJM', 'https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss', '医学期刊；仅收录标题和摘要'),
    ('lancet', 'The Lancet', 'https://www.thelancet.com/rssfeed/lancet_current.xml', '医学期刊；仅收录标题和摘要'),
    ('bbc_health', 'BBC Health', 'https://feeds.bbci.co.uk/news/health/rss.xml', '大众健康资讯'),
    ('sciencedaily_health', 'ScienceDaily 健康', 'https://www.sciencedaily.com/rss/health_medicine.xml', '大众健康、科研进展'),
)
SECTOR_KEYS = frozenset(row[0] for row in (*ENERGY_FEEDS, *MEDICAL_FEEDS))


def sector_policies(policy_class):
    from urllib.parse import urlsplit
    for key, name, url, description, region, language in ENERGY_FEEDS:
        host = urlsplit(url).hostname
        restricted = key in {'energy_storage_news', 'windpower_monthly'}
        yield policy_class(key, name, (host, host.removeprefix('www.')), url,
            region=region, language=language, description=description, default_category='新能源',
            html_allowed=False, reading_policy='rss_summary_only' if restricted else 'public_rss',
            keyword_filter='new_energy' if key in {'ithome_energy', 'ifanr_energy'} else '')
    for key, name, url, description in MEDICAL_FEEDS:
        host = urlsplit(url).hostname
        domains = ('www.bbc.com', 'www.bbc.co.uk', 'bbc.com', 'bbc.co.uk') if key == 'bbc_health' else (host, host.removeprefix('www.'))
        government = key in {'fda_news', 'nih_news'}
        yield policy_class(key, name, domains, url, region='international', language='en',
            description=description, default_category='医疗健康', html_allowed=False,
            reading_policy='public_rss' if government else 'rss_summary_only',
            unsupported_reason='feed_verification_pending' if key == 'fda_news' else '',
            content_kind='abstract' if key in {'nature_medicine', 'nejm', 'lancet'} else 'article',
            date_format={'fierce_healthcare': '%b %d, %Y %I:%M%p', 'nih_news': '%a, %m/%d/%Y - %H:%M'}.get(key, ''),
            date_timezone='America/New_York' if key in {'fierce_healthcare', 'nih_news'} else '')
