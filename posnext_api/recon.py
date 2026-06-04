"""
Malindi Stock Take Utility
==========================

Generates Excel reports for stock in the Malindi warehouses, transfers
stock from the Main + Damages warehouses into the Shop warehouse, and
finally zeroes out the Shop warehouse via a Stock Reconciliation.

Usage (from frappe-bench):
        bench --site <site> execute \
            mtolori_api.malindi_stock_take.run_stock_take

Excel files are written to:
        sites/<site>/private/files/malindi_stock_take_<timestamp>/
"""

import os
from datetime import datetime

import frappe
from frappe.utils import flt, getdate, now_datetime, nowdate, nowtime
from frappe.utils.xlsxutils import make_xlsx


def _log(msg):
    """Best-effort logger that won't crash if log files aren't writable."""
    try:
        frappe.logger().info(msg)
    except Exception:
        pass
    print(msg)

SOURCE_WAREHOUSES = [
    "Stores - GC"
]
TARGET_WAREHOUSE = "GLOWEMPIRE KAMAKIS SHOP - GC"

ALL_WAREHOUSES = SOURCE_WAREHOUSES + [TARGET_WAREHOUSE]

EXCEL_HEADERS = ["Item Code", "Item Name", "Available Quantity", "Valuation Rate", "Stock Value"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stock_rows(warehouse):
    """Return list of dict rows of positive stock in warehouse."""
    return frappe.db.sql(
        """
        SELECT b.item_code        AS item_code,
               i.item_name        AS item_name,
               b.actual_qty       AS qty,
               b.valuation_rate   AS valuation_rate,
               b.stock_value      AS stock_value
        FROM   `tabBin` b
        INNER JOIN `tabItem` i ON i.name = b.item_code
        WHERE  b.warehouse = %s
          AND  b.actual_qty <> 0
        ORDER  BY i.item_name
        """,
        (warehouse,),
        as_dict=True,
    )


def _safe_filename(label):
    keep = "-_ "
    return "".join(c if c.isalnum() or c in keep else "_" for c in label).strip()


def _ensure_output_dir():
    site_path = frappe.get_site_path("private", "files")
    stamp = now_datetime().strftime("%Y%m%d_%H%M%S")
    folder = os.path.join(site_path, f"malindi_stock_take_{stamp}")
    os.makedirs(folder, exist_ok=True)
    return folder


def _write_excel(folder, label, rows):
    data = [EXCEL_HEADERS]
    total_qty = 0.0
    total_value = 0.0
    for r in rows:
        qty = flt(r.get("qty"))
        rate = flt(r.get("valuation_rate"))
        value = flt(r.get("stock_value"))
        total_qty += qty
        total_value += value
        data.append([r.get("item_code"), r.get("item_name"), qty, rate, value])
    data.append(["", "TOTAL", total_qty, "", total_value])

    _INVALID_SHEET_CHARS = r'[]:*?/\\'
    safe_sheet = "".join(c if c not in _INVALID_SHEET_CHARS else "-" for c in label)[:30] or "Stock"
    xlsx = make_xlsx(data, sheet_name=safe_sheet)
    filename = f"{_safe_filename(label)}.xlsx"
    path = os.path.join(folder, filename)
    with open(path, "wb") as fh:
        fh.write(xlsx.getvalue())
    return path


def _generate_reports(folder, warehouses, prefix=""):
    paths = {}
    for wh in warehouses:
        rows = _get_stock_rows(wh)
        label = f"{prefix}{wh}" if prefix else wh
        path = _write_excel(folder, label, rows)
        paths[wh] = path
        _log(f"[glow_empire_take] Wrote {len(rows)} rows for {wh} -> {path}")
    return paths


# ---------------------------------------------------------------------------
# Stock movement
# ---------------------------------------------------------------------------

def _get_company_for_warehouse(warehouse):
    return frappe.db.get_value("Warehouse", warehouse, "company")


def _transfer_warehouse_to_shop(source_warehouse):
    """Material Transfer of all positive stock from source -> TARGET_WAREHOUSE."""
    rows = _get_stock_rows(source_warehouse)
    rows = [r for r in rows if flt(r.get("qty")) > 0]
    if not rows:
        _log(f"[glow_empire_take] Nothing to transfer from {source_warehouse}")
        return None

    # Filter out disabled / end-of-life items so Stock Entry validation passes
    active_rows = []
    for r in rows:
        item = frappe.db.get_value(
            "Item", r["item_code"], ["disabled", "end_of_life"], as_dict=True
        )
        if not item:
            _log(f"[glow_empire_take] Skipping unknown item {r['item_code']}")
            continue
        if item.disabled:
            _log(f"[glow_empire_take] Skipping disabled item {r['item_code']}")
            continue
        if item.end_of_life and item.end_of_life <= getdate(nowdate()):
            _log(f"[glow_empire_take] Skipping end-of-life item {r['item_code']}")
            continue
        active_rows.append(r)

    if not active_rows:
        _log(f"[glow_empire_take] All items from {source_warehouse} are inactive — nothing to transfer")
        return None

    company = _get_company_for_warehouse(source_warehouse) or _get_company_for_warehouse(TARGET_WAREHOUSE)

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.purpose = "Material Transfer"
    se.company = company
    se.from_warehouse = source_warehouse
    se.to_warehouse = TARGET_WAREHOUSE
    se.posting_date = nowdate()
    se.posting_time = nowtime()

    for r in active_rows:
        rate = flt(r.get("valuation_rate"))
        se.append("items", {
            "item_code": r["item_code"],
            "qty": flt(r["qty"]),
            "s_warehouse": source_warehouse,
            "t_warehouse": TARGET_WAREHOUSE,
            "basic_rate": rate,
            "valuation_rate": rate,
            "allow_zero_valuation_rate": 1 if rate == 0 else 0,
        })

    se.insert(ignore_permissions=True)
    se.submit()
    frappe.db.commit()
    _log(f"[glow_empire_take] Submitted Stock Entry {se.name}: {source_warehouse} -> {TARGET_WAREHOUSE}")
    return se.name


def _zero_out_shop_warehouse():
    """Create + submit a Stock Reconciliation that sets every item in the
    Shop warehouse to qty=0."""
    rows = _get_stock_rows(TARGET_WAREHOUSE)
    rows = [r for r in rows if flt(r.get("qty")) != 0]
    if not rows:
        _log(f"[glow_empire_take] {TARGET_WAREHOUSE} is already empty")
        return None

    # Filter out disabled / end-of-life items so Stock Reconciliation validation passes
    active_rows = []
    for r in rows:
        item = frappe.db.get_value(
            "Item", r["item_code"], ["disabled", "end_of_life"], as_dict=True
        )
        if not item:
            _log(f"[glow_empire_take] Skipping unknown item {r['item_code']} in reconciliation")
            continue
        if item.disabled:
            _log(f"[glow_empire_take] Skipping disabled item {r['item_code']} in reconciliation")
            continue
        if item.end_of_life and item.end_of_life <= getdate(nowdate()):
            _log(f"[glow_empire_take] Skipping end-of-life item {r['item_code']} in reconciliation")
            continue
        active_rows.append(r)

    if not active_rows:
        _log(f"[glow_empire_take] {TARGET_WAREHOUSE} has no active items to reconcile")
        return None

    company = _get_company_for_warehouse(TARGET_WAREHOUSE)

    sr = frappe.new_doc("Stock Reconciliation")
    sr.purpose = "Stock Reconciliation"
    sr.company = company
    sr.posting_date = nowdate()
    sr.posting_time = nowtime()

    for r in active_rows:
        sr.append("items", {
            "item_code": r["item_code"],
            "warehouse": TARGET_WAREHOUSE,
            "qty": 0,
            "valuation_rate": flt(r.get("valuation_rate")),
            "allow_zero_valuation_rate": 1 if flt(r.get("valuation_rate")) == 0 else 0,
        })

    sr.insert(ignore_permissions=True)
    sr.submit()
    frappe.db.commit()
    _log(f"[glow_empire_take] Submitted Stock Reconciliation {sr.name} (zeroed {TARGET_WAREHOUSE})")
    return sr.name


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

@frappe.whitelist()
def run_stock_take():
    """Full workflow: pre-reports -> transfers -> post-report -> zero-out."""
    folder = _ensure_output_dir()
    summary = {"folder": folder, "files": [], "stock_entries": [], "stock_reconciliation": None}

    # 1. Pre-transfer reports for all 3 warehouses
    pre = _generate_reports(folder, ALL_WAREHOUSES, prefix="01_BEFORE_")
    summary["files"].extend(pre.values())

    # 2. Transfer Main + Damages -> Shop
    for wh in SOURCE_WAREHOUSES:
        name = _transfer_warehouse_to_shop(wh)
        if name:
            summary["stock_entries"].append(name)

    # 3. Post-transfer report for Shop only
    post = _generate_reports(folder, [TARGET_WAREHOUSE], prefix="02_AFTER_TRANSFER_")
    summary["files"].extend(post.values())

    # 4. Zero out Shop warehouse via Stock Reconciliation
    # sr_name = _zero_out_shop_warehouse()
    # summary["stock_reconciliation"] = sr_name

    # 5. Final (zeroed) report for record
    # final = _generate_reports(folder, [TARGET_WAREHOUSE], prefix="03_AFTER_RECONCILIATION_")
    # summary["files"].extend(final.values())

    _log(f"[glow_empire_take] DONE: {summary}")
    print("\n=== Glow Empire Stock Take Complete ===")
    print(f"Folder: {folder}")
    # for f in summary["files"]:
    #     print(f"  - {f}")
    print(f"Stock Entries: {summary['stock_entries']}")
    # print(f"Stock Reconciliation: {summary['stock_reconciliation']}")
    return summary


@frappe.whitelist()
def generate_reports_only():
    """Just generate the Excel reports for all 3 warehouses (no movement)."""
    folder = _ensure_output_dir()
    paths = _generate_reports(folder, ALL_WAREHOUSES)
    print(f"\nReports written to: {folder}")
    for p in paths.values():
        print(f"  - {p}")
    return {"folder": folder, "files": list(paths.values())}


@frappe.whitelist()
def auto_zero():
    folder = _ensure_output_dir()
    summary = {"folder": folder, "files": [], "stock_entries": [], "stock_reconciliation": None}
    
    # 4. Zero out Shop warehouse via Stock Reconciliation
    sr_name = _zero_out_shop_warehouse()
    summary["stock_reconciliation"] = sr_name

    # 5. Final (zeroed) report for record
    final = _generate_reports(folder, [TARGET_WAREHOUSE], prefix="03_AFTER_ZEROING_")
    summary["files"].extend(final.values())

    _log(f"[glow_empire_take] DONE: {summary}")
    print("\n=== Glow Empire Stock Take Complete ===")
    print(f"Folder: {folder}")
    for f in summary["files"]:
        print(f"  - {f}")
    print(f"Stock Entries: {summary['stock_entries']}")
    print(f"Stock Reconciliation: {summary['stock_reconciliation']}")
    return summary

