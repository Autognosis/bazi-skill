#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pai_pan.py 回归：用 stdout 断言黄金用例与日界/大运/农历/流年。"""

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "pai_pan.py")
# 子进程解释器：默认用当前解释器；可用 PAIPAN_PYTHON 覆盖。
# 覆盖选项用于解释器路径异常的环境（例如某些 Windows 安装中 python 命令
# 指向 0 字节的应用商店转发器，直接执行会返回 9009）。
PY = os.environ.get("PAIPAN_PYTHON") or sys.executable


def run_pai(*args):
    # 强制父子进程统一使用 UTF-8 交互。
    # Linux / macOS 默认即 UTF-8，此处为显式确认；
    # Windows 控制台默认使用本地代码页（简中为 cp936），若不统一，子进程输出
    # 一旦含非 ASCII 字符就会解码失败，导致 stdout 变成 None 而误报。
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [PY, SCRIPT] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def section(stdout, title):
    """截取 '## title' 到下一个 '##'（不含）。"""
    marker = "## " + title
    start = stdout.find(marker)
    if start < 0:
        return ""
    rest = stdout[start + len(marker) :]
    nxt = rest.find("\n## ")
    if nxt < 0:
        return rest
    return rest[:nxt]


def table_row(stdout, cell0):
    for line in stdout.splitlines():
        if line.startswith("| " + cell0 + " |"):
            return [p.strip() for p in line.strip().strip("|").split("|")]
    return []


def pillars(stdout):
    gan = table_row(stdout, "天干")
    zhi = table_row(stdout, "地支")
    # gan/zhi: ['天干', 年, 月, 日, 时]
    return {
        "year": (gan[1] if gan else "") + (zhi[1] if zhi else ""),
        "month": (gan[2] if gan else "") + (zhi[2] if zhi else ""),
        "day": (gan[3] if gan else "") + (zhi[3] if zhi else ""),
        "hour": (gan[4] if gan else "") + (zhi[4] if zhi else ""),
        "gan": gan[1:] if gan else [],
        "zhi": zhi[1:] if zhi else [],
    }


def field(stdout, name):
    m = re.search(r"^- %s：(.+)$" % re.escape(name), stdout, re.MULTILINE)
    return m.group(1).strip() if m else ""


def boundary_block(stdout):
    """边界情况段落（该段落标题较长，单独取）。"""
    return section(stdout, "边界情况（出生时刻落在临界点附近）")


def _is_leap_month_start(pai_pan, year, month):
    """该农历年是否存在「闰 month 月初一」，且换算回来仍是闰月初一。"""
    try:
        day = pai_pan.lunar_to_solar(year, month, 1, leap=True)
    except ValueError:
        return False
    return pai_pan.solar_to_lunar(day.year, day.month, day.day) == (year, month, 1, True)


