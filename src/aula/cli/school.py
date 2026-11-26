from collections.abc import Awaitable, Callable

import click

from ..api_client import AulaApiClient
from ..http import HttpRequestError
from ..models import (
    Group,
    Profile,
)
from ..utils.mapping import get_in
from ..utils.output import (
    build_contact_table,
    echo,
    format_post_lines,
    format_row,
    output_json,
    print_empty,
    print_error,
    print_heading,
    scope_relations_to_children,
)
from ..utils.table import (
    print_row_table,
)
from ._app import _get_client, async_cmd, cli


async def _fetch_groups(client: AulaApiClient) -> list[Group] | None:
    """Fetch the groups available in the user's context.

    Returns None and prints an error if the profile or groups can't be fetched.
    """
    try:
        prof: Profile = await client.get_profile()
    except (HttpRequestError, ValueError) as e:
        print_error(f"fetching profile: {e}")
        return None

    # Guardians filter by child institution profile IDs, which surfaces the
    # children's own class and SFO groups. Employees (and guardians with no
    # children listed) fall back to their institution codes.
    child_institution_profile_ids = [child.id for child in prof.children]

    institution_codes: list[str] = []
    if not child_institution_profile_ids and prof._raw:
        for inst_profile in prof._raw.get("institutionProfiles", []):
            code = inst_profile.get("institutionCode", "") if isinstance(inst_profile, dict) else ""
            if code and str(code) not in institution_codes:
                institution_codes.append(str(code))

    if not child_institution_profile_ids and not institution_codes:
        print_error("no children or institutions found on this profile")
        return None

    try:
        return await client.get_groups(
            institution_codes=institution_codes,
            child_institution_profile_ids=child_institution_profile_ids,
        )
    except HttpRequestError as e:
        print_error(f"fetching groups: {e}")
        return None


#: The contacts endpoints return at most this many profiles per page.
CONTACTS_PAGE_SIZE = 20


#: Safety stop so a server that never returns a short page can't loop forever.
MAX_CONTACT_PAGES = 200


async def _fetch_contact_pages(
    fetch_page: Callable[[int], Awaitable[list[dict]]],
    page: int | None = None,
) -> list[dict]:
    """Fetch one contact page, or walk every page when ``page`` is None.

    Paging stops on the first short page, matching how the Aula web client
    decides there is nothing more to load.
    """
    if page is not None:
        return await fetch_page(page)

    items: list[dict] = []
    for current in range(1, MAX_CONTACT_PAGES + 1):
        batch = await fetch_page(current)
        items.extend(batch)
        if len(batch) < CONTACTS_PAGE_SIZE:
            return items

    echo(
        f"Warning: stopped after {MAX_CONTACT_PAGES} pages; "
        "results may be incomplete. Use --page to fetch further pages."
    )
    return items


def _format_group_row(group: Group) -> str:
    """Render a group as a display row with its ID and metadata."""
    parts = [f"ID {group.id}"]
    if group.group_type:
        parts.append(group.group_type)
    if group.institution_code:
        parts.append(f"Inst {group.institution_code}")
    return format_row(group.name, *parts)


@cli.command()
@click.option("--group-id", type=int, default=None, help="Show a single group by ID.")
@click.option("--members", is_flag=True, help="List members of the group (requires --group-id).")
@click.option("--search", "search_text", default=None, help="Search for groups by name.")
@click.pass_context
@async_cmd
async def groups(ctx, group_id, members, search_text):
    """List child's groups, or show group detail / members."""
    async with await _get_client(ctx) as client:
        if search_text:
            try:
                result = await client.search_groups(search_text)
            except HttpRequestError as e:
                print_error(f"searching groups: {e}")
                return

            if output_json(ctx, [dict(g) for g in result]):
                return

            if not result:
                print_empty("matching groups")
                return

            print_heading(f'Groups matching "{search_text}"')
            for g in result:
                echo(_format_group_row(g))
            return

        if group_id and members:
            try:
                result = await client.get_group_members(group_id)
            except HttpRequestError as e:
                print_error(f"fetching group members: {e}")
                return

            if output_json(ctx, [dict(m) for m in result]):
                return

            if not result:
                print_empty("group members")
                return

            print_heading(f"Group {group_id} Members")
            for m in result:
                role = f" ({m.portal_role})" if m.portal_role else ""
                echo(format_row(m.name, f"ID {m.institution_profile_id}{role}"))
            return

        if group_id:
            try:
                group = await client.get_group(group_id)
            except HttpRequestError as e:
                print_error(f"fetching group: {e}")
                return

            if group is None:
                print_empty("group")
                return

            if output_json(ctx, dict(group)):
                return

            print_heading(f"Group: {group.name}")
            echo(format_row("ID", str(group.id)))
            if group.group_type:
                echo(format_row("Type", group.group_type))
            if group.institution_code:
                echo(format_row("Institution", group.institution_code))
            if group.description:
                echo(format_row("Description", group.description))
            return

        # List all groups for children
        result = await _fetch_groups(client)
        if result is None:
            return

        if output_json(ctx, [dict(g) for g in result]):
            return

        if not result:
            print_empty("groups")
            return

        print_heading("Groups")
        for g in result:
            echo(_format_group_row(g))


