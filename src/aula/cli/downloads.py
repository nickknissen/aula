import click

from ..utils.output import (
    echo,
    output_json,
    print_heading,
)
from ._app import _get_client, async_cmd, cli


@cli.command("download-images")
@click.option(
    "--output",
    type=click.Path(),
    default="./aula_images",
    help="Output directory for downloaded images.",
)
@click.option(
    "--since",
    required=True,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Only download images from this date onwards (YYYY-MM-DD).",
)
@click.option(
    "--source",
    type=click.Choice(["all", "gallery", "posts", "messages"], case_sensitive=False),
    default="all",
    help="Which source(s) to download from.",
)
@click.option(
    "--tags",
    multiple=True,
    help="Filter gallery images by tag (can be specified multiple times).",
)
@click.option(
    "--max-size",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Largest file to download, in MB. Larger files count as failed.",
)
@click.pass_context
@async_cmd
async def download_images(ctx, output, since, source, tags, max_size):
    """Download images from Aula (gallery, posts, messages)."""
    from pathlib import Path

    from ..utils.download import (
        download_gallery_images,
        download_message_images,
        download_post_images,
    )

    output_path = Path(output)
    cutoff = since.date()
    tag_list = list(tags) if tags else None

    async with await _get_client(ctx) as client:
        is_json = ctx.obj.get("OUTPUT_FORMAT") == "json"
        if not is_json:
            print_heading("Download images")
        prof = await client.get_profile()
        institution_profile_ids = prof.institution_profile_ids

        # Children's institution profile IDs and institution codes (for message search)
        children_inst_ids = [child.id for child in prof.children]
        institution_codes: list[str] = []
        for child in prof.children:
            if child.institution_code and child.institution_code not in institution_codes:
                institution_codes.append(child.institution_code)

        total_downloaded = 0
        total_skipped = 0
        total_failed = 0
        message_issues: list[str] = []
        on_progress = echo if not is_json else lambda _msg: None
        max_bytes = max_size * 1024 * 1024

        def tally(counts) -> None:
            nonlocal total_downloaded, total_skipped, total_failed
            total_downloaded += counts.downloaded
            total_skipped += counts.skipped
            total_failed += counts.failed
            if not is_json:
                echo(f"  Downloaded: {counts.downloaded}")
                echo(f"  Skipped: {counts.skipped}")
                echo(f"  Failed: {counts.failed}")
                echo()

        if source in ("all", "gallery"):
            if not is_json:
                echo("Gallery")
            tally(
                await download_gallery_images(
                    client,
                    institution_profile_ids,
                    output_path,
                    cutoff,
                    tag_list,
                    on_progress=on_progress,
                    max_bytes=max_bytes,
                )
            )

        if source in ("all", "posts"):
            if not is_json:
                echo("Posts")
            tally(
                await download_post_images(
                    client,
                    institution_profile_ids,
                    output_path,
                    cutoff,
                    on_progress=on_progress,
                    max_bytes=max_bytes,
                )
            )

        if source in ("all", "messages"):
            if not is_json:
                echo("Messages")
            tally(
                await download_message_images(
                    client,
                    children_inst_ids,
                    institution_codes,
                    output_path,
                    cutoff,
                    on_progress=on_progress,
                    on_incomplete=message_issues.append,
                    max_bytes=max_bytes,
                )
            )

        failed_run = bool(message_issues) or total_failed > 0
        report: dict[str, object] = {
            "downloaded": total_downloaded,
            "skipped": total_skipped,
            "failed": total_failed,
        }
        if source in ("all", "messages"):
            report["message_export"] = {"complete": not message_issues, "issues": message_issues}
        if output_json(ctx, report):
            if failed_run:
                ctx.exit(1)
            return

        echo("Total")
        echo(f"  Downloaded: {total_downloaded}")
        echo(f"  Skipped: {total_skipped}")
        echo(f"  Failed: {total_failed}")
        if failed_run:
            ctx.exit(1)
