#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四柱八字排盘（零第三方依赖，仅标准库）。

时区一律按北京时间 UTC+8，不用本机本地时区。
节气用太阳视黄经定气（立春=315°），农历用定气定朔
（冬至所在月为十一月，无中气之月为闰月）。

算法锚点（供 QA 对照）
---------------------
1. 日柱：公历儒略日（JDN）→ 六十甲子。
   锚点：1990-05-15 = 庚辰（序号 16：庚=6，辰=4）。
   公式：gz_index = (JDN + 49) % 60。
   日界按早晚子时：23:00 前用当日日柱；23:00 起（含）用次日日柱。

2. 年柱：以该年立春的精确时刻分界，不是正月初一，也不是 2 月 4 日零点。
   年份干支：(year - 4) % 60（1984=甲子）；若时刻 < 该年立春，用 year-1。
   锚点：1990-02-03 10:00 年柱必须是己巳，不是庚午。

3. 月柱：以十二「节」（不是中气）时刻分界：
   立春寅、惊蛰卯、清明辰、立夏巳、芒种午、小暑未、
   立秋申、白露酉、寒露戌、立冬亥、大雪子、小寒丑。
   天干：年上起月。甲己丙作首、乙庚戊为头、丙辛庚上、丁壬壬寅、戊癸甲寅。
   锚点：1990-05-15（立夏后、芒种前）= 辛巳月。

4. 时柱：子 23:00-01:00，丑 01-03，寅 03-05，卯 05-07，辰 07-09，巳 09-11，
   午 11-13，未 13-15，申 15-17，酉 17-19，戌 19-21，亥 21-23。
   五鼠遁元：甲己甲子、乙庚丙子、丙辛戊子、丁壬庚子、戊癸壬子。
   锚点：庚日午时 = 壬午。

5. 十神 / 藏干：与 references/wuxing-tables.md 同一张表，以日干为基准。
   日干那一格十神为「—」。

6. 大运：年干甲丙戊庚壬为阳年；乙丁己辛癸为阴年。
   阳年男/阴年女顺排；阴年男/阳年女逆排。
   从月柱的下一柱（顺）或上一柱（逆）开始，不要把月柱本身当作第一步大运。
   起运年龄 = 出生日到最近「节」的天数 ÷ 3（顺数下一节，逆数上一节）。
   余 1 天 ≈ 4 个月，余 2 天 ≈ 8 个月。起运前用月柱作小运。
   锚点：1990-05-15 男（阳年）必须顺排。

7. 节气时刻：太阳视黄经（Meeus 简式，等价于寿星定气）。
   立春=黄经 315°。精确到小时以上，覆盖 1900–2100。禁止写死「立春大约 2 月 3-5 日」。

8. 农历：节气+朔望。冬至所在月为十一月，无中气之月为闰月。
   朔用 Meeus 定朔（TT），再换北京日期。
   非闰月锚点：1990 农历四月廿一 = 1990-05-15。

9. 神煞：与 references/shensha-table.md 同一张表。只输出命局命中的条目；
   时柱未知则不参与。

