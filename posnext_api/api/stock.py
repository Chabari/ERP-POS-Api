import frappe
from frappe import _
from frappe.utils import getdate, cint


@frappe.whitelist()
def get_purchase_receipts(warehouse=None, start_date=None, end_date=None):
    """Return Purchase Receipts (Stock Received)."""
    filters = {"docstatus": 1}
    if warehouse:
        # Match receipts by header set_warehouse OR by item-level warehouse
        header_matches = set(frappe.get_all(
            "Purchase Receipt",
            filters={"docstatus": 1, "set_warehouse": warehouse},
            pluck="name",
        ))
        item_matches = set(frappe.get_all(
            "Purchase Receipt Item",
            filters={"warehouse": warehouse, "docstatus": 1},
            pluck="parent",
        ))
        matching_names = list(header_matches | item_matches)
        if not matching_names:
            return []
        filters["name"] = ["in", matching_names]
    if start_date and end_date:
        filters["posting_date"] = [
            "between",
            [getdate(start_date), getdate(end_date)],
        ]

    receipts = frappe.get_all(
        "Purchase Receipt",
        filters=filters,
        fields=[
            "name",
            "supplier",
            "supplier_name",
            "set_warehouse",
            "grand_total",
            "posting_date",
            "docstatus",
            "creation",
            "modified",
        ],
        order_by="posting_date desc",
        limit_page_length=100,
    )

    for pr in receipts:
        pr["items"] = frappe.get_all(
            "Purchase Receipt Item",
            filters={"parent": pr.name},
            fields=["item_code", "item_name", "qty", "rate", "amount", "warehouse"],
        )

    return receipts


@frappe.whitelist()
def get_stock_transfers(warehouse=None, start_date=None, end_date=None):
    """Return Stock Entries of type Material Transfer."""
    filters = {"docstatus": 1, "stock_entry_type": "Material Transfer"}
    if start_date and end_date:
        filters["posting_date"] = [
            "between",
            [getdate(start_date), getdate(end_date)],
        ]

    entries = frappe.get_all(
        "Stock Entry",
        filters=filters,
        fields=[
            "name",
            "stock_entry_type",
            "posting_date",
            "from_warehouse",
            "to_warehouse",
            "total_amount",
            "docstatus",
            "creation",
            "modified",
        ],
        order_by="posting_date desc",
        limit_page_length=100,
    )

    # Filter by warehouse (source or destination)
    if warehouse:
        entries = [
            e
            for e in entries
            if e.from_warehouse == warehouse or e.to_warehouse == warehouse
        ]

    for se in entries:
        se["items"] = frappe.get_all(
            "Stock Entry Detail",
            filters={"parent": se.name},
            fields=[
                "item_code",
                "item_name",
                "qty",
                "s_warehouse",
                "t_warehouse",
                "amount",
            ],
        )

    return entries


@frappe.whitelist()
def get_stock_reconciliation(warehouse=None, start_date=None, end_date=None):
    """Return Stock Reconciliation entries (Stock Take)."""
    filters = {"docstatus": 1}
    if start_date and end_date:
        filters["posting_date"] = [
            "between",
            [getdate(start_date), getdate(end_date)],
        ]

    reconciliations = frappe.get_all(
        "Stock Reconciliation",
        filters=filters,
        fields=[
            "name",
            "posting_date",
            "purpose",
            "docstatus",
            "creation",
            "modified",
        ],
        order_by="posting_date desc",
        limit_page_length=100,
    )

    for sr in reconciliations:
        items = frappe.get_all(
            "Stock Reconciliation Item",
            filters={"parent": sr.name},
            fields=[
                "item_code",
                "item_name",
                "warehouse",
                "qty",
                "valuation_rate",
                "current_qty",
                "amount",
            ],
        )
        # Filter by warehouse
        if warehouse:
            items = [i for i in items if i.warehouse == warehouse]
        sr["items"] = items

    return reconciliations


# =============================================================================
# Create Stock Entry (Material Transfer)
# =============================================================================
@frappe.whitelist()
def create_stock_transfer(from_warehouse=None, to_warehouse=None, items=None, remarks=None):
    """Create a Stock Entry of type Material Transfer."""
    import json as _json

    if not from_warehouse or not to_warehouse:
        frappe.throw(_("Source and destination warehouses are required"))

    if isinstance(items, str):
        items = _json.loads(items)

    if not items or len(items) == 0:
        frappe.throw(_("At least one item is required"))

    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.from_warehouse = from_warehouse
    se.to_warehouse = to_warehouse
    if remarks:
        se.remarks = remarks

    for item in items:
        se.append("items", {
            "item_code": item.get("item_code"),
            "qty": item.get("qty", 0),
            "s_warehouse": from_warehouse,
            "t_warehouse": to_warehouse,
        })

    se.insert()
    se.submit()

    return {
        "name": se.name,
        "status": "Submitted",
        "message": _("Stock Transfer {0} created successfully").format(se.name),
    }


