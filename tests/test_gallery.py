import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "registry-with-logos.json"
GALLERY_DATA_PATH = ROOT / "data" / "gallery.json"
INDEX_PATH = ROOT / "web" / "index.html"
APP_PATH = ROOT / "web" / "app.js"
CORE_PATH = ROOT / "web" / "gallery-core.js"
STYLES_PATH = ROOT / "web" / "styles.css"
THEME_PATH = ROOT / "web" / "theme.js"
THEME_UI_PATH = ROOT / "web" / "theme-ui.js"


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_gallery_files_and_accessibility_shell_exist() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    styles = STYLES_PATH.read_text(encoding="utf-8")

    assert INDEX_PATH.is_file()
    assert STYLES_PATH.is_file()
    assert THEME_PATH.is_file()
    assert THEME_UI_PATH.is_file()
    assert GALLERY_DATA_PATH.is_file()
    assert '<script type="module" src="app.js"></script>' in index
    assert '<link rel="stylesheet" href="styles.css">' in index
    assert 'href="#gallery-content"' in index
    assert 'id="gallery-content"' in index
    assert 'aria-live="polite"' in index
    assert 'id="search-input"' in index
    assert 'id="entity-type-filter"' in index
    assert 'id="country-filter"' in index
    assert 'id="format-filter"' in index
    assert 'id="rights-filter"' in index
    assert 'id="reset-filters"' in index
    assert 'id="load-more"' in index
    assert 'id="theme-select"' in index
    assert 'value="system"' in index
    assert 'value="light"' in index
    assert 'value="dark"' in index
    assert "gfr-gallery-theme" in index
    assert index.index("localStorage.getItem") < index.index('<link rel="stylesheet" href="styles.css">')
    assert "--color-canvas" in styles
    assert 'data-theme="dark"' in styles
    assert "@media (prefers-color-scheme: dark)" in styles
    assert "color-scheme: dark" in styles
    assert "--color-preview" in styles
    assert "--dark-color-preview: #f0ede7;" in styles
    assert styles.count("--color-preview: var(--dark-color-preview);") == 2
    assert ".visually-hidden" in styles


def test_every_registry_staging_path_resolves_to_a_local_binary() -> None:
    registry = load_registry()

    assert registry["asset_root"] == "assets"
    assert registry["assets"]
    for asset in registry["assets"]:
        staging_path = Path(asset["staging_path"])
        assert not staging_path.is_absolute()
        assert ".." not in staging_path.parts
        local_path = ROOT / "data" / "assets" / staging_path
        assert local_path.is_file(), asset["staging_path"]


def test_gallery_script_uses_safe_dom_and_source_url_guards() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    core = CORE_PATH.read_text(encoding="utf-8")

    assert APP_PATH.is_file()
    assert CORE_PATH.is_file()
    assert "../data/gallery.json" in app
    assert "textContent" in app
    assert "innerHTML" not in app
    assert re.search(r"new URL\(", core)
    assert "noopener" in app
    assert "noopener noreferrer" in app
    assert 'from "./theme-ui.js"' in app
    assert "recordPreviewFailure" in app
    assert "setTimeout" in app
    assert "limitCards" in app
    assert "theme-select" in app
    assert "https:" in core
    assert "http:" in core


def test_gallery_bootstrap_and_theme_module_share_storage_key() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")
    theme = THEME_PATH.read_text(encoding="utf-8")

    match = re.search(r'THEME_STORAGE_KEY\s*=\s*"([^"]+)"', theme)
    assert match
    assert f'localStorage.getItem("{match.group(1)}")' in index


def test_gallery_copy_explains_scope_and_rights() -> None:
    index = INDEX_PATH.read_text(encoding="utf-8")

    assert "identification" in index.lower()
    assert "no blanket open" in index.lower()
    assert "without a logo" in index.lower()
