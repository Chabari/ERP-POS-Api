import frappe
from frappe import _
from frappe.utils import getdate, nowdate, flt
from collections import defaultdict


# =============================================================================
# Daily Shift Summary
# =============================================================================
@frappe.whitelist()
def daily_shift_summary(warehouse=None, date=None):
    """Return list of POS Closing Shifts for the day, optionally filtered by warehouse."""
    if not date:
        date = nowdate()

    filters = {"posting_date": getdate(date), "docstatus": 1}

    if warehouse:
        profiles = frappe.get_all(
            "POS Profile",
            filters={"warehouse": warehouse, "disabled": 0},
            pluck="name",
        )
        if profiles:
            filters["pos_profile"] = ["in", profiles]

    shifts = frappe.get_all(
        "POS Closing Shift",
        filters=filters,
        fields=[
            "name", "user", "pos_profile", "posting_date",
            "grand_total", "net_total", "total_quantity",
            "period_start_date", "period_end_date",
        ],
        order_by="posting_date desc, period_start_date desc",
    )

    data = []
    for shift in shifts:
        full_name = frappe.db.get_value("User", shift.user, "full_name") or shift.user
        data.append({
            "name": shift.name,
            "user": shift.user,
            "user_name": full_name,
            "pos_profile": shift.pos_profile,
            "grand_total": flt(shift.grand_total),
            "net_total": flt(shift.net_total),
            "total_quantity": flt(shift.total_quantity),
            "period_start_date": str(shift.period_start_date or ""),
            "period_end_date": str(shift.period_end_date or ""),
        })

    return {"data": data, "total": sum(d["grand_total"] for d in data)}


@frappe.whitelist()
def shift_detail(shift_name=None):
    """Detailed breakdown of a single POS Closing Shift."""
    if not shift_name:
        return {"error": "shift_name is required"}

    shift = frappe.get_doc("POS Closing Shift", shift_name)

    # 1. Payment methods from POS Closing Shift Detail
    payment_methods = []
    for p in shift.payment_reconciliation:
        payment_methods.append({
            "mode_of_payment": p.mode_of_payment,
            "expected_amount": flt(p.expected_amount),
            "closing_amount": flt(p.closing_amount),
            "difference": flt(p.difference),
        })

    # 2. Get all invoice names from this shift
    invoice_names = [t.sales_invoice for t in shift.pos_transactions]
    if not invoice_names:
        return {
            "shift": shift_name,
            "payment_methods": payment_methods,
            "cashiers": [],
            "items": [],
            "invoices": [],
            "customers": [],
        }

    # 3. Cashiers - sales grouped by owner
    cashiers_raw = frappe.db.sql("""
        SELECT owner, COUNT(*) as invoice_count,
               SUM(grand_total) as total, SUM(total_qty) as qty
        FROM `tabSales Invoice`
        WHERE name IN %(invoices)s AND docstatus = 1
        GROUP BY owner
        ORDER BY total DESC
    """, {"invoices": invoice_names}, as_dict=True)

    users = list({c.owner for c in cashiers_raw})
    full_names = {}
    if users:
        for u in frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"]):
            full_names[u.name] = u.full_name

    cashiers = [{
        "user": c.owner,
        "user_name": full_names.get(c.owner, c.owner),
        "invoice_count": int(c.invoice_count),
        "total": flt(c.total),
        "qty": flt(c.qty),
    } for c in cashiers_raw]

    # 4. Items sold - grouped by item
    items = frappe.db.sql("""
        SELECT sii.item_code, sii.item_name, sii.uom,
               SUM(sii.qty) as qty, SUM(sii.amount) as amount
        FROM `tabSales Invoice Item` sii
        WHERE sii.parent IN %(invoices)s
        GROUP BY sii.item_code, sii.item_name, sii.uom
        ORDER BY qty DESC
    """, {"invoices": invoice_names}, as_dict=True)

    items_data = [{
        "item_code": i.item_code,
        "item_name": i.item_name,
        "uom": i.uom or "",
        "qty": flt(i.qty),
        "amount": flt(i.amount),
    } for i in items]

    # 5. Invoices with payment info
    invoices_raw = frappe.db.sql("""
        SELECT si.name, si.customer_name, si.grand_total,
               si.outstanding_amount, si.owner, si.is_return,
               si.posting_date, si.posting_time
        FROM `tabSales Invoice` si
        WHERE si.name IN %(invoices)s AND si.docstatus = 1
        ORDER BY si.posting_time DESC
    """, {"invoices": invoice_names}, as_dict=True)

    # Get payment modes per invoice
    inv_payments = defaultdict(list)
    if invoice_names:
        payments = frappe.db.sql("""
            SELECT parent, mode_of_payment, amount
            FROM `tabSales Invoice Payment`
            WHERE parent IN %(invoices)s
        """, {"invoices": invoice_names}, as_dict=True)
        for p in payments:
            inv_payments[p.parent].append({
                "mode": p.mode_of_payment,
                "amount": flt(p.amount),
            })

    invoices_data = [{
        "name": inv.name,
        "customer_name": inv.customer_name or "",
        "grand_total": flt(inv.grand_total),
        "outstanding_amount": flt(inv.outstanding_amount),
        "is_return": inv.is_return,
        "owner": inv.owner,
        "payments": inv_payments.get(inv.name, []),
    } for inv in invoices_raw]

    # 6. Top customers
    customers_raw = frappe.db.sql("""
        SELECT customer_name, COUNT(*) as invoice_count,
               SUM(grand_total) as total
        FROM `tabSales Invoice`
        WHERE name IN %(invoices)s AND docstatus = 1 AND is_return = 0
        GROUP BY customer
        ORDER BY total DESC
    """, {"invoices": invoice_names}, as_dict=True)

    customers = [{
        "customer_name": c.customer_name,
        "invoice_count": int(c.invoice_count),
        "total": flt(c.total),
    } for c in customers_raw]

    return {
        "shift": shift_name,
        "payment_methods": payment_methods,
        "cashiers": cashiers,
        "items": items_data,
        "invoices": invoices_data,
        "customers": customers,
    }