@cli.command()
@click.option(
    "--institution-profile-id",
    multiple=True,
    type=int,
    help="Filter posts by specific institution profile ID(s).",
)
@click.option("--post-id", type=int, default=None, help="Show a single post by ID.")
@click.option("--comments", is_flag=True, help="Show comments on the post (requires --post-id).")
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Maximum number of posts to fetch. Defaults to 10.",
)
@click.option(
    "--page",
    type=int,
    default=1,
    help="Page number to fetch. Defaults to 1.",
)
@click.pass_context
@async_cmd
async def posts(ctx, institution_profile_id, post_id, comments, limit, page):
    """Fetch posts from Aula."""
    async with await _get_client(ctx) as client:
        if post_id:
            try:
                post = await client.get_post(post_id)
            except HttpRequestError as e:
                print_error(f"fetching post: {e}")
                return

            if post is None:
                print_empty("post")
                return

            post_data = dict(post)
            comment_list = []
            if comments:
                try:
                    comment_list = await client.get_comments("post", post_id)
                    post_data["comments"] = [dict(c) for c in comment_list]
                except HttpRequestError as e:
                    print_error(f"fetching comments: {e}")

            if output_json(ctx, post_data):
                return

            date_str = post.timestamp.strftime("%Y-%m-%d %H:%M") if post.timestamp else ""
            for line in format_post_lines(
                title=post.title,
                author=post.owner.full_name,
                date=date_str,
                body=post.content,
                attachments_count=len(post.attachments),
                link=post.web_url,
            ):
                echo(line)

            if comment_list:
                echo()
                print_heading("Comments")
                for c in comment_list:
                    echo(format_row(c.creator_name, c.created_at))
                    echo(f"  {c.content}")
                    echo()
            return

        institution_profile_ids = list(institution_profile_id)

        if not institution_profile_ids:
            try:
                prof = await client.get_profile()
                institution_profile_ids = prof.institution_profile_ids
            except (HttpRequestError, ValueError) as e:
                print_error(f"fetching profile: {e}")
                return

        try:
            posts_list = await client.get_posts(
                page=page,
                limit=limit,
                institution_profile_ids=institution_profile_ids,
            )

            if output_json(ctx, [dict(p) for p in posts_list]):
                return

            if not posts_list:
                print_empty("posts")
                return

            print_heading("Posts")

            for i, post in enumerate(posts_list):
                date_str = post.timestamp.strftime("%Y-%m-%d %H:%M") if post.timestamp else ""

                for line in format_post_lines(
                    title=post.title,
                    author=post.owner.full_name,
                    date=date_str,
                    body=post.content,
                    attachments_count=len(post.attachments),
                    link=post.web_url,
                ):
                    echo(line)

                if i < len(posts_list) - 1:
                    echo()

        except HttpRequestError as e:
            print_error(f"fetching posts: {e}")
            return


@cli.command()
@click.argument("text")
@click.option("--type", "doc_type", default=None, help="Filter by document type.")
@click.option("--limit", type=int, default=20, help="Maximum results. Defaults to 20.")
@click.pass_context
@async_cmd
async def search(ctx, text, doc_type, limit):
    """Search Aula for posts, messages, and more."""
    async with await _get_client(ctx) as client:
        try:
            result = await client.search(text, doc_type=doc_type, limit=limit)
        except HttpRequestError as e:
            print_error(f"searching: {e}")
            return

        if output_json(ctx, result):
            return

        results = result.get("results", [])
        if not results:
            print_empty("search results")
            return

        print_heading(f'Search: "{text}"')
        for item in results:
            title = item.get("title", item.get("name", "Untitled"))
            item_type = item.get("docType", "")
            echo(format_row(title, item_type))


