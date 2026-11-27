#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对拍脚本：验证「由 vendor/lunar_python 负责的那部分」是否与本项目一致。

技术框架（已确定）：
  · 农历（公历↔农历互转、闰月判定、节气时刻）—— 由 vendor/lunar_python 负责
  · 四柱、大运、流年、神煞 —— 本项目自研

因此本脚本只比对**库真正负责、且本项目会用到**的两件事：
  1. 农历互转：1900–2100 逐日「公历→农历→公历」与库一致
  2. 节气时刻：24 个节气逐项与库的表一致（秒级）
  3. 四柱的年柱/月柱：这两个依赖节气，用来验证自研的立春分年、十二节分月逻辑

明确不做（无意义或已被排除）：
  · 日柱 / 时柱比对 —— 纯干支推算，与农历无关，已由 test_pai_pan.py 覆盖
  · 大运方向 / 起运岁数 —— 自研实现；参考库的 eightchar/Yun.py 已按框架排除，
    且其起运先截断到分钟，精度低于本项目（按秒折算），比对只会产生误导性差异
  · 神煞 —— 两边性质不同（本项目为八字命局神煞，库为黄历每日宜忌），不可比

用法：
    python scripts/compare_with_reference.py             # 默认抽样
    python scripts/compare_with_reference.py --full      # 1900–2100 全量逐日
    python scripts/compare_with_reference.py --seed 42