真太阳时：默认钟表时间。若给了 --place 且时刻距时辰整点边界 ≤15 分钟，
只加警告「校正后可能跨时辰」，不查经度、不做完整真太阳时。
"""

import argparse
import math
import os
import sys
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

# 节气时刻优先采用内嵌的 lunar-python（寿星天文历定气）。
# MIT License，见 vendor/lunar-python-LICENSE。
# 农历换算（公历↔农历互转、闰月判定）同样委托该库，不再自行推历。
_VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

from lunar_python import Lunar, Solar  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BJ = timezone(timedelta(hours=8))
J2000 = 2451545.0
UNIX_JD = 2440587.5  # 1970-01-01 00:00 UTC

GAN = "甲乙丙丁戊己庚辛壬癸"
ZHI = "子丑寅卯辰巳午未申酉戌亥"
GAN_WUXING = "木木火火土土金金水水"
ZHI_LIST = list(ZHI)
SHICHEN_SET = set(ZHI_LIST)

# 十二节：黄经、名称、月支下标（寅=2 … 丑=1）
JIE_DEFS = (
    (315, "立春", 2),
    (345, "惊蛰", 3),
    (15, "清明", 4),
    (45, "立夏", 5),
    (75, "芒种", 6),
    (105, "小暑", 7),
    (135, "立秋", 8),
    (165, "白露", 9),
    (195, "寒露", 10),
    (225, "立冬", 11),
    (255, "大雪", 0),
    (285, "小寒", 1),
)
JIE_LONGS = tuple(item[0] for item in JIE_DEFS)
ZHONGQI_LONGS = (0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330)

# 年上起月：寅月天干。甲己丙、乙庚戊、丙辛庚、丁壬壬、戊癸甲
YUE_GAN_YIN = {
    0: 2,
    5: 2,
    1: 4,
    6: 4,
    2: 6,
    7: 6,
    3: 8,
    8: 8,
    4: 0,
    9: 0,
}

# 五鼠遁元：日干 -> 子时天干
ZI_SHI_GAN = {
    0: 0,
    5: 0,
    1: 2,
    6: 2,
    2: 4,
    7: 4,
    3: 6,
    8: 6,
    4: 8,
    9: 8,
}

# 地支藏干：与 references/wuxing-tables.md 同一张表（本气、中气、余气）
CANGGAN = {
    "子": [("癸", "水")],
    "丑": [("己", "土"), ("癸", "水"), ("辛", "金")],
    "寅": [("甲", "木"), ("丙", "火"), ("戊", "土")],
    "卯": [("乙", "木")],
    "辰": [("戊", "土"), ("乙", "木"), ("癸", "水")],
    "巳": [("丙", "火"), ("庚", "金"), ("戊", "土")],
    "午": [("丁", "火"), ("己", "土")],
    "未": [("己", "土"), ("丁", "火"), ("乙", "木")],
    "申": [("庚", "金"), ("壬", "水"), ("戊", "土")],
    "酉": [("辛", "金")],
    "戌": [("戊", "土"), ("辛", "金"), ("丁", "火")],
    "亥": [("壬", "水"), ("甲", "木")],
}

# 十神：rel = (他干五行 - 日干五行) % 5
# 0 同我 / 1 我生 / 2 我克 / 3 克我 / 4 生我
SHISHEN_SAME = ("比肩", "食神", "偏财", "偏官", "偏印")
SHISHEN_DIFF = ("劫财", "伤官", "正财", "正官", "正印")

# 神煞：与 references/shensha-table.md 同一张表
TIANYI = {
    "甲": ("丑", "未"),
    "戊": ("丑", "未"),
    "乙": ("子", "申"),
    "己": ("子", "申"),
    "丙": ("亥", "酉"),
    "丁": ("亥", "酉"),
    "壬": ("卯", "巳"),
    "癸": ("卯", "巳"),
    "庚": ("丑", "未", "寅", "午"),
    "辛": ("寅", "午"),
}
# 天德：("gan", 干) 查天干；("zhi", 支) 查地支
TIANDE = {
    "寅": ("gan", "丁"),
    "卯": ("zhi", "申"),
    "辰": ("gan", "壬"),
    "巳": ("gan", "辛"),
    "午": ("zhi", "亥"),
    "未": ("gan", "甲"),
    "申": ("gan", "癸"),
    "酉": ("zhi", "寅"),
    "戌": ("gan", "丙"),
    "亥": ("gan", "乙"),
    "子": ("gan", "己"),
    "丑": ("gan", "庚"),
}
YUEDE = {
    "寅": "丙",
    "午": "丙",
    "戌": "丙",
    "申": "壬",
    "子": "壬",
    "辰": "壬",
    "亥": "甲",
    "卯": "甲",
    "未": "甲",
    "巳": "庚",
    "酉": "庚",
    "丑": "庚",
}
WENCHANG = {
    "甲": "巳",
    "乙": "午",
    "丙": "申",
    "丁": "酉",
    "戊": "申",
    "己": "酉",
    "庚": "亥",
    "辛": "子",
    "壬": "寅",
    "癸": "卯",
}
XUETANG = {
    "甲": "亥",
    "乙": "午",
    "丙": "寅",
    "丁": "酉",
    "戊": "寅",
    "己": "酉",
    "庚": "巳",
    "辛": "子",
    "壬": "申",
    "癸": "卯",
}
CIGUAN = {
    "甲": "寅",
    "乙": "卯",
    "丙": "巳",
    "丁": "午",
    "戊": "巳",
    "己": "午",
    "庚": "申",
    "辛": "酉",
    "壬": "亥",
    "癸": "子",
}
SANHE = {
    "寅": "火",
    "午": "火",
    "戌": "火",
    "申": "水",
    "子": "水",
    "辰": "水",
    "巳": "金",
    "酉": "金",
    "丑": "金",
    "亥": "木",
    "卯": "木",
    "未": "木",
}
JIANGXING = {"火": "午", "水": "子", "金": "酉", "木": "卯"}
HUAGAI = {"火": "戌", "水": "辰", "金": "丑", "木": "未"}
YIMA = {"火": "申", "水": "寅", "金": "亥", "木": "巳"}
JIESHA = {"水": "巳", "火": "亥", "金": "寅", "木": "申"}
ZAISHA = {"水": "午", "火": "子", "金": "卯", "木": "酉"}
WANGSHEN = {"水": "亥", "火": "巳", "金": "申", "木": "寅"}
TAOHUA = {"火": "卯", "水": "酉", "金": "午", "木": "子"}
GUCHEN = {
    "亥": "寅",
    "子": "寅",
    "丑": "寅",
    "寅": "巳",
    "卯": "巳",
    "辰": "巳",
    "巳": "申",
    "午": "申",
    "未": "申",
    "申": "亥",
    "酉": "亥",
    "戌": "亥",
}
GUASU = {
    "亥": "戌",
    "子": "戌",
    "丑": "戌",
    "寅": "丑",
    "卯": "丑",
    "辰": "丑",
    "巳": "辰",
    "午": "辰",
    "未": "辰",
    "申": "未",
    "酉": "未",
    "戌": "未",
}
JINYU = {
    "甲": "辰",
    "乙": "巳",
    "丙": "未",
    "丁": "申",
    "戊": "未",
    "己": "申",
    "庚": "戌",
    "辛": "亥",
    "壬": "丑",
    "癸": "寅",
}
YANGBLADE = {
    "甲": "卯",
    "乙": "寅",
    "丙": "午",
    "丁": "巳",
    "戊": "午",
    "己": "巳",
    "庚": "酉",
    "辛": "子",
    "壬": "子",
    "癸": "亥",
}
YUANCHEN_FORWARD = {
    "子": "未",
    "丑": "申",
    "寅": "酉",
    "卯": "戌",
    "辰": "亥",
    "巳": "子",
    "午": "丑",
    "未": "寅",
    "申": "卯",
    "酉": "辰",
    "戌": "巳",
    "亥": "午",
}
YUANCHEN_REVERSE = {
    "子": "巳",
    "丑": "午",
    "寅": "未",
    "卯": "申",
    "辰": "酉",
    "巳": "戌",
    "午": "亥",
    "未": "子",
    "申": "丑",
    "酉": "寅",
    "戌": "卯",
    "亥": "辰",
}
XUEREN = {
    "寅": "午",
    "卯": "未",
    "辰": "申",
    "巳": "酉",
    "午": "戌",
    "未": "亥",
    "申": "子",
    "酉": "丑",
    "戌": "寅",
    "亥": "卯",
    "子": "辰",
    "丑": "巳",
}
GAN_LABELS = ("年干", "月干", "日干", "时干")
ZHI_LABELS = ("年支", "月支", "日支", "时支")
MDH_ZHI_LABELS = ("月支", "日支", "时支")

# ---------------------------------------------------------------------------
# 神煞补充表（依据《三命通会》《渊海子平》通行口径，与 references/shensha-table.md 一致）
# ---------------------------------------------------------------------------

# 太极贵人：年干或日干查四柱地支
TAIJI = {
    "甲": ("子", "午"),
    "乙": ("子", "午"),
    "丙": ("卯", "酉"),
    "丁": ("卯", "酉"),
    "戊": ("辰", "戌", "丑", "未"),
    "己": ("辰", "戌", "丑", "未"),
    "庚": ("寅", "亥"),
    "辛": ("寅", "亥"),
    "壬": ("巳", "申"),
    "癸": ("巳", "申"),
}

# 国印贵人：年干或日干查四柱地支
GUOYIN = {
    "甲": "戌",
    "乙": "亥",
    "丙": "丑",
    "丁": "寅",
    "戊": "丑",
    "己": "寅",
    "庚": "辰",
    "辛": "巳",
    "壬": "未",
    "癸": "申",
}

# 天厨贵人：年干或日干查四柱地支
TIANCHU = {
    "甲": "巳",
    "乙": "午",
    "丙": "子",
    "丁": "巳",
    "戊": "午",
    "己": "申",
    "庚": "寅",
    "辛": "午",
    "壬": "酉",
    "癸": "亥",
}

# 福星贵人：年干或日干查四柱地支
FUXING = {
    "甲": ("寅", "子"),
    "乙": ("丑", "亥"),
    "丙": ("子",),
    "丁": ("酉",),
    "戊": ("申",),
    "己": ("未",),
    "庚": ("午",),
    "辛": ("巳",),
    "壬": ("辰",),
    "癸": ("卯", "丑"),
}

# 德秀贵人（月德 + 日干德）：以月支三合之德配合日干
DEXIU = {
    "寅": ("丙", "丁"),
    "午": ("丙", "丁"),
    "戌": ("丙", "丁"),
    "申": ("壬", "癸"),
    "子": ("壬", "癸"),
    "辰": ("壬", "癸"),
    "亥": ("甲", "乙"),
    "卯": ("甲", "乙"),
    "未": ("甲", "乙"),
    "巳": ("庚", "辛"),
    "酉": ("庚", "辛"),
    "丑": ("庚", "辛"),
}

# 天赦日：按「季节 + 日柱」双条件判定，两者同时成立才见。
#   春（寅卯辰月）逢戊寅日；夏（巳午未月）逢甲午日；
#   秋（申酉戌月）逢戊申日；冬（亥子丑月）逢甲子日。
# 注意：这四个干支日全年各出现约 6 次，但只有落在对应季节月份的才算天赦，
# 所以一年实际约 4–8 天，不是「每个月 4 个季节各一次」。
TIANSHE_SEASON = {
    "寅": "戊寅", "卯": "戊寅", "辰": "戊寅",
    "巳": "甲午", "午": "甲午", "未": "甲午",
    "申": "戊申", "酉": "戊申", "戌": "戊申",
    "亥": "甲子", "子": "甲子", "丑": "甲子",
}

# 魁罡：日柱为下列四组之一（《三命通会》）
KUIGANG = ("庚辰", "庚戌", "壬辰", "戊戌")

# 十恶大败：日柱为下列十组之一
# 口诀：甲辰乙巳与壬申，丙申丁亥及庚辰，戊戌癸亥加辛巳，己丑都来十位神
# 注意：庚辰、戊戌与魁罡重叠，古籍本来如此，二说并存，不是笔误。
SHIE_DAIBAI = (
    "甲辰", "乙巳", "丙申", "丁亥", "戊戌",
    "己丑", "庚辰", "辛巳", "壬申", "癸亥",
)

# 六秀日：日柱为下列六组之一
LIUXIU = ("丙午", "丁未", "戊子", "戊午", "己丑", "己未")

# 金神：日柱或时柱为下列三组之一
JINSHEN = ("乙丑", "己巳", "癸酉")

# 童子煞：按年支三合 + 季节查日柱或时柱地支
#   「春秋寅子贵，冬夏卯未辰；金木马卯合，水火鸡犬多，土命逢辰巳」
TONGZI_SEASON = {
    # 季节 -> 地支
    "spring": ("寅", "子"),
    "autumn": ("寅", "子"),
    "winter": ("卯", "未", "辰"),
    "summer": ("卯", "未", "辰"),
}
TONGZI_NAYIN = {
    # 年柱纳音五行 -> 地支
    "金": ("午", "卯"),
    "木": ("午", "卯"),
    "水": ("酉", "戌"),
    "火": ("酉", "戌"),
    "土": ("辰", "巳"),
}

# 纳音五行表（六十甲子），用于童子煞等
NAYIN = {
    "甲子": "金", "乙丑": "金", "丙寅": "火", "丁卯": "火", "戊辰": "木", "己巳": "木",
    "庚午": "土", "辛未": "土", "壬申": "金", "癸酉": "金", "甲戌": "火", "乙亥": "火",
    "丙子": "水", "丁丑": "水", "戊寅": "土", "己卯": "土", "庚辰": "金", "辛巳": "金",
    "壬午": "木", "癸未": "木", "甲申": "水", "乙酉": "水", "丙戌": "土", "丁亥": "土",
    "戊子": "火", "己丑": "火", "庚寅": "木", "辛卯": "木", "壬辰": "水", "癸巳": "水",
    "甲午": "金", "乙未": "金", "丙申": "火", "丁酉": "火", "戊戌": "木", "己亥": "木",
    "庚子": "土", "辛丑": "土", "壬寅": "金", "癸卯": "金", "甲辰": "火", "乙巳": "火",
    "丙午": "水", "丁未": "水", "戊申": "土", "己酉": "土", "庚戌": "金", "辛亥": "金",
    "壬子": "木", "癸丑": "木", "甲寅": "水", "乙卯": "水", "丙辰": "土", "丁巳": "土",
    "戊午": "火", "己未": "火", "庚申": "木", "辛酉": "木", "壬戌": "水", "癸亥": "水",
}

# 天罗地网：辰为天罗、戌为地网，男怕天罗（辰）、女怕地网（戌）
TIANLUO = "辰"
DIWANG = "戌"

# 天医的另一说法（月支前一位）已在原表；此处补「病符」= 月支前一位的上一支
# 十二天将（贵人、螣蛇、朱雀、六合、勾陈、青龙、天空、白虎、太常、玄武、太阴、天后）
# 按日干起贵人，本表只输出「天上贵人」相关，不作主论。
# 时辰中点（仅 shichen、无 clock 时用于节气比较与起运）
SHICHEN_MID = {
    "子": (0, 0),
    "丑": (2, 0),
    "寅": (4, 0),
    "卯": (6, 0),
    "辰": (8, 0),
    "巳": (10, 0),
    "午": (12, 0),
    "未": (14, 0),
    "申": (16, 0),
    "酉": (18, 0),
    "戌": (20, 0),
    "亥": (22, 0),
}

# 时辰整点边界（北京钟表，不含 00:00，因子时跨日在 23:00 / 01:00 换支）
SHICHEN_BOUNDARIES_MIN = (60, 180, 300, 420, 540, 660, 780, 900, 1020, 1140, 1260, 1380)

LUNAR_DAY_NAMES = {
    1: "初一",
    2: "初二",
    3: "初三",
    4: "初四",
    5: "初五",
    6: "初六",
    7: "初七",
    8: "初八",
    9: "初九",
    10: "初十",
    11: "十一",
    12: "十二",
    13: "十三",
    14: "十四",
    15: "十五",
    16: "十六",
    17: "十七",
    18: "十八",
    19: "十九",
    20: "二十",
    21: "廿一",
    22: "廿二",
    23: "廿三",
    24: "廿四",
    25: "廿五",
    26: "廿六",
    27: "廿七",
    28: "廿八",
    29: "廿九",
    30: "三十",
}
LUNAR_MONTH_NAMES = {
    1: "正月",
    2: "二月",
    3: "三月",
    4: "四月",
    5: "五月",
    6: "六月",
    7: "七月",
    8: "八月",
    9: "九月",
    10: "十月",
    11: "十一月",
    12: "十二月",
}


# ---------------------------------------------------------------------------
# 时间 / 儒略日（北京 UTC+8）
# ---------------------------------------------------------------------------

def delta_t_seconds(year):
    """TT−UTC 近似秒，Espenak/Meeus 分段多项式，1900–2100 足够到分钟级。"""
    y = float(year)
    t = y - 2000.0
    if y < 1920:
        t1 = y - 1900.0
        return -2.79 + 1.494119 * t1 - 0.0598939 * t1**2 + 0.0061966 * t1**3 - 0.000197 * t1**4
    if y < 1941:
        t1 = y - 1920.0
        return 21.20 + 0.84493 * t1 - 0.076100 * t1**2 + 0.0020936 * t1**3
    if y < 1961:
        t1 = y - 1950.0
        return 29.07 + 0.407 * t1 - t1**2 / 233.0 + t1**3 / 2547.0
    if y < 1986:
        t1 = y - 1975.0
        return 45.45 + 1.067 * t1 - t1**2 / 260.0 - t1**3 / 718.0
    if y < 2005:
        t1 = y - 2000.0
        return (
            63.86
            + 0.3345 * t1
            - 0.060374 * t1**2
            + 0.0017275 * t1**3
            + 0.000651814 * t1**4
            + 0.00002373599 * t1**5
        )
    if y < 2050:
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    return -20.0 + 32.0 * ((y - 1820.0) / 100.0) ** 2 - 0.5628 * (2150.0 - y)


def jd_from_datetime_utc(dt):
    """datetime（带时区）→ 儒略日（UTC）。"""
    utc = dt.astimezone(timezone.utc)
    unix = (utc - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
    return UNIX_JD + unix / 86400.0


def datetime_utc_from_jd(jd):
    seconds = (jd - UNIX_JD) * 86400.0
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def jd_tt_to_beijing(jd_tt):
    """力学时 JD → 北京时间 datetime。"""
    year = 2000.0 + (jd_tt - J2000) / 365.242189
    utc_jd = jd_tt - delta_t_seconds(year) / 86400.0
    return datetime_utc_from_jd(utc_jd).astimezone(BJ)


def beijing(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=BJ)


def jdn(year, month, day):
    """格里历儒略日数（中午，整数）。用于日柱。"""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


# ---------------------------------------------------------------------------
# 二十四节气
# ---------------------------------------------------------------------------
#
# 优先使用 vendor/lunar_python 的寿星天文历定气（精度到秒级）。
# 下方自研的 Meeus 简式仅作兜底：它约有 3–7 分钟误差，
# 出生时刻若落在节气前后几分钟内，会把年柱/月柱判到错的月建上
# （实测 2024 年立春：自研 16:20:11 vs 真实 16:27:07）。

# 黄经 → (参考库表里的本年名, 跨年别名)
# 参考库的节气表覆盖「前一年大雪 → 次年立春」共 31 项。
# 同一个名字在这张表里可能出现两次，跨年的那次用大写别名区分：
#   冬至 → DONG_ZHI（本年 12 月）、小寒 → XIAO_HAN、立春 → LI_CHUN 等。
_LON_TO_NAME = {
    315: ("立春", "LI_CHUN"),
    345: ("惊蛰", "JING_ZHE"),
    15: ("清明", None),
    45: ("立夏", None),
    75: ("芒种", None),
    105: ("小暑", None),
    135: ("立秋", None),
    165: ("白露", None),
    195: ("寒露", None),
    225: ("立冬", None),
    255: ("大雪", None),
    285: ("小寒", "XIAO_HAN"),
    270: ("冬至", "DONG_ZHI"),
    300: ("大寒", "DA_HAN"),
    330: ("雨水", "YU_SHUI"),
    0: ("春分", None),
    30: ("谷雨", None),
    60: ("小满", None),
    90: ("夏至", None),
    120: ("大暑", None),
    150: ("处暑", None),
    180: ("秋分", None),
    210: ("霜降", None),
    240: ("小雪", None),
}


def sun_apparent_longitude(jd_tt):
    """太阳视黄经（度）。Meeus AA 第 25 章简式，仅作兜底。"""
    T = (jd_tt - J2000) / 36525.0
    L0 = 280.46646 + 36000.76983 * T + 0.0003032 * T * T
    M = 357.52911 + 35999.05029 * T - 0.0001537 * T * T
    mr = math.radians(M)
    C = (
        (1.914602 - 0.004817 * T - 0.000014 * T * T) * math.sin(mr)
        + (0.019993 - 0.000101 * T) * math.sin(2.0 * mr)
        + 0.000289 * math.sin(3.0 * mr)
    )
    omega = 125.04 - 1934.136 * T
    lam = L0 + C - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    return lam % 360.0


def _lon_delta(actual, target):
    """actual − target，归一到 (−180, 180]。"""
    return (actual - target + 180.0) % 360.0 - 180.0


@lru_cache(maxsize=4096)
def _solar_term_jd_fallback(year, longitude):
    """兜底算法：二分法求太阳视黄经达到目标值的 TT 儒略日。"""
    year = int(year)
    longitude = float(longitude) % 360.0
    delta_lon = (longitude - 280.46646) % 360.0
    jd0 = J2000 + (year - 2000) * 365.242189 + delta_lon / 0.98564736
    lo, hi = jd0 - 8.0, jd0 + 8.0
    for _ in range(52):
        mid = (lo + hi) / 2.0
        if _lon_delta(sun_apparent_longitude(mid), longitude) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


@lru_cache(maxsize=8192)
def solar_term_beijing(year, longitude):
    """给定公历年、目标黄经，返回该年对应定气的北京时间 datetime。

    优先查参考库的节气表；查不到时回退到自研 Meeus 简式。
    """
    year = int(year)
    longitude = float(longitude) % 360.0
    names = _LON_TO_NAME.get(longitude)
    if names:
        try:
            # 以该年年中为锚点取出参考库的节气表（覆盖前一年大雪 → 次年立春）
            table = Solar.fromYmd(year, 6, 1).getLunar().getJieQiTable()
            candidates = []
            for key in names:
                if not key:
                    continue
                dt = table.get(key)
                if dt is not None:
                    candidates.append(
                        beijing(
                            dt.getYear(), dt.getMonth(), dt.getDay(),
                            dt.getHour(), dt.getMinute(), dt.getSecond(),
                        )
                    )
            # 取落在本公历年内的那一次（同名的另一次属相邻年份）
            for cand in candidates:
                if cand.year == year:
                    return cand
        except Exception:
            pass
    return jd_tt_to_beijing(_solar_term_jd_fallback(year, longitude))


def solar_term_jd(year, longitude):
    """返回该年对应定气的 TT 儒略日（兼容旧接口，内部走 solar_term_beijing）。"""
    return jd_from_datetime_utc(solar_term_beijing(year, longitude))


def jie_events_around(year):
    """year-1 … year+1 的十二节，按北京时间排序。每项 (dt, name, zhi_index, lon, year)。"""
    events = []
    for y in (year - 1, year, year + 1):
        for lon, name, zhi_i in JIE_DEFS:
            dt = solar_term_beijing(y, lon)
            events.append((dt, name, zhi_i, lon, y))
    events.sort(key=lambda x: x[0])
    return events


# ---------------------------------------------------------------------------
# 定朔（Meeus 第 49 章）
# ---------------------------------------------------------------------------

def new_moon_jde(k):
    """新月力学时 JDE。k=0 对应 2000-01-06 附近朔。精度约 1–2 分钟。"""
    T = k / 1236.85
    jde = (
        2451550.09766
        + 29.530588861 * k
        + 0.00015437 * T * T
        - 0.000000150 * T * T * T
        + 0.00000000073 * T * T * T * T
    )
    E = 1.0 - 0.002516 * T - 0.0000074 * T * T
    M = math.radians(2.5534 + 29.10535670 * k - 0.0000014 * T * T - 0.00000011 * T * T * T)
    Mp = math.radians(
        201.5643
        + 385.81693528 * k
        + 0.0107582 * T * T
        + 0.00001238 * T * T * T
        - 0.000000058 * T * T * T * T
    )
    F = math.radians(
        160.7108
        + 390.67050284 * k
        - 0.0016118 * T * T
        - 0.00000227 * T * T * T
        + 0.000000011 * T * T * T * T
    )
    omega = math.radians(124.7746 - 1.56375588 * k + 0.0020672 * T * T + 0.00000215 * T * T * T)
    args = (
        Mp,
        M,
        2 * Mp,
        2 * F,
        Mp - M,
        Mp + M,
        2 * M,
        Mp - 2 * F,
        Mp + 2 * F,
        2 * Mp + M,
        3 * Mp,
        M + 2 * F,
        M - 2 * F,
        2 * Mp - M,
        omega,
        Mp + 2 * M,
        2 * Mp - 2 * F,
        3 * M,
        Mp + M - 2 * F,
        2 * Mp + 2 * F,
        Mp + M + 2 * F,
        Mp - M + 2 * F,
        Mp - M - 2 * F,
        3 * Mp + M,
        4 * Mp,
    )
    coef = (
        -0.40720,
        0.17241 * E,
        0.01608,
        0.01039,
        0.00739 * E,
        -0.00514 * E,
        0.00208 * E * E,
        -0.00111,
        -0.00057,
        0.00056 * E,
        -0.00042,
        0.00042 * E,
        0.00038 * E,
        -0.00024 * E,
        -0.00017,
        -0.00007,
        0.00004,
        0.00004,
        0.00003,
        0.00003,
        -0.00003,
        0.00003,
        -0.00002,
        -0.00002,
        0.00002,
    )
    jde += sum(c * math.sin(a) for c, a in zip(coef, args))
    A = (
        299.77 + 0.107408 * k - 0.009173 * T * T,
        251.88 + 0.016321 * k,
        251.83 + 26.651886 * k,
        349.42 + 36.412478 * k,
        84.66 + 18.206239 * k,
        141.74 + 53.303771 * k,
        207.14 + 2.453732 * k,
        154.84 + 7.306860 * k,
        34.52 + 27.261239 * k,
        207.19 + 0.121824 * k,
        291.34 + 1.844379 * k,
        161.72 + 24.198154 * k,
        239.56 + 25.513099 * k,
        331.55 + 3.592518 * k,
    )
    Ac = (325, 165, 164, 126, 110, 62, 60, 56, 47, 42, 40, 37, 35, 23)
    jde += sum(c * 1e-6 * math.sin(math.radians(a)) for c, a in zip(Ac, A))
    return jde


def _k_near(jd):
    return int(round((jd - 2451550.09766) / 29.530588861))


def last_new_moon_k_on_or_before(jd_tt):
    k = _k_near(jd_tt)
    while new_moon_jde(k) > jd_tt:
        k -= 1
    while new_moon_jde(k + 1) <= jd_tt:
        k += 1
    return k


# ---------------------------------------------------------------------------
# 农历（委托 vendor/lunar_python 计算）
# ---------------------------------------------------------------------------
#
# 说明：本项目原先自研「定朔 + 无中气置闰 + 冬至十一月」的农历算法，
# 朔望与节气的天文计算本身是准确的，但闰月的定位与编号在多个年份与权威历法
# 不符（2001 年应为闰四月、2014 年闰九月、2033 年闰十一月）。
# 现统一委托 6tail/lunar-python（MIT License）计算农历，不再自行推历。
# 下列函数保留原有签名与返回结构，调用方无需改动。

def solar_to_lunar(y, m, d):
    """公历日 → (农历年, 月, 日, 是否闰月)。

    闰月的月份用正数返回，同时 leap=True（例：2001-06-17 → (2001, 4, 26, True)）。
    """
    solar = Solar.fromYmd(int(y), int(m), int(d))
    lunar = solar.getLunar()
    month = lunar.getMonth()
    return lunar.getYear(), abs(month), lunar.getDay(), month < 0


def lunar_to_solar(ly, lm, ld, leap=False):
    """农历日 → 公历 date。闰月必须 leap=True。"""
    ly, lm, ld = int(ly), int(lm), int(ld)
    month = -lm if leap else lm
    try:
        solar = Lunar.fromYmd(ly, month, ld).getSolar()
    except Exception:
        if leap:
            raise ValueError("农历 %d年没有闰%s" % (ly, LUNAR_MONTH_NAMES.get(lm, str(lm) + "月")))
        raise ValueError("找不到农历 %d年%s" % (ly, LUNAR_MONTH_NAMES.get(lm, str(lm) + "月")))
    # lunar-python 对不存在的日期会回绕，这里校验换算结果与输入一致
    back = solar.getLunar()
    if back.getYear() != ly or back.getMonth() != month or back.getDay() != ld:
        if leap:
            raise ValueError(
                "农历 %d年没有闰%s%s"
                % (ly, LUNAR_MONTH_NAMES.get(lm, str(lm) + "月"), LUNAR_DAY_NAMES.get(ld, str(ld)))
            )
        raise ValueError(
            "农历 %d年%s没有%s这一天"
            % (ly, LUNAR_MONTH_NAMES.get(lm, str(lm) + "月"), LUNAR_DAY_NAMES.get(ld, str(ld)))
        )
    return date(solar.getYear(), solar.getMonth(), solar.getDay())


def format_lunar(ly, lm, ld, leap):
    return "%d年%s%s%s" % (
        ly,
        "闰" if leap else "",
        LUNAR_MONTH_NAMES.get(lm, str(lm) + "月"),
        LUNAR_DAY_NAMES.get(ld, str(ld)),
    )


# ---------------------------------------------------------------------------
# 干支 / 十神 / 藏干
# ---------------------------------------------------------------------------

def gz_from_index(idx):
    idx = int(idx) % 60
    return GAN[idx % 10], ZHI[idx % 12]


def year_gz_index(year):
    """立春后的年干支序号。1984=甲子=0。"""
    return (int(year) - 4) % 60


def day_gz_index(year, month, day):
    """日柱序号。锚点 1990-05-15 = 16 庚辰。"""
    return (jdn(year, month, day) + 49) % 60


def shishen_of(day_gan, other_gan):
    if other_gan is None:
        return "—"
    rel = (other_gan // 2 - day_gan // 2) % 5
    if (day_gan % 2) == (other_gan % 2):
        return SHISHEN_SAME[rel]
    return SHISHEN_DIFF[rel]


def format_canggan(zhi):
    parts = CANGGAN.get(zhi, [])
    return "、".join("%s%s" % (g, wx) for g, wx in parts)


def _shensha_positions(needles, values, labels):
    if isinstance(needles, str):
        needles = (needles,)
    need = set(needles)
    out = []
    for val, lab in zip(values, labels):
        if val is not None and val in need:
            out.append(lab)
    return out


def _sanhe_needles(year_zhi, day_zhi, table):
    return {table[SANHE[year_zhi]], table[SANHE[day_zhi]]}


def kongwang_zhi(day_gan, day_zhi):
    """日柱所在旬的两个空亡地支。甲子旬戌亥，余旬依次前移。"""
    start = (ZHI.index(day_zhi) - GAN.index(day_gan)) % 12
    return ZHI[(start - 2) % 12], ZHI[(start - 1) % 12]


def compute_shensha(
    year_gan,
    year_zhi,
    month_gan,
    month_zhi,
    day_gan,
    day_zhi,
    hour_gan,
    hour_zhi,
    sex,
):
    """命中的神煞行。口径同 references/shensha-table.md；时柱未知则 hour_* 为 None。"""
    gans = (year_gan, month_gan, day_gan, hour_gan)
    zhis = (year_zhi, month_zhi, day_zhi, hour_zhi)
    mdh_zhis = (month_zhi, day_zhi, hour_zhi)
    lines = []

    def add(name, positions, method):
        if positions:
            lines.append("- %s — 见于%s — %s" % (name, "、".join(positions), method))

    tianyi_need = set(TIANYI[year_gan])
    tianyi_need.update(TIANYI[day_gan])
    add("天乙贵人", _shensha_positions(tianyi_need, zhis, ZHI_LABELS), "年干/日干查地支")

    td_kind, td_word = TIANDE[month_zhi]
    if td_kind == "gan":
        add("天德", _shensha_positions(td_word, gans, GAN_LABELS), "月支查天干")
    else:
        add("天德", _shensha_positions(td_word, zhis, ZHI_LABELS), "月支查地支")

    add("月德", _shensha_positions(YUEDE[month_zhi], gans, GAN_LABELS), "月支三合")

    wenchang_need = {WENCHANG[year_gan], WENCHANG[day_gan]}
    add("文昌", _shensha_positions(wenchang_need, zhis, ZHI_LABELS), "年干/日干查地支")
    add("学堂", _shensha_positions(XUETANG[day_gan], zhis, ZHI_LABELS), "日干长生")
    add("词馆", _shensha_positions(CIGUAN[day_gan], zhis, ZHI_LABELS), "日干临官")

    add(
        "将星",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, JIANGXING), zhis, ZHI_LABELS),
        "年支/日支三合",
    )
    add(
        "华盖",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, HUAGAI), zhis, ZHI_LABELS),
        "年支/日支",
    )
    add(
        "驿马",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, YIMA), zhis, ZHI_LABELS),
        "年支/日支",
    )

    tianyi_prev = ZHI[(ZHI.index(month_zhi) - 1) % 12]
    add("天医", _shensha_positions(tianyi_prev, zhis, ZHI_LABELS), "月支前一位")
    add("禄神", _shensha_positions(CIGUAN[day_gan], zhis, ZHI_LABELS), "日干")
    add("金舆", _shensha_positions(JINYU[day_gan], zhis, ZHI_LABELS), "日干")
    add("羊刃", _shensha_positions(YANGBLADE[day_gan], zhis, ZHI_LABELS), "日干")
    add(
        "劫煞",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, JIESHA), zhis, ZHI_LABELS),
        "年支/日支",
    )
    add(
        "灾煞",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, ZAISHA), zhis, ZHI_LABELS),
        "年支/日支",
    )
    add(
        "亡神",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, WANGSHEN), zhis, ZHI_LABELS),
        "年支/日支",
    )
    add(
        "桃花/咸池",
        _shensha_positions(_sanhe_needles(year_zhi, day_zhi, TAOHUA), zhis, ZHI_LABELS),
        "年支/日支",
    )
    add("孤辰", _shensha_positions(GUCHEN[year_zhi], zhis, ZHI_LABELS), "年支")
    add("寡宿", _shensha_positions(GUASU[year_zhi], zhis, ZHI_LABELS), "年支")
    add("空亡/旬空", _shensha_positions(kongwang_zhi(day_gan, day_zhi), zhis, ZHI_LABELS), "日柱旬空")

    yang_year = GAN.index(year_gan) % 2 == 0
    yuan_map = YUANCHEN_FORWARD if (yang_year == (sex == "男")) else YUANCHEN_REVERSE
    add("元辰", _shensha_positions(yuan_map[year_zhi], mdh_zhis, MDH_ZHI_LABELS), "年支阴阳男女")
    add("血刃", _shensha_positions(XUEREN[month_zhi], zhis, ZHI_LABELS), "月支")

    # ---------------- 补充条目（依据《三命通会》《渊海子平》通行口径）----------------

    # 太极贵人：年干或日干查四柱地支
    taiji_need = set(TAIJI[year_gan]) | set(TAIJI[day_gan])
    add("太极贵人", _shensha_positions(taiji_need, zhis, ZHI_LABELS), "年干/日干查地支")

    # 国印贵人：年干或日干查四柱地支
    guoyin_need = {GUOYIN[year_gan], GUOYIN[day_gan]}
    add("国印贵人", _shensha_positions(guoyin_need, zhis, ZHI_LABELS), "年干/日干查地支")

    # 天厨贵人：年干或日干查四柱地支
    tianchu_need = {TIANCHU[year_gan], TIANCHU[day_gan]}
    add("天厨贵人", _shensha_positions(tianchu_need, zhis, ZHI_LABELS), "年干/日干查地支")

    # 福星贵人：年干或日干查四柱地支
    fuxing_need = set(FUXING[year_gan]) | set(FUXING[day_gan])
    add("福星贵人", _shensha_positions(fuxing_need, zhis, ZHI_LABELS), "年干/日干查地支")

    # 德秀贵人：月支三合之德见于天干
    add("德秀贵人", _shensha_positions(DEXIU[month_zhi], gans, GAN_LABELS), "月支三合查天干")

    # 天赦日：季节 + 日柱，两项同时成立才见
    she = TIANSHE_SEASON.get(month_zhi)
    if she and (day_gan + day_zhi) == she:
        add("天赦", ["日柱"], "季节+日柱")

    # 魁罡：日柱四组之一
    day_gz = day_gan + day_zhi
    if day_gz in KUIGANG:
        add("魁罡", ["日柱"], "日柱")

    # 十恶大败：日柱十组之一
    if day_gz in SHIE_DAIBAI:
        add("十恶大败", ["日柱"], "日柱")

    # 六秀日：日柱六组之一
    if day_gz in LIUXIU:
        add("六秀日", ["日柱"], "日柱")

    # 金神：日柱或时柱
    jinshen_pos = []
    if day_gz in JINSHEN:
        jinshen_pos.append("日柱")
    if hour_gan is not None and (hour_gan + hour_zhi) in JINSHEN:
        jinshen_pos.append("时柱")
    add("金神", jinshen_pos, "日柱/时柱")

    # 童子煞：季节查日时支 + 年柱纳音查日时支
    season = {
        "寅": "spring", "卯": "spring", "辰": "spring",
        "巳": "summer", "午": "summer", "未": "summer",
        "申": "autumn", "酉": "autumn", "戌": "autumn",
        "亥": "winter", "子": "winter", "丑": "winter",
    }[month_zhi]
    tongzi_need = set(TONGZI_SEASON[season])
    year_gz = year_gan + year_zhi
    nayin_wx = NAYIN.get(year_gz)
    if nayin_wx:
        tongzi_need |= set(TONGZI_NAYIN[nayin_wx])
    # 只看日支与时支（童子煞以日时必须见）
    day_hour_zhis = (day_zhi, hour_zhi)
    day_hour_labels = ("日柱", "时柱")
    tongzi_hits = [lab for z, lab in zip(day_hour_zhis, day_hour_labels) if z is not None and z in tongzi_need]
    add("童子煞", tongzi_hits, "季节/年纳音查日时支")

    # 天罗地网：男忌辰、女忌戌
    luowang = TIANLUO if sex == "男" else DIWANG
    add("天罗地网", _shensha_positions(luowang, mdh_zhis, MDH_ZHI_LABELS), "男女查地支")

    return lines


def hour_to_shichen(hour, minute):
    """钟点 → 时支。23:00–01:00 子，其后每两小时一支。"""
    total = hour * 60 + minute
    if total >= 23 * 60 or total < 60:
        return "子"
    # 01:00 起：丑=1 … 亥=11
    idx = ((hour + 1) // 2) % 12
    return ZHI[idx]


def near_shichen_boundary(hour, minute):
    total = hour * 60 + minute
    for b in SHICHEN_BOUNDARIES_MIN:
        if abs(total - b) <= 15:
            return True
    return False


# ---------------------------------------------------------------------------
# 排盘
# ---------------------------------------------------------------------------

def resolve_year_pillar(birth_dt):
    """立春时刻分年。1990-02-03 10:00 → 己巳。"""
    cal_year = birth_dt.year
    lichun = solar_term_beijing(cal_year, 315)
    year_num = cal_year if birth_dt >= lichun else cal_year - 1
    gan, zhi = gz_from_index(year_gz_index(year_num))
    return year_num, gan, zhi, lichun


def resolve_month_pillar(birth_dt, year_gan):
    """十二节分月 + 年上起月。1990-05-15 → 辛巳。"""
    events = jie_events_around(birth_dt.year)
    current = None
    next_jie = None
    prev_jie = None
    for i, ev in enumerate(events):
        if ev[0] <= birth_dt:
            current = ev
        elif next_jie is None:
            next_jie = ev
            if i >= 1:
                prev_jie = events[i - 1]
            break
    if current is None:
        raise ValueError("找不到出生时刻之前的节气")
    if prev_jie is None:
        # birth 落在列表最后一节之后
        prev_jie = current
        # next 取更后面一年
        later = jie_events_around(birth_dt.year + 1)
        for ev in later:
            if ev[0] > birth_dt:
                next_jie = ev
                break
    _dt, name, zhi_i, lon, _y = current
    yue_zhi = ZHI[zhi_i]
    # 寅=2 对应年上起月的第 0 步
    step = (zhi_i - 2) % 12
    yue_gan = GAN[(YUE_GAN_YIN[year_gan] + step) % 10]
    return yue_gan, yue_zhi, name, lon, prev_jie[0], next_jie[0] if next_jie else None


def resolve_day_pillar(solar_date, hour, minute):
    """早晚子时日界。返回 (gan, zhi, index, used_date, zishi_label)。"""
    used = date(solar_date.year, solar_date.month, solar_date.day)
    zishi = "无"
    if hour is not None:
        if hour >= 23:
            used = used + timedelta(days=1)
            zishi = "夜子时"
        elif hour == 0:
            zishi = "早子时"
    idx = day_gz_index(used.year, used.month, used.day)
    gan, zhi = gz_from_index(idx)
    return gan, zhi, idx, used, zishi


def resolve_hour_pillar(day_gan, shichen):
    if not shichen:
        return None, None
    zhi_i = ZHI.index(shichen)
    gan_i = (ZI_SHI_GAN[day_gan] + zhi_i) % 10
    return GAN[gan_i], ZHI[zhi_i]


def qiyun_from_days(days):
    """起运折算：3 天 = 1 年，1 天 = 4 个月，余数不足 1 个月则舍去。

    单位换算：
        3 天（259200 秒） = 1 年
        1 天（86400 秒）   = 4 个月  → 1 个月 = 21600 秒 = 6 小时
    这里按**秒**换算再取整，保留完整精度；先截断到分钟会在临界点上
    少算一个月（例：410358 秒 vs 410400 秒，截断后都变成 6839 分钟）。
    返回 (岁, 月)，月为 0..11。
    """
    total_seconds = int(abs(float(days)) * 86400.0 + 0.5)
    months_total = total_seconds // 21600       # 21600 秒 = 6 小时 = 1 个月
    years, months = divmod(months_total, 12)
    return years, months


def build_dayun(month_gan, month_zhi, forward, qiyun_years, qiyun_months, steps=8):
    """从月柱下一柱（顺）或上一柱（逆）起排。月柱本身是起运前小运。"""
    gi = GAN.index(month_gan)
    zi = ZHI.index(month_zhi)
    delta = 1 if forward else -1
    rows = []
    start_age = qiyun_years
    if qiyun_years > 0 or qiyun_months > 0:
        if qiyun_months == 0:
            pre_end = "%d岁" % qiyun_years
        else:
            pre_end = "%d岁%d个月" % (qiyun_years, qiyun_months)
        rows.append(("起运前", "0岁-" + pre_end, month_gan + month_zhi + "（小运）"))
    for n in range(1, steps + 1):
        gi = (gi + delta) % 10
        zi = (zi + delta) % 12
        a0 = start_age + (n - 1) * 10
        a1 = a0 + 9
        rows.append((str(n), "%d-%d岁" % (a0, a1), GAN[gi] + ZHI[zi]))
    return rows


def liunian_gz(year):
    g, z = gz_from_index(year_gz_index(year))
    return g + z


def compute(
    solar_date,
    hour=None,
    minute=None,
    shichen=None,
    sex="男",
    place=None,
    deceased_year=None,
    lunar_display=None,
    now=None,
):
    """核心排盘。solar_date 为公历 date；hour/minute 为北京钟表，可空。"""
    warnings = []
    clock_known = hour is not None
    shichen_known = bool(shichen)

    if clock_known:
        shichen = hour_to_shichen(hour, minute)
    elif shichen_known:
        hour, minute = SHICHEN_MID[shichen]
    else:
        hour, minute = 12, 0
        warnings.append("时辰未知")

    birth_dt = beijing(solar_date.year, solar_date.month, solar_date.day, hour, minute)

    year_num, year_gan, year_zhi, lichun = resolve_year_pillar(birth_dt)
    month_gan, month_zhi, jie_name, jie_lon, prev_jie_dt, next_jie_dt = resolve_month_pillar(
        birth_dt, GAN.index(year_gan)
    )

    if clock_known:
        d_gan, d_zhi, d_idx, day_used, zishi = resolve_day_pillar(solar_date, hour, minute)
    elif shichen_known and shichen == "子":
        d_gan, d_zhi, d_idx, day_used, zishi = resolve_day_pillar(solar_date, 0, 0)
        warnings.append("未提供具体时刻，子时按早子时（当日日柱）处理")
    else:
        d_gan, d_zhi, d_idx, day_used, zishi = resolve_day_pillar(solar_date, None, None)

    if clock_known or shichen_known:
        h_gan, h_zhi = resolve_hour_pillar(GAN.index(d_gan), shichen)
        hour_unknown = False
    else:
        h_gan, h_zhi = None, None
        hour_unknown = True
        zishi = "无"

    day_gan_i = GAN.index(d_gan)
    pillars = {
        "year": (year_gan, year_zhi, shishen_of(day_gan_i, GAN.index(year_gan)), format_canggan(year_zhi)),
        "month": (month_gan, month_zhi, shishen_of(day_gan_i, GAN.index(month_gan)), format_canggan(month_zhi)),
        "day": (d_gan, d_zhi, "—", format_canggan(d_zhi)),
        "hour": (
            "未知" if hour_unknown else h_gan,
            "未知" if hour_unknown else h_zhi,
            "未知" if hour_unknown else shishen_of(day_gan_i, GAN.index(h_gan)),
            "未知" if hour_unknown else format_canggan(h_zhi),
        ),
    }

    year_gan_i = GAN.index(year_gan)
    yang_year = year_gan_i % 2 == 0
    if sex == "男":
        forward = yang_year
    else:
        forward = not yang_year
    # 1990-05-15 男（庚午阳年）必须顺排

    if forward:
        jie_for_qiyun = next_jie_dt
    else:
        jie_for_qiyun = prev_jie_dt
    if jie_for_qiyun is None:
        raise ValueError("无法定位起运所用的节")
    delta_sec = (jie_for_qiyun - birth_dt).total_seconds()
    qiyun_days = abs(delta_sec) / 86400.0
    qy, qm = qiyun_from_days(qiyun_days)
    dayun_rows = build_dayun(month_gan, month_zhi, forward, qy, qm)

    # 节气交界 / 立春前后：距节或立春 24 小时内
    if next_jie_dt is not None and abs((birth_dt - next_jie_dt).total_seconds()) <= 86400:
        warnings.append("节气交界")
    if abs((birth_dt - prev_jie_dt).total_seconds()) <= 86400:
        if "节气交界" not in warnings:
            warnings.append("节气交界")
    if abs((birth_dt - lichun).total_seconds()) <= 86400:
        warnings.append("立春前后")
    else:
        # 邻近上一年或下一年立春
        for y in (birth_dt.year - 1, birth_dt.year + 1):
            lc = solar_term_beijing(y, 315)
            if abs((birth_dt - lc).total_seconds()) <= 86400:
                warnings.append("立春前后")
                break

    if place and clock_known and near_shichen_boundary(hour, minute):
        warnings.append("校正后可能跨时辰")

    if now is None:
        now = datetime.now(BJ)
    current_year = now.year
    if deceased_year is not None:
        end_year = int(deceased_year)
        show_current_year = end_year
    else:
        end_year = current_year
        show_current_year = current_year
    birth_year = solar_date.year
    if end_year < birth_year:
        end_year = birth_year

    liunian_years = list(range(birth_year, end_year + 1))

    if lunar_display is None:
        try:
            ly, lm, ld, leap = solar_to_lunar(solar_date.year, solar_date.month, solar_date.day)
            lunar_display = format_lunar(ly, lm, ld, leap)
        except ValueError as exc:
            lunar_display = "未知"
            warnings.append(str(exc))

    if clock_known:
        solar_text = "%04d-%02d-%02d %02d:%02d" % (
            solar_date.year,
            solar_date.month,
            solar_date.day,
            hour,
            minute,
        )
        shichen_text = "%s / %02d:%02d" % (shichen, hour, minute)
    elif shichen_known:
        solar_text = "%04d-%02d-%02d" % (solar_date.year, solar_date.month, solar_date.day)
        shichen_text = shichen
    else:
        solar_text = "%04d-%02d-%02d" % (solar_date.year, solar_date.month, solar_date.day)
        shichen_text = "未知"

    if qm:
        qiyun_text = "%d岁%d个月" % (qy, qm)
    else:
        qiyun_text = "%d岁" % qy

    shensha_lines = compute_shensha(
        year_gan,
        year_zhi,
        month_gan,
        month_zhi,
        d_gan,
        d_zhi,
        h_gan,
        h_zhi,
        sex,
    )

    return {
        "solar_text": solar_text,
        "lunar_text": lunar_display,
        "shichen_text": shichen_text,
        "sex": sex,
        "place": place,
        "zishi": zishi,
        "pillars": pillars,
        "forward": forward,
        "qiyun_text": qiyun_text,
        "qiyun_years": qy,
        "qiyun_months": qm,
        "dayun_rows": dayun_rows,
        "liunian_years": liunian_years,
        "current_year": show_current_year,
        "current_gz": liunian_gz(show_current_year),
        "warnings": warnings,
        "hour_unknown": hour_unknown,
        "year_num": year_num,
        "jie_name": jie_name,
        "birth_dt": birth_dt,
        "shensha_lines": shensha_lines,
    }


def format_report(result):
    p = result["pillars"]
    lines = []
    lines.append("## 输入")
    lines.append("- 阳历：%s" % result["solar_text"])
    lines.append("- 农历：%s" % result["lunar_text"])
    lines.append("- 时辰：%s" % result["shichen_text"])
    lines.append("- 性别：%s" % result["sex"])
    if result["place"]:
        lines.append("- 出生地：%s" % result["place"])
    lines.append("- 子时：%s" % result["zishi"])
    lines.append("")
    lines.append("## 四柱")
    lines.append("| | 年柱 | 月柱 | 日柱 | 时柱 |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        "| 天干 | %s | %s | %s | %s |" % (p["year"][0], p["month"][0], p["day"][0], p["hour"][0])
    )
    lines.append(
        "| 地支 | %s | %s | %s | %s |" % (p["year"][1], p["month"][1], p["day"][1], p["hour"][1])
    )
    lines.append(
        "| 十神 | %s | %s | %s | %s |" % (p["year"][2], p["month"][2], p["day"][2], p["hour"][2])
    )
    lines.append(
        "| 藏干 | %s | %s | %s | %s |" % (p["year"][3], p["month"][3], p["day"][3], p["hour"][3])
    )
    lines.append("")
    lines.append("## 大运")
    lines.append("- 方向：%s" % ("顺排" if result["forward"] else "逆排"))
    lines.append("- 起运：%s" % result["qiyun_text"])
    lines.append("| 大运序 | 年龄范围 | 干支 |")
    lines.append("|---|---|---|")
    for seq, ages, gz in result["dayun_rows"]:
        lines.append("| %s | %s | %s |" % (seq, ages, gz))
    lines.append("")
    lines.append("## 流年")
    lines.append("- 当前：%d年%s" % (result["current_year"], result["current_gz"]))
    for y in result["liunian_years"]:
        lines.append("- %d年%s" % (y, liunian_gz(y)))
    lines.append("")
    lines.append("## 神煞")
    lines.extend(result["shensha_lines"])
    lines.append("")
    lines.append("## 警告")
    if result["warnings"]:
        # 去重且保持顺序
        seen = set()
        for w in result["warnings"]:
            if w in seen:
                continue
            seen.add(w)
            lines.append("- %s" % w)
    else:
        lines.append("- 无")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_iso_date(text, flag):
    try:
        parts = text.split("-")
        if len(parts) != 3:
            raise ValueError
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return date(y, m, d)
    except ValueError:
        raise argparse.ArgumentTypeError("%s 需要 YYYY-MM-DD，收到 %r" % (flag, text))


def parse_hour(text):
    try:
        hh, mm = text.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h, m
    except ValueError:
        raise argparse.ArgumentTypeError("--hour 需要 HH:MM，收到 %r" % text)


def build_parser():
    p = argparse.ArgumentParser(description="四柱八字排盘（北京时间，无第三方依赖）")
    p.add_argument("--solar", help="阳历 YYYY-MM-DD")
    p.add_argument("--lunar", help="农历 YYYY-MM-DD（年-月-日数字）")
    p.add_argument("--leap", action="store_true", help="农历闰月")
    p.add_argument("--hour", help="出生钟点 HH:MM（北京时间），与 --shichen 互斥")
    p.add_argument("--shichen", choices=ZHI_LIST, help="时辰地支")
    p.add_argument("--sex", required=True, choices=("男", "女"), help="性别（必填）")
    p.add_argument("--place", help="出生地（只展示；近时辰边界时警告）")
    p.add_argument("--deceased-year", type=int, dest="deceased_year", help="已故年份，流年只列到该年")
    return p


def run(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.solar and not args.lunar:
        parser.error("至少提供 --solar 或 --lunar")
    if args.hour and args.shichen:
        parser.error("--hour 与 --shichen 互斥")
    if args.leap and not args.lunar:
        parser.error("--leap 只能与 --lunar 同时使用")

    hour = minute = None
    if args.hour:
        hour, minute = parse_hour(args.hour)

    solar_date = None
    lunar_display = None
    if args.solar:
        solar_date = parse_iso_date(args.solar, "--solar")
    if args.lunar:
        lunar_date = parse_iso_date(args.lunar, "--lunar")
        try:
            converted = lunar_to_solar(lunar_date.year, lunar_date.month, lunar_date.day, leap=args.leap)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        lunar_display = format_lunar(lunar_date.year, lunar_date.month, lunar_date.day, args.leap)
        if solar_date is None:
            solar_date = converted
        # 两个都给：以阳历为准，农历仅展示（用用户给的农历字串）

    try:
        result = compute(
            solar_date=solar_date,
            hour=hour,
            minute=minute,
            shichen=args.shichen,
            sex=args.sex,
            place=args.place,
            deceased_year=args.deceased_year,
            lunar_display=lunar_display if args.lunar and args.solar else None,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    # 仅农历输入时，展示用户农历；同时用换算出的阳历
    if args.lunar and not args.solar:
        result["lunar_text"] = lunar_display

    report = format_report(result)
    sys.stdout.write(report)
    if not report.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