# =============================================================================
# Daily Sales Summary (warehouse x payment method table)
# =============================================================================
@frappe.whitelist()
def daily_sales_summary(start_date=None, end_date=None):
    """Sales summary table: each row = warehouse, columns = payment methods."""
    if not start_date:
        start_date = nowdate()
    if not end_date:
        end_date = start_date

    # Get all submitted POS invoices in the date range
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "posting_date": ["between", [getdate(start_date), getdate(end_date)]],
            "docstatus": 1,
        },
        fields=["name", "grand_total", "is_return", "is_pos", "outstanding_amount"],
    )

    if not invoices:
        return {"columns": [], "rows": [], "totals": {}}

    inv_names = [inv.name for inv in invoices]

    # Get item-level warehouse info for each invoice
    items = frappe.db.sql("""
        SELECT parent, warehouse, SUM(ABS(amount)) as amount
        FROM `tabSales Invoice Item`
        WHERE parent IN %(invoices)s
        GROUP BY parent, warehouse
    """, {"invoices": inv_names}, as_dict=True)

    # Build per-invoice warehouse shares
    inv_warehouse_shares = defaultdict(dict)
    inv_totals = defaultdict(float)
    for item in items:
        inv_warehouse_shares[item.parent][item.warehouse or "Other"] = flt(item.amount)
        inv_totals[item.parent] += flt(item.amount)

    # Get POS payments
    payments = frappe.db.sql("""
        SELECT parent, mode_of_payment, amount
        FROM `tabSales Invoice Payment`
        WHERE parent IN %(invoices)s
    """, {"invoices": inv_names}, as_dict=True)

    inv_payments = defaultdict(list)
    for p in payments:
        inv_payments[p.parent].append(p)

    # Get Payment Entry payments for non-POS invoices
    pe_refs = frappe.db.sql("""
        SELECT per.reference_name, per.allocated_amount, pe.mode_of_payment
        FROM `tabPayment Entry Reference` per
        JOIN `tabPayment Entry` pe ON pe.name = per.parent
        WHERE per.reference_doctype = 'Sales Invoice'
          AND per.reference_name IN %(invoices)s
          AND pe.docstatus = 1
    """, {"invoices": inv_names}, as_dict=True)

    inv_pe_payments = defaultdict(list)
    for ref in pe_refs:
        inv_pe_payments[ref.reference_name].append(ref)

    # Build: warehouse -> { mode_of_payment: total }
    summary = defaultdict(lambda: defaultdict(float))
    all_modes = set()

    for inv in invoices:
        sign = -1 if inv.is_return else 1
        total_amount = inv_totals.get(inv.name, 0) or 1
        wh_shares = inv_warehouse_shares.get(inv.name, {"Other": 1})

        payment_entries = []
        if inv.is_pos and inv.name in inv_payments:
            for p in inv_payments[inv.name]:
                payment_entries.append((p.mode_of_payment, flt(p.amount)))
        elif inv.name in inv_pe_payments:
            for ref in inv_pe_payments[inv.name]:
                payment_entries.append((ref.mode_of_payment or "Bank", flt(ref.allocated_amount)))
            outstanding = flt(inv.outstanding_amount)
            if outstanding > 0:
                payment_entries.append(("Credit", outstanding))
        else:
            paid = flt(inv.grand_total) - flt(inv.outstanding_amount)
            if paid > 0:
                payment_entries.append(("Cash", paid))
            outstanding = flt(inv.outstanding_amount)
            if outstanding > 0:
                payment_entries.append(("Credit", outstanding))

        for mode, amount in payment_entries:
            all_modes.add(mode)
            for wh, wh_amount in wh_shares.items():
                share = wh_amount / total_amount if total_amount else 0
                summary[wh][mode] += amount * sign * share

    sorted_modes = sorted(all_modes - {"Credit"})
    if "Credit" in all_modes:
        sorted_modes.append("Credit")

    rows = []
    grand_totals = defaultdict(float)
    for wh in sorted(summary.keys()):
        row = {"warehouse": wh}
        row_total = 0
        for mode in sorted_modes:
            val = round(summary[wh].get(mode, 0), 2)
            row[mode] = val
            row_total += val
            grand_totals[mode] += val
        row["total"] = round(row_total, 2)
        grand_totals["total"] += row_total
        rows.append(row)

    totals = {mode: round(grand_totals[mode], 2) for mode in sorted_modes}
    totals["total"] = round(grand_totals["total"], 2)

    return {
        "columns": sorted_modes,
        "rows": rows,
        "totals": totals,
    }


