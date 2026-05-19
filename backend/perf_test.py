"""
Run: cd backend && python manage.py shell < perf_test.py
Profile all API endpoint response times.
"""
import time
from django.test import Client

client = Client()

def timed(url, label):
    t0 = time.time()
    resp = client.get(url)
    ms = (time.time() - t0) * 1000
    print(f'{label:25s} {ms:6.0f}ms  (HTTP {resp.status_code})')
    return ms

print('=== API Performance Test ===')
print()

# 1. Default list
timed('/api/news/?page_size=20', '1. 默认列表(无搜索)')

# 2. Keyword search
timed('/api/news/?search=Python&mode=keyword&page_size=20', '2. keyword搜索')

# 3. Semantic search (loads embedding model)
timed('/api/news/?search=Python&mode=semantic&page_size=20', '3. semantic搜索(首次加载模型)')

# 4. Hybrid search
timed('/api/news/?search=Python&mode=hybrid&page_size=20', '4. hybrid搜索')

# 5. Multi-select filter
timed('/api/news/?category=8,17&source=5,4&page_size=20', '5. 多选过滤')

# 6. Page 10
timed('/api/news/?page=10&page_size=20', '6. 第10页')

# 7. Categories list
timed('/api/categories/', '7. 分类列表')

# 8. Sources list
timed('/api/sources/', '8. 来源列表')

# --- second round: check warm cache ---
print()
print('=== 第二轮(模型已加载/缓存生效) ===')
print()

timed('/api/news/?page_size=20', '9. 默认列表(二次)')
timed('/api/news/?search=Python&mode=semantic&page_size=20', '10. semantic搜索(模型已加载)')
timed('/api/news/?search=Python&mode=hybrid&page_size=20', '11. hybrid搜索(模型已加载)')
