"""
B-019 regression: light-mode selected rows must remain readable.

We can't run a real browser in CI, so these tests parse the static
``index.html`` and assert structural invariants that catch the original
bug class:

  * No hard-coded ``#1e2233`` (or any near-black hex) is applied as a
    selection background in code that runs in both themes.
  * The theme switch in App.useEffect sets ``--selected-bg`` for BOTH
    light and dark branches.
  * The ScanPage file-row uses ``var(--selected-bg)`` (theme-aware), not
    a hex literal.
"""
from pathlib import Path
import re

HTML = Path(__file__).parent.parent / "reencoder-api" / "static" / "index.html"


def test_index_html_exists():
    assert HTML.exists(), f"missing {HTML}"


def test_selected_bg_variable_is_defined_for_both_themes():
    """Both branches of the theme-switch effect must set --selected-bg."""
    txt = HTML.read_text(encoding="utf-8")
    # Match the light branch
    light_block = re.search(
        r"if \(theme === 'light'\) \{.*?\}\s*else\s*\{.*?\}",
        txt, flags=re.DOTALL,
    )
    assert light_block, "theme switch block not found in App"
    block = light_block.group(0)
    # The --selected-bg property must appear at least twice (light + dark)
    assert block.count("--selected-bg") >= 2, (
        "expected --selected-bg to be set in both theme branches; got: "
        + str(block.count('--selected-bg'))
    )
    # And --selected-fg too
    assert block.count("--selected-fg") >= 2


def test_scan_file_row_uses_selected_bg_variable():
    """The file row in ScanPage uses var(--selected-bg) (not #1e2233)."""
    txt = HTML.read_text(encoding="utf-8")
    # The smoking-gun line:
    #   background: f.selected ? '...' : 'transparent'
    m = re.search(
        r"f\.selected\s*\?\s*'([^']+)'\s*:\s*'transparent'", txt
    )
    assert m, "scan-page file-row background expression not found"
    selected_bg = m.group(1)
    assert selected_bg == "var(--selected-bg)", (
        f"scan-page selected row uses hardcoded {selected_bg!r}; expected "
        f"a theme-aware CSS var. This breaks light mode (B-019)."
    )


def test_no_hardcoded_1e2233_outside_css_root():
    """The original bug used the literal '#1e2233' inline. After the fix
    the only occurrence allowed is inside the dark-theme branch of the
    runtime theme setter, not in JSX inline styles."""
    txt = HTML.read_text(encoding="utf-8")
    # Allow the dark-theme branch — it sets the CSS var deliberately
    # via setProperty('--selected-bg', '#1e2233'). Forbidden is the
    # background-as-inline-string form.
    bad = re.findall(
        r"background:\s*[^,]*?['\"]#1e2233['\"]", txt
    )
    assert not bad, f"hardcoded selection bg found: {bad}"


def test_badge_gray_is_theme_aware():
    """badge-gray previously used #1e293b (dark slate) → invisible in light mode."""
    txt = HTML.read_text(encoding="utf-8")
    # In the CSS .badge-gray rule, the background must NOT be the
    # legacy hex literal — it should be a CSS var.
    m = re.search(r"\.badge-gray\s*\{[^}]*\}", txt)
    assert m, ".badge-gray rule not found"
    rule = m.group(0)
    assert "#1e293b" not in rule, ".badge-gray still hardcodes #1e293b (B-019)"
    assert "var(--" in rule, ".badge-gray should reference a CSS var"