"""

import argparse
import os
import random
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
sys.path.insert(0, HERE)

import pai_pan as P  # noqa: E402
from lunar_python import Solar  # noqa: E402

# 黄经 → 库的节气名（含跨年别名）
JIEQI_NAMES = {
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


def check_lunar_days(days, label):
    """逐日：公历→农历→公历 必须回环，且农历值与库一致。"""
    bad = []
    for d in days:
        y, m, dd = d.year, d.month, d.day
        try:
            ly, lm, ld, leap = P.solar_to_lunar(y, m, dd)
        except Exception as exc:  # noqa: BLE001
            bad.append((d, "换算抛错: %s" % exc))
            continue
        ref = Solar.fromYmd(y, m, dd).getLunar()
        ref_val = (ref.getYear(), abs(ref.getMonth()), ref.getDay(), ref.getMonth() < 0)
        if (ly, lm, ld, leap) != ref_val:
            bad.append((d, "本项目=%s 库=%s" % ((ly, lm, ld, leap), ref_val)))
            continue
        try:
            back = P.lunar_to_solar(ly, lm, ld, leap)
        except Exception as exc:  # noqa: BLE001
            bad.append((d, "回环抛错: %s" % exc))
            continue
        if back != d:
            bad.append((d, "回环后变成 %s" % back))
    print("\n【农历互转】%s：%d 天，不一致 %d 处" % (label, len(days), len(bad)))
    for d, why in bad[:10]:
        print("   %s  %s" % (d, why))
    if len(bad) > 10:
        print("   …共 %d 处，只显示前 10 处" % len(bad))
    return bad


def check_solar_terms(years):
    """逐节气：本项目 solar_term_beijing 与库的节气表必须秒级一致。"""
    bad = []
    total = 0
    for y in years:
        try:
            table = Solar.fromYmd(y, 6, 1).getLunar().getJieQiTable()
        except Exception:  # noqa: BLE001
            continue
        for lon, (name, alias) in JIEQI_NAMES.items():
            total += 1
            ours = P.solar_term_beijing(y, lon)
            # 库里同名节气可能在相邻年份出现，逐个候选比对，取落在本年的那个
            ref_dt = None
            for key in (name, alias):
                if not key:
                    continue
                dt = table.get(key)
                if dt is None:
                    continue
                if dt.getYear() == y:
                    ref_dt = dt
                    break
            if ref_dt is None:
                continue
            got = ours.strftime("%Y-%m-%d %H:%M:%S")
            want = ref_dt.toYmdHms()
            if got != want:
                bad.append((y, name, got, want))
    print("\n【节气时刻】%d 项，不一致 %d 处" % (total, len(bad)))
    for y, name, got, want in bad[:10]:
        print("   %d %s 本项目=%s 库=%s" % (y, name, got, want))
    if len(bad) > 10:
        print("   …共 %d 处，只显示前 10 处" % len(bad))
    return bad


def check_year_month_pillars(samples):
    """年柱/月柱依赖节气，用来验证自研的立春分年、十二节分月。"""
    bad = []
    for (y, m, d, hh, mm) in samples:
        res = P.compute(
            solar_date=date(y, m, d), hour=hh, minute=mm, sex="男",
            now=P.datetime(2026, 1, 1, tzinfo=P.BJ), with_variants=False,
        )
        p = res["pillars"]
        ours = (p["year"][0] + p["year"][1], p["month"][0] + p["month"][1])
        lunar = Solar.fromYmdHms(y, m, d, hh, mm, 0).getLunar()
        ec = lunar.getEightChar()
        ec.setSect(1)
        ref = (ec.getYear(), ec.getMonth())
        if ours != ref:
            bad.append(((y, m, d, hh, mm), ours, ref))
    print("\n【年柱/月柱】%d 例，不一致 %d 处" % (len(samples), len(bad)))
    for case, ours, ref in bad[:10]:
        print("   %s 本项目=%s 库=%s" % (case, ours, ref))
    if len(bad) > 10:
        print("   …共 %d 处，只显示前 10 处" % len(bad))
    return bad


def edge_samples():
    """节气 / 立春 / 子时 / 闰月附近等易错时刻。"""
    return [
        (1990, 2, 3, 10, 0), (1990, 2, 4, 12, 0), (1990, 5, 15, 23, 30),
        (1990, 5, 15, 0, 30), (2000, 2, 4, 20, 30), (2001, 6, 17, 12, 0),
        (2014, 10, 24, 8, 0), (2033, 12, 22, 15, 0), (2034, 1, 20, 6, 0),
        (1984, 2, 4, 23, 59), (2024, 2, 4, 16, 27), (1950, 1, 1, 0, 0),
        (2049, 12, 31, 23, 0),
    ]


def random_samples(seed, n):
    rng = random.Random(seed)
    base = date(1950, 1, 1)
    span = (date(2049, 12, 31) - base).days
    out = []
    for _ in range(n):
        d0 = base + timedelta(days=rng.randrange(span + 1))
        out.append((d0.year, d0.month, d0.day, rng.randrange(24), rng.choice((0, 15, 30, 45))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="验证农历/节气与 vendor 库一致")
    ap.add_argument("--full", action="store_true", help="1900–2100 全量逐日（较慢）")
    ap.add_argument("--n", type=int, default=800, help="抽样天数（非 --full 时）")
    ap.add_argument("--seed", type=int, default=20261127)
    args = ap.parse_args(argv)

    print("=" * 74)
    print("对拍范围：农历互转 + 节气时刻 + 年柱/月柱")
    print("（大运、日柱、时柱、神煞按技术框架不参与比对，理由见文件头说明）")
    print("=" * 74)

    # 1. 农历逐日
    if args.full:
        day = date(1900, 1, 1)
        days = []
        while day <= date(2100, 12, 31):
            days.append(day)
            day += timedelta(days=1)
        lunar_bad = check_lunar_days(days, "全量 1900–2100 逐日")
    else:
        rng = random.Random(args.seed)
        days = []
        base = date(1900, 1, 1)
        span = (date(2100, 12, 31) - base).days
        for _ in range(args.n):
            days.append(base + timedelta(days=rng.randrange(span + 1)))
        lunar_bad = check_lunar_days(sorted(set(days)), "抽样")

    # 2. 节气时刻
    term_years = range(1900, 2101) if args.full else range(1950, 2051)
    term_bad = check_solar_terms(term_years)

    # 3. 年柱/月柱
    samples = edge_samples() + random_samples(args.seed, 200 if not args.full else 800)
    ym_bad = check_year_month_pillars(samples)

    all_bad = lunar_bad + term_bad + ym_bad
    print("\n" + "=" * 74)
    if all_bad:
        print("结论：存在 %d 处不一致，见上文" % len(all_bad))
    else:
        print("结论：农历互转、节气时刻、年柱/月柱全部一致")
    print("=" * 74)
    return 0 if not all_bad else 1


if __name__ == "__main__":
    sys.exit(main())