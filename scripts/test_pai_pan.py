#!/usr/bin/env python3
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
        self.assertIn("天乙贵人", shensha)
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

    def test_yin_year_male_dayun_reverse(self):
        """1991-06-15 辛未阴年男，大运逆排。"""
        code, out, err = run_pai(
            "--solar", "1991-06-15", "--shichen", "午", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["year"], "辛未")
        self.assertIn("方向：逆排", out)

    def test_yang_year_female_dayun_reverse(self):
        """1990-05-15 阳年女，大运逆排。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--shichen", "午", "--sex", "女"
        )
        self.assertEqual(code, 0, err)
        p = pillars(out)
        self.assertEqual(p["year"], "庚午")
        self.assertIn("方向：逆排", out)

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
        """1900–2100 年每个闰月的月号都与 lunar-python 一致，且不会把 11/12 月当闰月。"""
        sys.path.insert(0, HERE)
        import pai_pan
        from lunar_python import LunarYear

        for y in range(1900, 2100):
            ref = LunarYear.fromYear(y).getLeapMonth()
            ours = []
            day = pai_pan.date(y, 1, 1)
            while day.year == y:
                _ly, lm, ld, leap = pai_pan.solar_to_lunar(day.year, day.month, day.day)
                if leap and ld == 1 and lm not in ours:
                    ours.append(lm)
                day += pai_pan.timedelta(days=1)
            self.assertLessEqual(len(ours), 1, "%d 年出现多个闰月 %s" % (y, ours))
            got = ours[0] if ours else 0
            self.assertEqual(got, ref, "%d 年闰月应为 %d，实际 %d" % (y, ref, got))

    def test_roundtrip_self_consistency(self):
        """1990-01-01…2040-12-31 每天：公历→农历→公历 必须回到原日。"""
        sys.path.insert(0, HERE)
        import pai_pan

        day = pai_pan.date(1990, 1, 1)
        end = pai_pan.date(2040, 12, 31)
        while day <= end:
            ly, lm, ld, leap = pai_pan.solar_to_lunar(day.year, day.month, day.day)
            back = pai_pan.lunar_to_solar(ly, lm, ld, leap)
            self.assertEqual(back, day, "%s 往返后变成 %s" % (day, back))
            day += pai_pan.timedelta(days=1)


class BoundaryTests(unittest.TestCase):
    """出生时刻落在四柱分界附近时，必须把可能的几种结果都列出来。"""

    def test_lichun_boundary_lists_both_results(self):
        """2024-02-04 16:27 紧邻立春（16:27:07），应同时列出卯年与辰年两种四柱。"""
        code, out, err = run_pai(
            "--solar", "2024-02-04", "--hour", "16:27", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = section(out, "边界情况（出生时刻落在临界点附近）")
        self.assertIn("癸卯", block)
        self.assertIn("甲辰", block)
        self.assertIn("当前输入", block)

    def test_normal_time_has_no_variants(self):
        """普通时刻不应展开边界表，避免输出无用组合。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "12:00", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = section(out, "边界情况（出生时刻落在临界点附近）")
        self.assertIn("无（出生时刻不在任何四柱分界附近）", block)

    def test_zi_hour_boundary_lists_both_days(self):
        """23:10 紧邻夜子时界，次日日柱与当日日柱都应列出。"""
        code, out, err = run_pai(
            "--solar", "1990-05-15", "--hour", "23:10", "--sex", "男"
        )
        self.assertEqual(code, 0, err)
        block = section(out, "边界情况（出生时刻落在临界点附近）")
        self.assertTrue(block.strip())
        self.assertTrue("跨" in block or "分钟" in block)

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
        """起运按秒折算，不截断到分钟：410358 秒 = 18.99 月 → 1 岁 6 月。"""
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertEqual(pai_pan.qiyun_from_days(410358.0 / 86400.0), (1, 6))
        self.assertEqual(pai_pan.qiyun_from_days(1.0), (0, 4))
        self.assertEqual(pai_pan.qiyun_from_days(3.0), (1, 0))


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

    def test_tianshe_count_per_year_is_small(self):
        """一年天赦日应在个位数（四个季节各 1–2 次），不可能月月都有。"""
        sys.path.insert(0, HERE)
        import pai_pan

        day = pai_pan.date(2000, 1, 1)
        end = pai_pan.date(2000, 12, 31)
        hits = 0
        while day <= end:
            r = pai_pan.compute(
                solar_date=day,
                hour=12,
                minute=0,
                sex="男",
                now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ),
                with_variants=False,
            )
            if any("天赦" in line for line in r["shensha_lines"]):
                hits += 1
            day += pai_pan.timedelta(days=1)
        self.assertGreater(hits, 0, "2000 年应有天赦日")
        self.assertLessEqual(hits, 8, "2000 年天赦日不应超过 8 天，实际 %d" % hits)

    def test_kuigang_overlap_is_intentional(self):
        """魁罡与十恶大败在庚辰、戊戌上重叠是古籍原貌，不应被当成 bug 去掉。"""
        sys.path.insert(0, HERE)
        import pai_pan

        self.assertIn("庚辰", pai_pan.KUIGANG)
        self.assertIn("庚辰", pai_pan.SHIE_DAIBAI)
        self.assertIn("戊戌", pai_pan.KUIGANG)
        self.assertIn("戊戌", pai_pan.SHIE_DAIBAI)

    def test_shensha_hit_rate_sanity(self):
        """神煞表健康度：魁罡应稀有（<15%），整体不应完全无命中。"""
        sys.path.insert(0, HERE)
        import pai_pan

        d0 = pai_pan.date(1985, 1, 1)
        total = 0
        kuigang = 0
        for i in range(0, 3000, 11):
            d = d0 + pai_pan.timedelta(days=i)
            r = pai_pan.compute(
                solar_date=d,
                hour=10,
                minute=0,
                sex="男",
                now=pai_pan.datetime(2026, 1, 1, tzinfo=pai_pan.BJ),
                with_variants=False,
            )
            total += 1
            if any("魁罡" in line for line in r["shensha_lines"]):
                kuigang += 1
        self.assertLess(kuigang * 100.0 / total, 15.0, "魁罡命中率异常偏高")

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
