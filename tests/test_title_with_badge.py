"""Unit tests for title badge prefixing. No Codex CLI required."""

import importlib.util
from pathlib import Path
import sys


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugins" / "codex-model-badges" / "hooks" / "codex_model_badges.py"


def load_badges():
    spec = importlib.util.spec_from_file_location("codex_model_badges", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError(f"{message}: {actual!r} != {expected!r}")


def expect_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    badges = load_badges()
    sep = badges.SEPARATOR
    badge = lambda title, model="gpt-6.1-sol", speed=None, known=True: badges.title_with_badge(
        title, model, speed, known
    )

    expect_equal(badge("示例会话"), "☀️" + sep + "示例会话", "plain titles should get a model badge")
    expect_equal(
        badge("示例会话", speed="fast"),
        "☀️ ⚡" + sep + "示例会话",
        "Fast mode should add a speed icon",
    )
    expect_equal(
        badge("☀️" + sep + "示例会话", "gpt-6.1-terra"),
        "🌍" + sep + "示例会话",
        "an existing plugin prefix should be replaced",
    )
    expect_equal(
        badge("☀️ ⚡" + sep + "示例会话", "gpt-6.1-sol", None, True),
        "☀️" + sep + "示例会话",
        "turning Fast off should drop the speed icon",
    )

    issue_title = "✨ 【进行中】OCR架构设计"
    expect_equal(badge(issue_title, "gpt-6-astra"), issue_title, "issue #2: do not stack a second ✨")
    expect_equal(badge(issue_title, "gpt-6.1-sol"), issue_title, "do not add a different model badge either")
    expect_equal(badge("📌 示例会话"), "📌 示例会话", "user emoji such as 📌 should be left alone")
    expect_equal(badge("☀️ 整理项目需求"), "☀️ 整理项目需求", "a sun emoji with a regular space is a user prefix")

    for title in (
        "【进行中】OCR架构设计",
        "A ✨ title",
        "© copyright",
        "# hash",
        "2026 plan",
        "你好世界",
    ):
        result = badge(title)
        expect_true(result.startswith("☀️" + sep), f"{title!r} should still get a badge, got {result!r}")
        expect_true(result.endswith(title), f"{title!r} body should be preserved, got {result!r}")

    for title in ("©️ copyright", "1️⃣ list", "🇯🇵 trip", "👍🏻 ok", "👨‍💻 dev", "⭐ star", "⚡ 快"):
        expect_equal(badge(title), title, f"{title!r} already starts with an emoji")

    expect_equal(badges.leading_emoji_length("✨ 【进行中】"), 1, "sparkles is one code point")
    expect_equal(badges.leading_emoji_length("☀️ 整理"), 2, "☀️ includes the variation selector")
    expect_equal(badges.leading_emoji_length("👨‍💻 dev"), len("👨‍💻"), "ZWJ sequences are one emoji")
    expect_equal(badges.leading_emoji_length("©️ copyright"), 2, "©️ includes the variation selector")
    expect_equal(badges.leading_emoji_length("© copyright"), 0, "bare © is text presentation")
    expect_equal(badges.leading_emoji_length("示例会话"), 0, "CJK text is not an emoji")
    print("PASS: title_with_badge leaves leading emoji titles unchanged")
    print("PASS: plain titles and existing plugin prefixes still update")
    print("PASS: flags, keycaps, skin tones, and ZWJ sequences count as one emoji")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