@cli.command()
@click.option(
    "--group-id",
    type=int,
    default=None,
    help="Filter contacts by group ID. Omit to list the available group IDs.",
)
@click.option("--parents", is_flag=True, help="Show other parents instead of group contacts.")
@click.option(
    "--profile-type",
    type=click.Choice(["guardian", "child", "boy", "girl", "employee"]),
    default="guardian",
    show_default=True,
    help="Which profiles to list. A group only has contacts for the types it contains.",
)
@click.option(
    "--page",
    type=int,
    default=None,
    help="Fetch only this 1-based page (20 per page). Default: every page.",
)
@click.pass_context
@async_cmd
async def contacts(ctx, group_id, parents, profile_type, page):
    """List contacts from groups or other parents.

    Rows pair each child with their guardians. With neither --group-id nor
    --parents, lists the available groups and their IDs.
    """
    async with await _get_client(ctx) as client:
        if parents:
            try:
                result = await _fetch_contact_pages(
                    lambda p: client.get_contact_parents(page=p), page
                )
            except HttpRequestError as e:
                print_error(f"fetching parent contacts: {e}")
                return
        elif group_id:
            try:
                result = await _fetch_contact_pages(
                    lambda p: client.get_contact_list(group_id, page=p, profile_type=profile_type),
                    page,
                )
                if profile_type == "guardian" and result:
                    # Guardians carry every child they have, so scope the pairing
                    # to the children who are actually in this group. Always read
                    # the full membership, even when --page limited the guardians.
                    group_children = await _fetch_contact_pages(
                        lambda p: client.get_contact_list(group_id, page=p, profile_type="child")
                    )
                    result = scope_relations_to_children(result, group_children)
            except HttpRequestError as e:
                print_error(f"fetching contacts: {e}")
                return
        else:
            # No group given: show the group IDs available to pick from.
            groups_result = await _fetch_groups(client)
            if groups_result is None:
                return

            if output_json(ctx, [dict(g) for g in groups_result]):
                return

            if not groups_result:
                print_empty("groups")
                return

            print_row_table(
                ["Group ID", "Name", "Institution"],
                [(str(g.id), g.name, g.institution_code) for g in groups_result],
                title="Available groups",
            )
            echo("")
            echo("Specify one with --group-id <ID>, or use --parents for other parents.")
            return

        if output_json(ctx, result):
            return

        if not result:
            print_empty("contacts")
            return

        headers, rows = build_contact_table(result)
        print_row_table(headers, rows, title="Contacts")


@cli.command("documents")
@click.option("--common", is_flag=True, help="Show common institution files instead.")
@click.pass_context
@async_cmd
async def documents(ctx, common):
    """List secure documents or common institution files."""
    async with await _get_client(ctx) as client:
        try:
            prof = await client.get_profile()
        except (HttpRequestError, ValueError) as e:
            print_error(f"fetching profile: {e}")
            return

        if common:
            await _print_common_files(ctx, client, prof)
            return

        try:
            own_ids = [
                ip["id"]
                for ip in get_in(prof._raw, "institutionProfiles", default=[])
                if isinstance(ip, dict) and "id" in ip
            ]
            result = await client.get_secure_documents(own_ids)
        except HttpRequestError as e:
            print_error(f"fetching documents: {e}")
            return

        if output_json(ctx, [dict(d) for d in result]):
            return

        if not result:
            print_empty("documents")
            return

        print_heading("Secure Documents")
        for doc in result:
            parts = [f"ID {doc.id}"]
            if doc.document_type:
                parts.append(doc.document_type)
            if doc.owner_name:
                parts.append(doc.owner_name)
            echo(format_row(doc.title, *parts))
            if doc.created_at:
                echo(f"  Created: {doc.created_at}")


def _institution_codes(prof: Profile) -> list[str]:
    """The children's schools, or the user's own when no children are listed."""
    sources = [child.institution_code for child in prof.children]
    if not prof.children and prof._raw:
        sources = [get_in(ip, "institutionCode") for ip in prof._raw.get("institutionProfiles", [])]
    return list(dict.fromkeys(str(code) for code in sources if code))


async def _print_common_files(ctx: click.Context, client: AulaApiClient, prof: Profile) -> None:
    try:
        files = await client.get_common_files(_institution_codes(prof))
    except HttpRequestError as e:
        print_error(f"fetching common files: {e}")
        return

    if output_json(ctx, [dict(f) for f in files]):
        return

    if not files:
        print_empty("common files")
        return

    print_heading("Common Files")
    for f in files:
        echo(format_row(f.title, *[p for p in (f.institution_name, f.file_name) if p]))
        if f.created_at:
            echo(f"  Created: {f.created_at}")
