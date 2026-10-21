#!/usr/bin/env python3
"""
Read-only explorer for a Zoho Recruit account.

Pulls the account's structure through the Recruit v2 REST API (org, users,
modules, fields, layouts, related lists, picklists, record counts) and writes:

  out/snapshot.json   everything fetched, metadata only, no candidate data
  out/diagram.md      Mermaid flowcharts built from that snapshot

Only GET requests are made. Nothing in the account is changed.

Environment:
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN   (required)
  ZOHO_DC            data centre suffix, default "in" (in, com, eu, com.au, jp, ca, sa)
  MAX_COUNT_PAGES    pages of 200 to read per module when counting, default 10

Usage:
  python3 explore.py                     fetch from the API, then draw
  python3 explore.py --from out/snapshot.json   redraw from a saved snapshot
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
STATUS_FIELD = re.compile(r"(status|stage)$", re.IGNORECASE)


# ==================== API ====================

class Recruit:
    def __init__(self):
        dc = os.environ.get("ZOHO_DC", "in")
        self.accounts = f"https://accounts.zoho.{dc}"
        self.base = f"https://recruit.zoho.{dc}/recruit/v2"
        self.token = None

    def refresh(self):
        params = urllib.parse.urlencode({
            "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
            "client_id": os.environ["ZOHO_CLIENT_ID"],
            "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
            "grant_type": "refresh_token",
        }).encode()
        req = urllib.request.Request(f"{self.accounts}/oauth/v2/token", data=params, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        if "access_token" not in body:
            sys.exit(f"Token refresh failed: {body}")
        self.token = body["access_token"]

    def get(self, path, **params):
        url = f"{self.base}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(4):
            req = urllib.request.Request(url, headers={"Authorization": f"Zoho-oauthtoken {self.token}"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if r.status == 204:
                        return {}
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 0:
                    self.refresh()
                    continue
                if e.code == 429:
                    time.sleep(2 ** (attempt + 1))
                    continue
                detail = e.read().decode(errors="replace")[:300]
                print(f"  ! GET {path} -> {e.code} {detail}", file=sys.stderr)
                return None
        return None


def fetch():
    for var in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"):
        if not os.environ.get(var):
            sys.exit(f"Missing {var}. See README.md for how to create a Self Client.")
    max_pages = int(os.environ.get("MAX_COUNT_PAGES", "10"))
    api = Recruit()
    api.refresh()

    snap = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "base": api.base}
    print("org, users ...")
    snap["org"] = (api.get("org") or {}).get("org", [])
    users = (api.get("users", type="AllUsers") or {}).get("users", [])
    snap["users"] = [{"name": u.get("full_name"), "role": (u.get("role") or {}).get("name"),
                      "profile": (u.get("profile") or {}).get("name"), "status": u.get("status")}
                     for u in users]

    print("modules ...")
    modules = (api.get("settings/modules") or {}).get("modules", [])
    snap["modules"] = []
    for m in modules:
        name = m.get("api_name")
        if not name or m.get("api_supported") is False:
            continue
        print(f"  {name}")
        fields = (api.get("settings/fields", module=name) or {}).get("fields", [])
        layouts = (api.get("settings/layouts", module=name) or {}).get("layouts", [])
        related = (api.get("settings/related_lists", module=name) or {}).get("related_lists", [])
        snap["modules"].append({
            "api_name": name,
            "label": m.get("plural_label") or m.get("module_name") or name,
            "custom": bool(m.get("generated_type") == "custom" or m.get("custom")),
            "fields": [slim_field(f) for f in fields],
            "layouts": [l.get("name") for l in layouts],
            "related_lists": [{"label": r.get("display_label"), "module": module_name(r.get("module"))}
                              for r in related],
            "count": count_records(api, name, max_pages),
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "snapshot.json"), "w") as fh:
        json.dump(snap, fh, indent=2)
    return snap


def module_name(v):
    if isinstance(v, dict):
        return v.get("api_name") or v.get("module_name")
    return v


def slim_field(f):
    out = {"api_name": f.get("api_name"), "label": f.get("field_label"),
           "type": f.get("data_type"), "custom": f.get("custom_field", False)}
    if f.get("lookup"):
        out["lookup"] = module_name(f["lookup"].get("module"))
    if f.get("pick_list_values"):
        out["values"] = [v.get("display_value") for v in f["pick_list_values"]]
    return out


def count_records(api, module, max_pages):
    """Counts up to max_pages * 200 records. Returns e.g. 437 or '2000+'."""
    total = 0
    for page in range(1, max_pages + 1):
        body = api.get(module, page=page, per_page=200, fields="id")
        if body is None:
            return None
        total += len(body.get("data", []))
        if not body.get("info", {}).get("more_records"):
            return total
    return f"{total}+"


# ==================== DIAGRAM ====================

def nid(s):
    return re.sub(r"\W", "_", s or "x")


def q(s):
    return '"' + str(s).replace('"', "'") + '"'


def draw(snap):
    mods = {m["api_name"]: m for m in snap["modules"]}
    lines = [f"# Zoho Recruit: account map",
             "",
             f"Generated from `snapshot.json` fetched {snap.get('fetched_at')}.",
             ""]

    # ---- 1. Inputs -> modules -> relations
    lines += ["## How data comes in and how the modules connect", "", "```mermaid", "flowchart LR"]
    cand = mods.get("Candidates")
    sources = []
    if cand:
        for f in cand["fields"]:
            if f["api_name"] in ("Source", "Candidate_Source", "Origin") and f.get("values"):
                sources = [v for v in f["values"] if v and v != "-None-"]
                break
    if sources:
        lines.append('  subgraph IN["Candidate sources (Source picklist)"]')
        for s in sources:
            lines.append(f"    src_{nid(s)}[{q(s)}]")
        lines.append("  end")
        lines.append("  IN --> Candidates")

    lines.append('  subgraph CORE["Modules"]')
    for name, m in mods.items():
        count = m.get("count")
        label = f"{m['label']}" + (f"<br/>{count} records" if count not in (None, "") else "")
        shape = f"[({q(label)})]" if m.get("custom") else f"[{q(label)}]"
        lines.append(f"    {nid(name)}{shape}")
    lines.append("  end")

    edges = set()
    for name, m in mods.items():
        for f in m["fields"]:
            tgt = f.get("lookup")
            if tgt and tgt in mods and tgt != name:
                edges.add((name, tgt, f["label"]))
    for src, tgt, label in sorted(edges):
        lines.append(f"  {nid(src)} -- {q(label)} --> {nid(tgt)}")
    lines += ["```", ""]

    # ---- 2. One pipeline per status/stage picklist
    for name, m in mods.items():
        for f in m["fields"]:
            vals = [v for v in f.get("values", []) if v and v != "-None-"]
            if f["type"] == "picklist" and STATUS_FIELD.search(f["api_name"] or "") and len(vals) > 1:
                lines += [f"## {m['label']} - {f['label']}", "",
                          "Picklist order as configured. Real transitions may skip or jump steps.", "",
                          "```mermaid", "flowchart LR"]
                prev = None
                for i, v in enumerate(vals):
                    node = f"s{i}"
                    lines.append(f"  {node}[{q(v)}]")
                    if prev:
                        lines.append(f"  {prev} --> {node}")
                    prev = node
                lines += ["```", ""]

    # ---- 3. Field inventory
    lines += ["## Modules and fields", "", "| Module | Records | Fields | Custom fields | Lookups to |",
              "|---|---|---|---|---|"]
    for name, m in mods.items():
        customs = sum(1 for f in m["fields"] if f.get("custom"))
        looks = sorted({f["lookup"] for f in m["fields"] if f.get("lookup")})
        lines.append(f"| {m['label']} | {m.get('count', '')} | {len(m['fields'])} | {customs} | {', '.join(looks)} |")
    lines.append("")
    if snap.get("users"):
        lines += [f"## Users ({len(snap['users'])})", "", "| Name | Role | Profile | Status |", "|---|---|---|---|"]
        for u in snap["users"]:
            lines.append(f"| {u['name']} | {u['role']} | {u['profile']} | {u['status']} |")
        lines.append("")

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "diagram.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    print(f"wrote {path}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--from":
        with open(sys.argv[2]) as fh:
            draw(json.load(fh))
    else:
        draw(fetch())
