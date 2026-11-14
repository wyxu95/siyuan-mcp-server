"""Notebook access policy shared by HTTPS and local MCP tools."""
import posixpath
import re
from contextvars import ContextVar
from urllib.parse import unquote

from sqlglot import exp, parse
from sqlglot.optimizer.scope import traverse_scope


web_client = ContextVar("siyuan_web_client", default=False)
_tables = {"blocks", "spans", "assets", "attributes", "refs"}


def notebook_policy(raw):
    notebooks = raw("/api/notebook/lsNotebooks")["notebooks"]
    suffixes = ("(-NM)", "(-NB)") if web_client.get() else ("(-NM)",)
    denied = {item["id"] for item in notebooks if item["name"].endswith(suffixes)}
    return notebooks, denied


def scope_sql(query, denied):
    statements = parse(query, read="sqlite")
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise PermissionError("Only a single read-only query is available")
    tree = statements[0]
    for function in tree.find_all(exp.Anonymous):
        if function.name.lower() in {"readfile", "writefile", "load_extension"}:
            raise PermissionError("File access is available through the file tools")
    tables = [source for scope in traverse_scope(tree) for source in scope.sources.values() if isinstance(source, exp.Table)]
    for table in tables:
        name = table.name.lower()
        if table.db or table.catalog or not isinstance(table.this, exp.Identifier):
            raise PermissionError("Only notebook content tables are available")
        if name not in _tables:
            raise PermissionError("Only notebook content tables are available")
        filtered = exp.select("*").from_(name)
        if denied:
            filtered = filtered.where(exp.not_(exp.column("box").isin(*sorted(denied))))
        table.replace(filtered.subquery(table.alias_or_name))
    return tree.sql(dialect="sqlite")


def check_blocks(ids, denied, raw):
    ids = [value for value in ids if value]
    if not ids:
        return
    literals = ",".join("'" + str(value).replace("'", "''") + "'" for value in ids)
    rows = raw("/api/query/sql", {"stmt": f"SELECT box FROM blocks WHERE id IN ({literals})"})
    if any(row["box"] in denied for row in rows):
        raise PermissionError("This notebook is unavailable to this MCP client")


def checked_path(path, denied):
    decoded = unquote(path)
    if "\\" in decoded or ".." in decoded.split("/"):
        raise PermissionError("Use a workspace-relative notebook or asset path")
    normalized = posixpath.normpath("/" + decoded.lstrip("/"))
    if any(part in denied for part in normalized.split("/")):
        raise PermissionError("This notebook is unavailable to this MCP client")
    return normalized


def check_file(path, raw):
    notebooks, denied = notebook_policy(raw)
    normalized = checked_path(path, denied)
    parts = normalized.split("/")
    if normalized.startswith("/data/assets/"):
        asset = normalized.removeprefix("/data/").replace("'", "''")
        rows = raw("/api/query/sql", {"stmt": f"SELECT box FROM assets WHERE path='{asset}'"})
        if rows and all(row["box"] not in denied for row in rows):
            return
    elif normalized.endswith(".sy"):
        known = {notebook["id"] for notebook in notebooks}
        if any(part in known - denied for part in parts):
            return
        block_id = posixpath.basename(normalized)[:-3].replace("'", "''")
        rows = raw("/api/query/sql", {"stmt": f"SELECT box FROM blocks WHERE id='{block_id}'"})
        if rows and all(row["box"] not in denied for row in rows):
            return
    raise PermissionError("File access is limited to permitted notebook documents and their indexed assets")


def prepare_request(endpoint, data, raw):
    if endpoint.startswith("/api/notification/"):
        return data, set()
    notebooks, denied = notebook_policy(raw)
    data = dict(data or {})
    if endpoint == "/api/query/sql":
        data["stmt"] = scope_sql(data["stmt"], denied)
    elif endpoint == "/api/file/readDir":
        path = checked_path(data["path"], denied)
        known = {notebook["id"] for notebook in notebooks}
        permitted = path in {"/data", "/data/assets", "/history", "/data/history"}
        permitted |= path.startswith(("/history/", "/data/history/", "/data/assets/"))
        permitted |= any(part in known - denied for part in path.split("/"))
        if not permitted:
            raise PermissionError("Directory access is limited to notebooks, assets and history")
    else:
        if data.get("notebook") in denied:
            raise PermissionError("This notebook is unavailable to this MCP client")
        check_blocks([data.get(key) for key in ("id", "parentID", "nextID", "previousID")], denied, raw)
    return data, denied


def filter_response(endpoint, result, denied, raw, data=None):
    if endpoint == "/api/notebook/lsNotebooks":
        return {**result, "notebooks": [item for item in result["notebooks"] if item["id"] not in denied]}
    if endpoint == "/api/file/readDir":
        visible = []
        for item in result:
            name = item.get("name", "")
            if name in denied:
                continue
            path = checked_path((data or {}).get("path", "/data"), denied)
            if path.startswith("/data/assets") and not item.get("isDir"):
                try:
                    check_file(posixpath.join(path, name), raw)
                except PermissionError:
                    continue
            if name.endswith(".sy") and re.fullmatch(r"\d{14}-[a-zA-Z0-9]+\.sy", name):
                try:
                    check_blocks([name[:-3]], denied, raw)
                except PermissionError:
                    continue
            visible.append(item)
        return visible
    return result
