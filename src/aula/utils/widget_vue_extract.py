from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx


@dataclass
class WidgetSource:
    widget_id: str
    source_map_url: str
    source_path: str
    source_content: str


@dataclass
class WidgetSummary:
    widget_id: str
    source_map_url: str
    source_path: str
    source_content: str
    endpoints: list[str]


def extract_js_asset_urls_from_html(html: str, portal_url: str) -> list[str]:
    matches = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    urls = [urljoin(portal_url, src) for src in matches if src]
    return sorted({url for url in urls if url.lower().endswith(".js")})


def extract_sourcemap_url_from_js(js_url: str, js_text: str, headers: dict[str, str]) -> str:
    lowered_headers = {str(k).lower(): v for k, v in headers.items()}
    header_map = lowered_headers.get("sourcemap") or lowered_headers.get("x-sourcemap")
    if isinstance(header_map, str) and header_map:
        return urljoin(js_url, header_map)

    footer_matches = re.findall(r"sourceMappingURL\s*=\s*([^\s*]+)", js_text)
    if footer_matches:
        return urljoin(js_url, footer_matches[-1].strip())

    return js_url + ".map"


def extract_sourcemap_urls_from_portal_html(
    html: str,
    portal_url: str,
    js_assets: dict[str, tuple[str, dict[str, str]]],
) -> list[str]:
    sourcemap_urls: set[str] = set()
    for js_url in extract_js_asset_urls_from_html(html, portal_url):
        payload = js_assets.get(js_url)
        if payload is None:
            continue
        js_text, headers = payload
        sourcemap_urls.add(extract_sourcemap_url_from_js(js_url, js_text, headers))
    return sorted(sourcemap_urls)


def extract_sourcemap_urls_from_portal(portal_url: str, timeout: float = 30.0) -> list[str]:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        portal_response = client.get(portal_url)
        portal_response.raise_for_status()
        html = portal_response.text

        js_assets: dict[str, tuple[str, dict[str, str]]] = {}
        for js_url in extract_js_asset_urls_from_html(html, portal_url):
            response = client.get(js_url)
            if response.status_code != 200:
                continue
            js_assets[js_url] = (response.text, dict(response.headers))

        return extract_sourcemap_urls_from_portal_html(html, portal_url, js_assets)


def fetch_sourcemaps(urls: list[str], timeout: float = 30.0) -> list[tuple[str, dict[str, Any]]]:
    sourcemaps: list[tuple[str, dict[str, Any]]] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for url in urls:
            response = client.get(url)
            if response.status_code != 200:
                continue
            try:
                data = response.json()
            except ValueError:
                continue
            sourcemaps.append((url, data))
    return sourcemaps


def find_widget_source(
    widget_id: str,
    sourcemaps: list[tuple[str, dict[str, Any]]],
) -> WidgetSource | None:
    matcher = _build_widget_matcher(widget_id)
    matches: list[tuple[int, int, str, str, str]] = []

    for sourcemap_url, sourcemap in sourcemaps:
        sources = sourcemap.get("sources", [])
        for i, source_path in enumerate(sources):
            parsed = _parse_widget_component_path(source_path)
            if parsed is None:
                continue
            source_widget_id, source_version = parsed
            if matcher(source_widget_id, source_version):
                matches.append((source_version, i, sourcemap_url, source_path, source_widget_id))

    if not matches:
        return None

    best_version, best_index, sourcemap_url, source_path, source_widget_id = max(matches)
    sourcemap = next(data for url, data in sourcemaps if url == sourcemap_url)
    sources_content = sourcemap.get("sourcesContent", [])
    source_content = ""
    if best_index < len(sources_content) and isinstance(sources_content[best_index], str):
        source_content = sources_content[best_index]

    return WidgetSource(
        widget_id=source_widget_id,
        source_map_url=sourcemap_url,
        source_path=source_path,
        source_content=source_content,
    )


def _parse_widget_component_path(source_path: str) -> tuple[str, int] | None:
    match = re.fullmatch(
        r"webpack:///widgets/W(\d{1,4})V(\d{1,4})\.vue", source_path, flags=re.IGNORECASE
    )
    if not match:
        return None
    widget_num = int(match.group(1))
    version_num = int(match.group(2))
    return f"W{widget_num:04d}V{version_num:04d}", version_num


def _build_widget_matcher(widget_selector: str):
    clean = widget_selector.strip()

    digits_only = re.fullmatch(r"\d{1,4}", clean)
    if digits_only:
        widget_num = int(clean)
        widget_id = f"W{widget_num:04d}"
        return lambda source_widget_id, source_version: source_widget_id.startswith(widget_id)

    full_id = re.fullmatch(r"W?(\d{1,4})(?:V(\d{1,4}))?", clean, flags=re.IGNORECASE)
    if full_id:
        widget_num = int(full_id.group(1))
        version = full_id.group(2)
        widget_id = f"W{widget_num:04d}"
        if version is None:
            return lambda source_widget_id, source_version: source_widget_id.startswith(widget_id)
        version_num = int(version)
        full = f"{widget_id}V{version_num:04d}"
        return lambda source_widget_id, source_version: source_widget_id == full

    return lambda source_widget_id, source_version: source_widget_id == clean
    return None


def extract_endpoint_candidates(source: str) -> list[str]:
    urls = re.findall(r'https?://[^"\'\s)]+', source)
    paths = [
        match[1]
        for match in re.findall(
            r'(["\'])(/\?method=[A-Za-z0-9_.-]+[^"\']*|/api/[A-Za-z0-9_./?=&-]+)\1',
            source,
        )
    ]
    endpoints = sorted({*(u.rstrip("\"'") for u in urls), *paths})
    return endpoints


def extract_widget_summary(
    widget_id: str,
    sourcemaps: list[tuple[str, dict[str, Any]]],
) -> WidgetSummary:
    found = find_widget_source(widget_id, sourcemaps)
    if found is None:
        raise ValueError(f"Widget component not found in sourcemaps: {widget_id}")

    return WidgetSummary(
        widget_id=found.widget_id,
        source_map_url=found.source_map_url,
        source_path=found.source_path,
        source_content=found.source_content,
        endpoints=extract_endpoint_candidates(found.source_content),
    )


def render_widget_summary(summary: WidgetSummary) -> str:
    lines = [
        f"Widget: {summary.widget_id}",
        f"Component: {summary.widget_id}",
        f"Source map: {summary.source_map_url}",
        f"Source path: {summary.source_path}",
        "Endpoints:",
    ]
    if not summary.endpoints:
        lines.append("- (none found in component source)")
    else:
        lines.extend(f"- {endpoint}" for endpoint in summary.endpoints)
    lines.append("Source Content:")
    lines.append(summary.source_content or "(empty)")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m aula.utils.widget_vue_extract",
        description="Extract widget Vue endpoint summary from sourcemaps using widget id/key",
    )
    parser.add_argument(
        "widget_id",
        help="Widget id/key, e.g. 0030 or W0030V0001",
    )
    parser.add_argument(
        "--portal",
        default="https://www.aula.dk/portal/#/login",
        help="Portal URL used to discover JS assets and sourcemaps",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    sourcemap_urls = extract_sourcemap_urls_from_portal(args.portal)
    sourcemaps = fetch_sourcemaps(sourcemap_urls)
    summary = extract_widget_summary(args.widget_id, sourcemaps)
    print(render_widget_summary(summary))


if __name__ == "__main__":
    main()