class PaiPanTests(unittest.TestCase):
    def test_golden_1990_wushi_male(self):
        """1990-05-15 午时男：庚午 / 辛巳 / 庚辰 / 壬午，顺排，神煞已计算。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--shichen", "午", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["year"], "庚午")
        self.assertEqual(p["month"], "辛巳")
        self.assertEqual(p["day"], "庚辰")
        self.assertEqual(p["hour"], "壬午")
        self.assertIn("方向：顺排", out)
        shensha = section(out, "神煞").strip()
        self.assertNotEqual(shensha, "未计算")
        self.assertTrue(shensha)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("Traceback", err)

    def test_before_lichun_year_is_jisi(self):
        """1990-02-03 10:00 在立春前，年柱己巳，不是庚午。"""
        code, out, err = run_pai(
            "--solar", "1990-02-03", "--hour", "10:00", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["year"], "己巳")
        self.assertNotEqual(p["year"], "庚午")

    def test_late_zi_uses_next_day_pillar(self):
        """23:30 夜子时：日柱用次日辛巳，时支子。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "23:30", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["day"], "辛巳")
        self.assertEqual(p["zhi"][3], "子")
        self.assertEqual(field(out, "子时"), "夜子时")

    def test_early_zi_keeps_same_day_pillar(self):
        """00:30 早子时：日柱仍庚辰，时支子。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "00:30", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["day"], "庚辰")
        self.assertEqual(p["zhi"][3], "子")
        self.assertEqual(field(out, "子时"), "早子时")

    def test_dayun_direction_table(self):
        """大运方向真值表：阳年男顺、阴年男逆、阳年女逆、阴年女顺。"""
        cases = (
            ("阳年男顺排", "1990-05-15", "男", "庚午", "顺排"),
            ("阴年男逆排", "1991-06-15", "男", "辛未", "逆排"),
            ("阳年女逆排", "1990-05-15", "女", "庚午", "逆排"),
            ("阴年女顺排", "1991-06-15", "女", "辛未", "顺排"),
        )
        for name, day, sex, year_gz, direction in cases:
            with self.subTest(name):
                code, out, err = run_pai(
                    "--solar", day, "--shichen", "午", "--sex", sex
                )
                self.assertEqual(code, 0, err)
                self.assertEqual(pillars(out)["year"], year_gz)
                self.assertIn("方向：%s" % direction, out)

    def test_unknown_hour_keeps_ymd(self):
        """无 hour/shichen：时柱未知，年月日柱完整。"""
        code, out, err = run_pai("--solar", "1990-05-15", "--sex", "男")
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["year"], "庚午")
        self.assertEqual(p["month"], "辛巳")
        self.assertEqual(p["day"], "庚辰")
        self.assertEqual(p["gan"][3], "未知")
        self.assertEqual(p["zhi"][3], "未知")
        self.assertEqual(field(out, "时辰"), "未知")
        self.assertEqual(field(out, "子时"), "无")
        self.assertIn("时辰未知", section(out, "警告"))

    def test_lunar_non_leap_matches_solar(self):
        """农历 1990-04-21（非闰四月廿一）与阳历 1990-05-15 四柱一致。"""
        code_l, out_l, err_l = run_pai(
            "--lunar", "1990-04-21", "--shichen", "午", "--sex", "男"
        )
        code_s, out_s, err_s = run_pai(
            "--solar", "1990-05-15", "--shichen", "午", "--sex", "男"
        )
        self.assertEqual(code_l, 0, err_l)
        self.assertEqual(code_s, 0, err_s)
        self.assertEqual(pillars(out_l), pillars(out_s))

    def test_deceased_year_stops_liunian(self):
        """--deceased-year 2010：流年不出现 2011 及更晚。"""
        code, out, err = run_pai(
            "--solar",
            "1990-05-15",
            "--hour",
            "12:00",
            "--sex",
            "男",
            "--deceased-year",
            "2010",
        )
        self.assertEqual(code, 0, err)
        liunian = section(out, "流年")
        self.assertIn("2010", liunian)
        self.assertNotIn("2011", liunian)
        self.assertNotIn("2012", liunian)
        self.assertNotIn("2020", liunian)
        self.assertNotIn("2026", liunian)


class LeapMonthTests(unittest.TestCase):
    """置闰回归：闰月错位曾让闰月之后的所有日期提前一个月号。"""

    def test_2001_leap_fourth_month(self):
        """2001-06-17 = 农历 2001 年闰四月廿六（曾错算成五月廿六）。"""
        code, out, err = run_pai("--solar", "2001-06-17", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "农历"), "2001年闰四月廿六")

    def test_2001_leap_fourth_reverse(self):
        """农历 2001-04-26 --leap 回到公历 2001-06-17，且非闰四月是 2001-05-18。"""
        code, out, err = run_pai("--lunar", "2001-04-26", "--leap", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "阳历"), "2001-06-17")
        code2, out2, err2 = run_pai("--lunar", "2001-04-26", "--sex", "男")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(field(out2, "阳历"), "2001-05-18")

    def test_2001_month_after_leap_is_five(self):
        """闰四月之后依次是五月初一、六月初一，月号不得跳号。"""
        code, out, err = run_pai("--solar", "2001-06-21", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "农历"), "2001年五月初一")
        code2, out2, err2 = run_pai("--solar", "2001-07-21", "--sex", "男")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(field(out2, "农历"), "2001年六月初一")

    def test_2004_leap_second_month(self):
        """2004 年闰二月：2004-03-21 = 闰二月初一，2004-04-19 = 三月初一。"""
        code, out, err = run_pai("--solar", "2004-03-21", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "农历"), "2004年闰二月初一")
        code2, out2, err2 = run_pai("--solar", "2004-04-19", "--sex", "男")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(field(out2, "农历"), "2004年三月初一")

    def test_2014_leap_ninth_month(self):
        """2014 年闰九月：2014-10-24 = 闰九月初一，2014-11-22 = 十月初一。"""
        code, out, err = run_pai("--solar", "2014-10-24", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "农历"), "2014年闰九月初一")
        code2, out2, err2 = run_pai("--solar", "2014-11-22", "--sex", "男")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(field(out2, "农历"), "2014年十月初一")

    def test_2033_leap_eleventh_month(self):
        """2033 年闰十一月。

        真实历法：2033-11-22 十一月初一、2033-12-22 闰十一月初一、
        2034-01-20 十二月初一、2034-02-19 次年正月初一。
        """
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertEqual(pai_pan.solar_to_lunar(2033, 12, 22), (2033, 11, 1, True))
        self.assertEqual(
            pai_pan.lunar_to_solar(2033, 11, 1, leap=True), pai_pan.date(2033, 12, 22)
        )
        self.assertEqual(pai_pan.lunar_to_solar(2033, 12, 1), pai_pan.date(2034, 1, 20))
        self.assertEqual(pai_pan.lunar_to_solar(2034, 1, 1), pai_pan.date(2034, 2, 19))

    def test_leap_month_names_match_reference(self):
        """已知闰月年份的闰月月号必须精确命中。

        覆盖闰二月/闰四月/闰五月/闰六月/闰七月/闰九月等不同位置。
        这是抽样而不是全量：农历整块已委托 vendor/lunar_python，全量逐日比对
        只是在验证委托代码本身，代价数分钟而收益为零。真正需要守住的是
        「置闰错位后后续月号整体前移」这类回归，用定值表即可锁定。
        """
        sys.path.insert(0, HERE)
        import pai_pan

        # 公历年 -> 闰几月（取自公开万年历）
        expected = {
            2001: 4, 2004: 2, 2006: 7, 2009: 5, 2012: 4,
            2014: 9, 2017: 6, 2020: 4, 2023: 2,
        }
        for y, ref in sorted(expected.items()):
            found = [
                m for m in range(1, 13) if _is_leap_month_start(pai_pan, y, m)
            ]
            self.assertEqual(
                found, [ref], "%d 年应有且仅有闰%d月，实际 %s" % (y, ref, found)
            )

    def test_every_lunar_month_start_roundtrips(self):
        """每个农历月初一：公历→农历→公历 必须回到原日。

        只查月初一而不是逐日：月内日期由「初一 + n 天」保证，真正会错的是
        跨月的朔日定位（置闰错位的具体表现就在年初一）。
        2000–2050 约 630 个月，秒级完成。
        """
        sys.path.insert(0, HERE)
        import pai_pan

        checked = 0
        for y in range(2000, 2051):
            for m in range(1, 13):
                for leap in (False, True):
                    try:
                        day = pai_pan.lunar_to_solar(y, m, 1, leap=leap)
                    except ValueError:
                        continue
                    back = pai_pan.solar_to_lunar(day.year, day.month, day.day)
                    self.assertEqual(back, (y, m, 1, leap), "%d 年%s月%s月初一" % (
                        y, "闰" if leap else "", m))
                    checked += 1
        self.assertGreater(checked, 600)


class BoundaryTests(unittest.TestCase):
    """出生时刻落在四柱分界附近时，必须把可能的几种结果都列出来。"""

    def test_lichun_boundary_lists_both_results(self):
        """2024-02-04 16:27 紧邻立春（16:27:07），应同时列出卯年与辰年两种四柱。"""
        code, out, err = run_pai(
            "--solar", "2024-02-04", "--hour", "16:27", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = boundary_block(out)
        self.assertIn("癸卯", block)
        self.assertIn("甲辰", block)
        self.assertIn("当前输入", block)

    def test_normal_time_has_no_variants(self):
        """普通时刻不应输出边界情况小节：整节缺席，而不是用占位行代替。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "12:00", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        # 整节缺席是契约的一部分：下游按 ## 分节解析，不该平白多出一节。
        self.assertNotIn("## 边界情况", out)
        self.assertNotIn("出生时刻不在任何四柱分界附近", out)
        # 相邻的小节必须照常输出，证明省略只发生在这一节，没有连带吞掉别的。
        self.assertIn("## 神煞", out)
        self.assertIn("## 警告", out)

    def test_zi_hour_boundary_lists_both_days(self):
        """23:10 紧邻夜子时界：必须同时列出当日庚辰日柱与次日辛巳日柱。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "23:10", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = boundary_block(out)
        # 当前输入已是次日辛巳
        self.assertIn("辛巳", block)
        # 另一侧必须出现当日庚辰 —— 只有真的展开到边界另一侧才会出现
        self.assertIn("庚辰", block)
        self.assertIn("| 当前输入 |", block)

    def test_shichen_boundary_lists_both_hours(self):
        """22:50 紧邻 23:00 子时界：亥时丁亥与子时戊子两种时柱都要列出。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "22:50", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = boundary_block(out)
        self.assertIn("丁亥", block)
        self.assertIn("戊子", block)

    def test_place_warns_only_near_shichen_boundary(self):
        """--place 只在靠近时辰边界时提示「校正后可能跨时辰」。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "22:55", "--place", "乌鲁木齐", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("校正后可能跨时辰", section(out, "警告"))
        code2, out2, err2 = run_pai(
            "--solar", "1990-05-15", "--hour", "12:00", "--place", "北京", "--sex", "男"
        )
        self.assertEqual(code2, 0, err2)
        self.assertNotIn("校正后可能跨时辰", section(out2, "警告"))

    def test_solar_term_precision_matches_almanac(self):
        """节气必须到秒级，与公开年历值一致（紫金山天文台《中国天文年历》口径）。"""
        sys.path.insert(0, HERE)
        import pai_pan

        expected = {
            (2024, 315): "2024-02-04 16:27:07",
            (2024, 0): "2024-03-20 11:06:25",
            (2024, 90): "2024-06-21 04:51:00",
            (2024, 270): "2024-12-21 17:20:35",
            (2023, 270): "2023-12-22 11:27:20",
        }
        for (y, lon), want in expected.items():
            got = pai_pan.solar_term_beijing(y, lon).strftime("%Y-%m-%d %H:%M:%S")
            self.assertEqual(got, want, "%d 年黄经 %d 的节气时刻不符" % (y, lon))

    def test_qiyun_uses_second_precision(self):
        """起运按秒折算，不截断到分钟：410358 秒 = 1 岁 6 月，410400 秒 = 1 岁 7 月。"""
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertEqual(pai_pan.qiyun_from_days(410358.0 / 86400.0), (1, 6))
        # 410400 秒（恰好整分钟）按秒是 1 岁 7 个月；
        # 若先截断到分钟再算仍是 6839 分钟→6839//360=6 个月会退化成 (1, 6)。
        # 两者必须区分开，否则「按秒折算」这层精度实际上没被验证。
        self.assertEqual(pai_pan.qiyun_from_days(410400.0 / 86400.0), (1, 7))
        self.assertEqual(pai_pan.qiyun_from_days(1.0), (0, 4))
        self.assertEqual(pai_pan.qiyun_from_days(3.0), (1, 0))


class DayunLiunianTests(unittest.TestCase):
    """大运干支序列、起运前小运、流年干支锚点（此前为测试空白）。"""

    def test_dayun_sequence_forward(self):
        """顺排：从月柱下一柱起，每月柱干支顺行一位，年龄 10 年一档。"""
        sys.path.insert(0, HERE)
        import pai_pan

        rows = pai_pan.build_dayun("辛", "巳", True, 9, 9)
        self.assertEqual(rows[0], ("起运前", "0岁-9岁9个月", "辛巳（小运）"))
        self.assertEqual([r[2] for r in rows[1:4]], ["壬午", "癸未", "甲申"])
        self.assertEqual(rows[1][1], "9-18岁")
        self.assertEqual(rows[2][1], "19-28岁")

    def test_dayun_sequence_reverse(self):
        """逆排：从月柱上一柱起，每柱逆行一位。"""
        sys.path.insert(0, HERE)
        import pai_pan

        rows = pai_pan.build_dayun("辛", "巳", False, 3, 0)
        self.assertEqual([r[2] for r in rows[1:4]], ["庚辰", "己卯", "戊寅"])
        self.assertEqual(rows[0][1], "0岁-3岁")

    def test_dayun_wraps_at_jiazi(self):
        """甲子逆排一位应回到癸亥（十干十二支同时回绕，不得错位）。"""
        sys.path.insert(0, HERE)
        import pai_pan

        rows = pai_pan.build_dayun("甲", "子", False, 1, 0)
        self.assertEqual(rows[1][2], "癸亥")

    def test_liunian_anchor(self):
        """流年干支锚点：2024 甲辰、2025 乙巳，1984 甲子（六十甲子起点）。"""
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertEqual(pai_pan.liunian_gz(1984), "甲子")
        self.assertEqual(pai_pan.liunian_gz(2024), "甲辰")
        self.assertEqual(pai_pan.liunian_gz(2025), "乙巳")


class CliTests(unittest.TestCase):
    """命令行输入校验：非法输入必须被 argparse 接住并返回 2，不得抛堆栈。"""

    def test_invalid_solar_date_is_rejected_cleanly(self):
        """--solar 2001-02-30 是非法日期，必须友好报错而非未捕获堆栈。"""
        code, out, err = run_pai("--solar", "2001-02-30", "--sex", "男")
        self.assertEqual(code, 2, "期望退出码 2（argparse 用法错误），实际 %d" % code)
        self.assertNotIn("Traceback", err)
        self.assertIn("--solar", err)

    def test_malformed_solar_date_is_rejected(self):
        """--solar 2001/06/17 缺分隔符，应报错而不是崩溃。"""
        code, out, err = run_pai("--solar", "2001/06/17", "--sex", "男")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_invalid_hour_is_rejected(self):
        """--hour 25:00 越界，应友好报错。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "25:00", "--sex", "男"
        )
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)

    def test_nonexistent_leap_month_is_rejected(self):
        """2001 年闰四月，故不存在「闰五月」：--lunar 2001-05-01 --leap 必须返回 2。"""
        code, out, err = run_pai("--lunar", "2001-05-01", "--leap", "--sex", "男")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.assertIn("闰", err)