# =============================================================================
# Other reports
# =============================================================================
@frappe.whitelist()
def top_selling_items(
    warehouse=None, start_date=None, end_date=None, limit=10
):
    """Top selling items by quantity sold."""
    limit = int(limit)
    wh_filter = "AND si.set_warehouse = %(warehouse)s" if warehouse else ""

    items = frappe.db.sql(
        """
        SELECT sii.item_name as name, SUM(sii.qty) as quantity,
               SUM(sii.amount) as total
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %(start)s AND %(end)s
          {wh_filter}
        GROUP BY sii.item_code
        ORDER BY quantity DESC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {
            "start": getdate(start_date),
            "end": getdate(end_date),
            "warehouse": warehouse,
            "limit": limit,
        },
        as_dict=True,
    )

    return {
        "data": [
            {"name": i.name, "quantity": float(i.quantity), "total": float(i.total)}
            for i in items
        ]
    }


@frappe.whitelist()
def slow_selling_items(
    warehouse=None, start_date=None, end_date=None, limit=10
):
    """Slow selling items (lowest quantity sold)."""
    limit = int(limit)
    wh_filter = "AND si.set_warehouse = %(warehouse)s" if warehouse else ""

    items = frappe.db.sql(
        """
        SELECT sii.item_name as name, SUM(sii.qty) as quantity,
               SUM(sii.amount) as total
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %(start)s AND %(end)s
          {wh_filter}
        GROUP BY sii.item_code
        ORDER BY quantity ASC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {
            "start": getdate(start_date),
            "end": getdate(end_date),
            "warehouse": warehouse,
            "limit": limit,
        },
        as_dict=True,
    )

    return {
        "data": [
            {"name": i.name, "quantity": float(i.quantity), "total": float(i.total)}
            for i in items
        ]
    }


