import aula.utils.widget_vue_extract as widget_vue_extract
from aula.utils.widget_vue_extract import (
    extract_endpoint_candidates,
    extract_js_asset_urls_from_html,
    extract_sourcemap_url_from_js,
    extract_sourcemap_urls_from_portal_html,
    extract_widget_summary,
    find_widget_source,
    render_widget_summary,
)


def test_find_widget_source_matches_exact_component_path() -> None:
    sourcemaps = [
        (
            "https://www.aula.dk/static/js/10.js.map",
            {
                "sources": [
                    "webpack:///widgets/W0001V0001.vue",
                    "webpack:///widgets/W0030V0001.vue",
                ],
                "sourcesContent": ["a", "<template></template>"],
            },
        )
    ]

    found = find_widget_source("W0030V0001", sourcemaps)

    assert found is not None
    assert found.widget_id == "W0030V0001"
    assert found.source_path == "webpack:///widgets/W0030V0001.vue"
    assert found.source_map_url == "https://www.aula.dk/static/js/10.js.map"


def test_extract_endpoint_candidates_picks_urls_and_relative_api_paths() -> None:
    source = "\n".join(
        [
            "const x = 'https://api.minuddannelse.net/aula/opgaveliste';",
            "const y = '/api/Aula/INTileGet/56';",
            "const z = '/?method=aulaToken.getAulaToken&widgetId=' + id;",
        ]
    )

    endpoints = extract_endpoint_candidates(source)

    assert "https://api.minuddannelse.net/aula/opgaveliste" in endpoints
    assert "/api/Aula/INTileGet/56" in endpoints
    assert "/?method=aulaToken.getAulaToken&widgetId=" in endpoints


def test_extract_widget_summary_returns_component_and_endpoint_summary() -> None:
    sourcemaps = [
        (
            "https://www.aula.dk/static/js/10.js.map",
            {
                "sources": ["webpack:///widgets/W0030V0001.vue"],
                "sourcesContent": ["const url='https://api.minuddannelse.net/aula/opgaveliste';"],
            },
        )
    ]

    summary = extract_widget_summary("W0030V0001", sourcemaps)

    assert summary.widget_id == "W0030V0001"
    assert summary.source_path == "webpack:///widgets/W0030V0001.vue"
    assert summary.endpoints == ["https://api.minuddannelse.net/aula/opgaveliste"]


def test_extract_widget_summary_accepts_numeric_widget_id() -> None:
    sourcemaps = [
        (
            "https://www.aula.dk/static/js/10.js.map",
            {
                "sources": [
                    "webpack:///widgets/W0030V0001.vue",
                    "webpack:///widgets/W0030V0002.vue",
                ],
                "sourcesContent": [
                    "const url='https://api.minuddannelse.net/aula/opgaveliste';",
                    "const url='https://api.minuddannelse.net/aula/opgaveliste/v2';",
                ],
            },
        )
    ]

    summary = extract_widget_summary("0030", sourcemaps)

    assert summary.widget_id == "W0030V0002"
    assert summary.source_path == "webpack:///widgets/W0030V0002.vue"
    assert summary.endpoints == ["https://api.minuddannelse.net/aula/opgaveliste/v2"]


def test_module_has_no_har_extract_helpers() -> None:
    assert not hasattr(widget_vue_extract, "extract_sourcemap_urls_from_har")
    assert not hasattr(widget_vue_extract, "extract_sourcemap_urls_from_har_data")


def test_extract_js_asset_urls_from_html_finds_script_sources() -> None:
    html = """
    <html><head>
      <script src="/static/js/app.123.js"></script>
      <script src="https://www.aula.dk/static/js/10.abc.js"></script>
      <script>console.log('inline')</script>
    </head></html>
    """

    urls = extract_js_asset_urls_from_html(html, "https://www.aula.dk/portal/#/login")

    assert "https://www.aula.dk/static/js/app.123.js" in urls
    assert "https://www.aula.dk/static/js/10.abc.js" in urls


def test_extract_sourcemap_url_from_js_reads_footer_mapping() -> None:
    js = "console.log('x');\n//# sourceMappingURL=10.abc.js.map\n"

    url = extract_sourcemap_url_from_js(
        "https://www.aula.dk/static/js/10.abc.js",
        js,
        {},
    )

    assert url == "https://www.aula.dk/static/js/10.abc.js.map"


def test_extract_sourcemap_urls_from_portal_html_uses_header_and_fallback() -> None:
    html = """
    <script src="https://www.aula.dk/static/js/with-header.js"></script>
    <script src="https://www.aula.dk/static/js/with-footer.js"></script>
    <script src="https://www.aula.dk/static/js/with-neither.js"></script>
    """

    js_assets = {
        "https://www.aula.dk/static/js/with-header.js": (
            "console.log('x')",
            {"SourceMap": "with-header.js.map"},
        ),
        "https://www.aula.dk/static/js/with-footer.js": (
            "//# sourceMappingURL=with-footer.js.map",
            {},
        ),
        "https://www.aula.dk/static/js/with-neither.js": (
            "console.log('z')",
            {},
        ),
    }

    urls = extract_sourcemap_urls_from_portal_html(
        html,
        "https://www.aula.dk/portal/#/login",
        js_assets,
    )

    assert "https://www.aula.dk/static/js/with-header.js.map" in urls
    assert "https://www.aula.dk/static/js/with-footer.js.map" in urls
    assert "https://www.aula.dk/static/js/with-neither.js.map" in urls


def test_render_widget_summary_includes_component_line() -> None:
    sourcemaps = [
        (
            "https://www.aula.dk/static/js/10.js.map",
            {
                "sources": ["webpack:///widgets/W0030V0001.vue"],
                "sourcesContent": ["const url='https://api.minuddannelse.net/aula/opgaveliste';"],
            },
        )
    ]

    summary = extract_widget_summary("0030", sourcemaps)
    text = render_widget_summary(summary)

    assert "Component: W0030V0001" in text


def test_render_widget_summary_includes_widget_source_content() -> None:
    sourcemaps = [
        (
            "https://www.aula.dk/static/js/10.js.map",
            {
                "sources": ["webpack:///widgets/W0030V0001.vue"],
                "sourcesContent": ["<template><div>Widget</div></template>"],
            },
        )
    ]

    summary = extract_widget_summary("0030", sourcemaps)
    text = render_widget_summary(summary)

    assert "Source Content:" in text
    assert "<template><div>Widget</div></template>" in text