# =============================================================================
# Create Stock Reconciliation
# =============================================================================
@frappe.whitelist()
def create_stock_reconciliation(warehouse=None, items=None, posting_date=None, purpose=None):
    """Create a Stock Reconciliation entry."""
    import json as _json

    if not warehouse:
        frappe.throw(_("Warehouse is required"))

    if isinstance(items, str):
        items = _json.loads(items)

    if not items or len(items) == 0:
        frappe.throw(_("At least one item is required"))

    sr = frappe.new_doc("Stock Reconciliation")
    sr.purpose = purpose or "Stock Reconciliation"
    if posting_date:
        sr.posting_date = getdate(posting_date)
    sr.set_warehouse = warehouse

    for item in items:
        sr.append("items", {
            "item_code": item.get("item_code"),
            "warehouse": warehouse,
            "qty": item.get("qty", 0),
            "valuation_rate": item.get("valuation_rate", 0),
        })

    sr.insert()
    sr.submit()

    return {
        "name": sr.name,
        "status": "Submitted",
        "message": _("Stock Reconciliation {0} created successfully").format(sr.name),
    }


# =============================================================================
# Create Purchase Receipt
# =============================================================================
@frappe.whitelist()
def create_purchase_receipt(supplier=None, warehouse=None, items=None, posting_date=None):
    """Create a Purchase Receipt (Stock Received)."""
    import json as _json

    if not supplier:
        frappe.throw(_("Supplier is required"))

    if not warehouse:
        frappe.throw(_("Warehouse is required"))

    if isinstance(items, str):
        items = _json.loads(items)

    if not items or len(items) == 0:
        frappe.throw(_("At least one item is required"))

    pr = frappe.new_doc("Purchase Receipt")
    pr.supplier = supplier
    pr.set_warehouse = warehouse
    if posting_date:
        pr.posting_date = getdate(posting_date)

    for item in items:
        pr.append("items", {
            "item_code": item.get("item_code"),
            "qty": item.get("qty", 0),
            "rate": item.get("rate", 0),
            "warehouse": warehouse,
        })

    pr.insert()
    pr.submit()

    return {
        "name": pr.name,
        "status": "Submitted",
        "message": _("Purchase Receipt {0} created successfully").format(pr.name),
    }


@frappe.whitelist()
def get_warehouse_items(warehouse=None, search=None):
    """Get items with current stock for a warehouse (for reconciliation/transfer forms)."""
    if not warehouse:
        return []

    filters = {"warehouse": warehouse, "actual_qty": [">", 0]}

    bins = frappe.get_all(
        "Bin",
        filters=filters,
        fields=["item_code", "actual_qty", "valuation_rate", "stock_value"],
        order_by="item_code",
        limit_page_length=0,
    )

    item_codes = [b.item_code for b in bins]
    if not item_codes:
        return []

    # Get item names
    item_names = {}
    for i in frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "item_name"]):
        item_names[i.name] = i.item_name

    if search:
        search_lower = search.lower()
        bins = [
            b for b in bins
            if search_lower in b.item_code.lower()
            or search_lower in (item_names.get(b.item_code, "")).lower()
        ]

    result = []
    for b in bins:
        result.append({
            "item_code": b.item_code,
            "item_name": item_names.get(b.item_code, b.item_code),
            "actual_qty": b.actual_qty,
            "valuation_rate": b.valuation_rate,
            "stock_value": b.stock_value,
        })

    return result


@frappe.whitelist()
def get_stock_items(warehouse=None, search=None, page=None, page_size=None):
    """Get all is_stock_item items with optional warehouse stock info, paginated."""
    page = cint(page) or 1
    page_size = cint(page_size) or 50
    start = (page - 1) * page_size

    filters = {"is_stock_item": 1, "disabled": 0}
    or_filters = {}
    if search:
        or_filters = {"item_code": ["like", f"%{search}%"], "item_name": ["like", f"%{search}%"]}

    total = frappe.db.count("Item", filters=filters) if not search else \
        len(frappe.get_all("Item", filters=filters, or_filters=or_filters, fields=["name"], limit_page_length=0))

    items = frappe.get_all(
        "Item",
        filters=filters,
        or_filters=or_filters if search else None,
        fields=["name as item_code", "item_name"],
        order_by="item_name",
        limit_start=start,
        limit_page_length=page_size,
    )

    # Attach warehouse stock info if warehouse provided
    if warehouse and items:
        item_codes = [i["item_code"] for i in items]
        bins = frappe.get_all(
            "Bin",
            filters={"warehouse": warehouse, "item_code": ["in", item_codes]},
            fields=["item_code", "actual_qty", "valuation_rate"],
        )
        bin_map = {b.item_code: b for b in bins}
        for item in items:
            b = bin_map.get(item["item_code"])
            item["actual_qty"] = b.actual_qty if b else 0
            item["valuation_rate"] = b.valuation_rate if b else 0
    else:
        for item in items:
            item["actual_qty"] = 0
            item["valuation_rate"] = 0

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (start + page_size) < total,
    }
