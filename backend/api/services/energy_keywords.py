"""Conservative admission for the two general-purpose Chinese feeds."""
import re

CHINESE_TERMS = ('新能源', '电动车', '电动汽车', '纯电', '插混', '插电混动', '增程', '充电桩', '超充',
    '换电', '动力电池', '储能', '光伏', '太阳能', '风电', '风力发电', '氢能', '绿氢', '燃料电池',
    '电网', '特斯拉', '比亚迪', '蔚来', '小鹏', '理想汽车', '极氪', '小米SU7', '小米 SU7', '小米YU7', '小米 YU7')
ENGLISH = re.compile(r'\b(?:EVs?|electric vehicles?|electric cars?|plug-in hybrid|charging stations?|'
    r'energy storage|grid storage|solar|photovoltaic|wind power|hydrogen|fuel cells?|'
    r'Tesla|BYD|NIO|XPeng|Zeekr)\b', re.I)


def matches_new_energy(title, summary='', tags=()):
    text = ' '.join((title, summary, *[str(t.get('term', '')) if isinstance(t, dict) else str(t) for t in tags]))
    return any(term in text for term in CHINESE_TERMS) or bool(ENGLISH.search(text))