class LunarDateValidationTests(unittest.TestCase):
    """农历日期校验不得套用公历月长。

    回归：--lunar 曾复用 --solar 的 parse_iso_date，用 datetime.date 校验，
    而公历二月最多 29 天，导致合法的「农历 2023-02-30」被误判为非法。
    农历月长是 29/30 天、闰年有闰月，公历规则不适用。
    """

    def test_lunar_day_30_in_big_month_is_accepted(self):
        """2023 年正二月为 30 天大月（闰二月在次月）：农历 2023-02-30 = 公历 2023-03-21。"""
        code, out, err = run_pai("--lunar", "2023-02-30", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(field(out, "阳历"), "2023-03-21")
        self.assertEqual(field(out, "农历"), "2023年二月三十")

    def test_lunar_day_30_in_small_month_is_rejected(self):
        """2023 正月只有 29 天（小月），农历 2023-01-30 必须拒绝且提示小月。"""
        code, out, err = run_pai("--lunar", "2023-01-30", "--sex", "男")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.assertIn("29 天", err)

    def test_leap_month_day_maps_independently(self):
        """2023 闰二月 29 天：闰二月廿九 = 公历 2023-04-19，与正二月廿九（03-20）不同日。"""
        code, out, err = run_pai("--lunar", "2023-02-29", "--leap", "--sex", "男")
        self.assertEqual(code, 0, err)
        self.assertEqual(field(out, "阳历"), "2023-04-19")
        code2, out2, err2 = run_pai("--lunar", "2023-02-29", "--sex", "男")
        self.assertEqual(code2, 0, err2)
        self.assertEqual(field(out2, "阳历"), "2023-03-20")

    def test_solar_still_rejects_invalid_gregorian_day(self):
        """修复不得放松公历校验：--solar 2023-02-30 仍须拒绝。"""
        code, out, err = run_pai("--solar", "2023-02-30", "--sex", "男")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        self.assertIn("--solar", err)


class ShenshaTests(unittest.TestCase):
    def test_golden_shensha_hits_and_misses(self):
        """1990-05-15 午时男：有天乙贵人、将星；地支无申无卯，无驿马、桃花。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--shichen", "午", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        shensha = section(out, "神煞")
        self.assertNotEqual(shensha.strip(), "未计算")
        self.assertIn("天乙贵人", shensha)
        self.assertIn("将星", shensha)
        self.assertNotIn("驿马", shensha)
        self.assertNotIn("桃花", shensha)

    def test_extended_shensha_present(self):
        """补充条目必须在命中时输出：庚辰日见魁罡与十恶大败，夏月辰日见童子煞。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "12:00", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        shensha = section(out, "神煞")
        self.assertIn("魁罡", shensha)
        self.assertIn("十恶大败", shensha)
        self.assertIn("童子煞", shensha)
        self.assertIn("国印贵人", shensha)
        self.assertIn("福星贵人", shensha)

    def test_tongzi_method_note_matches_known_hours(self):
        """童子煞口径说明必须与是否给出时柱一致，不得宣称查了时支。

        时柱未知时不能声称「查日时支」——那是把未提供的信息当已用。
        """
        sys.path.insert(0, HERE)
        import pai_pan

        with_hour = pai_pan.compute(
            solar_date=pai_pan.date(1990, 5, 15), hour=12, minute=0, sex="男",
            now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ), with_variants=False,
        )
        tongzi = [l for l in with_hour["shensha_lines"] if "童子煞" in l]
        if tongzi:  # 命中有童子煞时核对说明措辞
            self.assertIn("日时支", tongzi[0])

        without_hour = pai_pan.compute(
            solar_date=pai_pan.date(1990, 5, 15), hour=None, minute=None, sex="男",
            now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ), with_variants=False,
        )
        tongzi_na = [l for l in without_hour["shensha_lines"] if "童子煞" in l]
        for line in tongzi_na:
            self.assertNotIn("日时支", line, "时柱未知却声称查了时支")
            self.assertIn("时柱未知", line)

    def test_tianshe_season_and_day_must_both_match(self):
        """天赦必须季节与日柱同时成立：戊寅日落在非春季月份不算天赦。

        特别注意：戊寅日全年会出现约 6 次，但只有落在寅卯辰月的才算「春戊寅」。
        """
        sys.path.insert(0, HERE)
        import pai_pan

        # 2000-01-21 是戊寅日，但月支为丑（冬），不是春 —— 不该判天赦
        r = pai_pan.compute(
            solar_date=pai_pan.date(2000, 1, 21),
            hour=12,
            minute=0,
            sex="男",
            now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ),
            with_variants=False,
        )
        self.assertEqual(r["pillars"]["month"][1], "丑")
        self.assertFalse(any("天赦" in line for line in r["shensha_lines"]))

        # 2000-03-21 是戊寅日，月支为卯（春）—— 应判天赦
        r2 = pai_pan.compute(
            solar_date=pai_pan.date(2000, 3, 21),
            hour=12,
            minute=0,
            sex="男",
            now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ),
            with_variants=False,
        )
        self.assertEqual(r2["pillars"]["month"][1], "卯")
        self.assertTrue(any("天赦" in line for line in r2["shensha_lines"]))

    def test_kuigang_overlap_is_intentional(self):
        """魁罡与十恶大败在庚辰、戊戌上重叠是古籍原貌，不应被当成 bug 去掉。"""
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertIn("庚辰", pai_pan.KUIGANG)
        self.assertIn("庚辰", pai_pan.SHIE_DAIBAI)
        self.assertIn("戊戌", pai_pan.KUIGANG)
        self.assertIn("戊戌", pai_pan.SHIE_DAIBAI)

    def test_shensha_table_driven(self):
        """日干甲见丑为天乙；日柱甲子旬空戌亥。"""
        sys.path.insert(0, HERE)
        import pai_pan

        cases = (
            {
                "name": "日干甲+地支丑→天乙",
                "args": ("乙", "亥", "戊", "丑", "甲", "寅", None, None, "男"),
                "has": ("天乙贵人",),
            },
            {
                "name": "日柱甲子→空亡戌亥",
                "args": ("甲", "戌", "乙", "亥", "甲", "子", None, None, "男"),
                "has": ("空亡",),
            },
        )
        for case in cases:
            with self.subTest(case["name"]):
                text = "\n".join(pai_pan.compute_shensha(*case["args"]))
                for name in case["has"]:
                    self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