@frappe.whitelist()
def most_stocked_items(warehouse=None, limit=10):
    """Items with the highest stock levels."""
    limit = int(limit)
    wh_filter = "AND b.warehouse = %(warehouse)s" if warehouse else ""

    items = frappe.db.sql(
        """
        SELECT i.item_name as name, SUM(b.actual_qty) as quantity,
               SUM(b.stock_value) as total
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE i.disabled = 0
          {wh_filter}
        GROUP BY b.item_code
        ORDER BY quantity DESC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {"warehouse": warehouse, "limit": limit},
        as_dict=True,
    )

    return {
        "data": [
            {"name": i.name, "quantity": float(i.quantity), "total": float(i.total)}
            for i in items
        ]
    }


@frappe.whitelist()
def almost_finished_items(warehouse=None, limit=10):
    """Items with low stock (near reorder level)."""
    limit = int(limit)
    wh_filter = "AND b.warehouse = %(warehouse)s" if warehouse else ""

    items = frappe.db.sql(
        """
        SELECT i.item_name as name, SUM(b.actual_qty) as quantity,
               SUM(b.stock_value) as total
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE i.disabled = 0 AND b.actual_qty > 0
          {wh_filter}
        GROUP BY b.item_code
        ORDER BY quantity ASC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {"warehouse": warehouse, "limit": limit},
        as_dict=True,
    )

    return {
        "data": [
            {"name": i.name, "quantity": float(i.quantity), "total": float(i.total)}
            for i in items
        ]
    }


@frappe.whitelist()
def top_customers(
    warehouse=None, start_date=None, end_date=None, limit=10
):
    """Top customers by invoice total."""
    limit = int(limit)
    wh_filter = "AND set_warehouse = %(warehouse)s" if warehouse else ""

    customers = frappe.db.sql(
        """
        SELECT customer_name as name, COUNT(*) as count,
               SUM(grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %(start)s AND %(end)s
          {wh_filter}
        GROUP BY customer
        ORDER BY total DESC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {
            "start": getdate(start_date),
            "end": getdate(end_date),
            "warehouse": warehouse,
            "limit": limit,
        },
        as_dict=True,
    )

    return {
        "data": [
            {"name": c.name, "quantity": float(c.count), "total": float(c.total)}
            for c in customers
        ]
    }


@frappe.whitelist()
def top_cashiers(
    warehouse=None, start_date=None, end_date=None, limit=10
):
    """Top cashiers (owners) by invoice total."""
    limit = int(limit)
    wh_filter = "AND set_warehouse = %(warehouse)s" if warehouse else ""

    cashiers = frappe.db.sql(
        """
        SELECT owner as name, COUNT(*) as count,
               SUM(grand_total) as total
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %(start)s AND %(end)s
          {wh_filter}
        GROUP BY owner
        ORDER BY total DESC
        LIMIT %(limit)s
        """.format(wh_filter=wh_filter),
        {
            "start": getdate(start_date),
            "end": getdate(end_date),
            "warehouse": warehouse,
            "limit": limit,
        },
        as_dict=True,
    )

    return {
        "data": [
            {"name": c.name, "quantity": float(c.count), "total": float(c.total)}
            for c in cashiers
        ]
    }
