import frappe
from frappe import _
from frappe.utils import getdate, flt, nowdate, nowtime, get_fullname
import json as _json

from posnext_api.api.sales import _get_pos_profile_for_warehouse


def _get_open_shift(warehouse):
    """Return the open POS Opening Shift name for the current warehouse."""
    pos_profile = _get_pos_profile_for_warehouse(warehouse)
    if not pos_profile:
        return None

    user = frappe.session.user
    shift = frappe.db.get_value(
        "POS Opening Shift",
        {"user": user, "docstatus": 1, "pos_profile": pos_profile,
         "status": "Open"},
        "name",
    )
    if shift:
        return shift

    # Check applicable users
    users = frappe.get_all(
        "POS Profile User",
        filters={"parent": pos_profile, "parenttype": "POS Profile"},
        fields=["user"],
    )
    applicable = [u["user"] for u in users]
    if applicable:
        shift = frappe.db.get_value(
            "POS Opening Shift",
            {"user": ["in", applicable], "docstatus": 1,
             "pos_profile": pos_profile, "status": "Open"},
            "name",
        )
    return shift


def _get_shift_invoices(shift_id):
    """Return submitted Sales Invoices linked to a POS Opening Shift."""
    return frappe.get_all(
        "Sales Invoice",
        filters={
            "posa_pos_opening_shift": shift_id,
            "docstatus": 1,
            "is_pos": 1,
        },
        fields=[
            "name", "customer_name", "grand_total", "paid_amount",
            "outstanding_amount", "owner", "posting_date", "creation",
            "is_return", "return_against", "status",
        ],
        order_by="creation asc",
    )


@frappe.whitelist()
def get_shift_data(shift_id=None, warehouse=None):
    """Return aggregated shift summary: totals, payment methods,
    sale items, users, and shift object."""
    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id:
        return {"success": "0", "message": "No open shift found"}

    shift_doc = frappe.get_doc("POS Opening Shift", shift_id)
    invoices = _get_shift_invoices(shift_id)

    # Totals
    total_sales = 0.0
    total_refunds = 0.0
    total_payments = 0.0
    credit_sales = 0.0
    payment_map = {}   # mode_of_payment -> total
    user_map = {}      # owner -> {total_sales, total_paid}
    item_map = {}      # item_code -> {name, total_amount, total_quantity, image, barcode}

    for inv in invoices:
        gt = flt(inv.grand_total)
        paid = flt(inv.paid_amount)
        outstanding = flt(inv.outstanding_amount)

        if inv.is_return:
            total_refunds += abs(gt)
        else:
            total_sales += gt
            total_payments += paid
            if outstanding > 0:
                credit_sales += outstanding

        # Payment breakdown
        payments = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": inv.name},
            fields=["mode_of_payment", "amount"],
        )
        for p in payments:
            mode = p.mode_of_payment or "Cash"
            payment_map[mode] = flt(payment_map.get(mode, 0)) + flt(p.amount)

        # User breakdown
        owner = inv.owner
        if owner not in user_map:
            user_map[owner] = {"total_sales": 0, "total_paid": 0}
        if not inv.is_return:
            user_map[owner]["total_sales"] += gt
            user_map[owner]["total_paid"] += paid

        # Item breakdown
        items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name},
            fields=["item_code", "item_name", "qty", "amount", "image"],
        )
        for itm in items:
            code = itm.item_code
            if code not in item_map:
                item_doc = frappe.get_cached_doc("Item", code)
                item_map[code] = {
                    "name": itm.item_name,
                    "total_amount": 0,
                    "total_quantity": 0,
                    "image": itm.image or item_doc.image or "none",
                    "barcode": (item_doc.barcodes[0].barcode
                                if item_doc.barcodes else "none"),
                }
            qty = flt(itm.qty)
            amt = flt(itm.amount)
            if inv.is_return:
                qty = -abs(qty)
                amt = -abs(amt)
            item_map[code]["total_quantity"] += qty
            item_map[code]["total_amount"] += amt

    # Build payment methods list from POS Profile balance details
    payment_methods = []
    for bd in shift_doc.balance_details:
        mode = bd.mode_of_payment
        payment_methods.append({
            "id": bd.idx,
            "name": mode,
            "total": str(flt(payment_map.get(mode, 0))),
            "warehouse": shift_doc.pos_profile,
            "warehouse_name": shift_doc.pos_profile,
            "isActive": 1,
            "can_receive": 1,
            "can_pay": 1,
            "has_website": 0,
            "has_mpesa": 1 if "mpesa" in mode.lower() else 0,
            "ledger_account": mode,
            "account_type": mode,
            "ledger_id": mode,
        })

    # Build sale items list
    sale_items = []
    for code, data in item_map.items():
        sale_items.append({
            "name": data["name"],
            "total_amount": str(round(data["total_amount"], 2)),
            "total_quantity": str(round(data["total_quantity"], 2)),
            "image": data["image"],
            "barcode": data["barcode"],
        })

    # Build users list
    users_list = []
    for owner, data in user_map.items():
        users_list.append({
            "full_name": get_fullname(owner),
            "user_id": owner,
            "total_sales": str(round(data["total_sales"], 2)),
            "total_paid": str(round(data["total_paid"], 2)),
        })

    # Build shift object
    shift_obj = {
        "id": shift_id,
        "warehouse_name": shift_doc.pos_profile,
        "isOpen": 1 if shift_doc.status == "Open" else 0,
        "shift_by": get_fullname(shift_doc.user),
        "opening_date": str(shift_doc.posting_date),
        "closing_date": "",
        "closing_time": "",
        "opening_time": str(shift_doc.creation.time()) if shift_doc.creation else "",
        "excess_shot": "0",
        "status": shift_doc.status,
        "isButchery": 0,
        "opening_amount": str(sum(
            flt(bd.amount) for bd in shift_doc.balance_details
        )),
        "closing_amount": "0",
    }

    return {
        "totalpayments": round(total_payments, 2),
        "totalsales": round(total_sales, 2),
        "totalrefunds": round(total_refunds, 2),
        "creditsales": round(credit_sales, 2),
        "paymentmethods": payment_methods,
        "saleitems": sale_items,
        "users": users_list,
        "shift": shift_obj,
    }


@frappe.whitelist()
def get_shift_closing_data(shift_id=None, warehouse=None):
    """Return opening balance entries for the close-shift dialog.
    Maps POS Opening Shift balance_details to the format the Flutter app expects."""
    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id:
        return []

    shift_doc = frappe.get_doc("POS Opening Shift", shift_id)
    invoices = _get_shift_invoices(shift_id)

    # Calculate expected balance per payment mode from invoices
    payment_totals = {}
    for inv in invoices:
        payments = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": inv.name},
            fields=["mode_of_payment", "amount"],
        )
        for p in payments:
            mode = p.mode_of_payment or "Cash"
            payment_totals[mode] = flt(payment_totals.get(mode, 0)) + flt(p.amount)

    result = []
    for bd in shift_doc.balance_details:
        mode = bd.mode_of_payment
        opening = flt(bd.amount)
        expected = flt(payment_totals.get(mode, 0))
        result.append({
            "id": bd.idx,
            "shift_id": shift_id,
            "opening_balance": str(opening),
            "closing_balance": "0",
            "difference": "0",
            "expected_balance": str(round(expected, 2)),
            "mode_of_payment": mode,
            "expected_amount": str(round(expected + opening, 2)),
        })

    return result


@frappe.whitelist()
def get_shift_closing_items(shift_id=None, is_close=False, warehouse=None):
    """Return closing shift items (butchery stock snapshot).
    ERPNext does not natively track butchery items in shifts, so return
    empty list. The Flutter app handles this gracefully."""
    return []


@frappe.whitelist()
def get_user_sales_per_shift(shift_id=None, user_id=None, warehouse=None):
    """Return items sold by a specific user within a shift."""
    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id or not user_id:
        return []

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "posa_pos_opening_shift": shift_id,
            "docstatus": 1,
            "is_pos": 1,
            "owner": user_id,
        },
        fields=["name", "customer_name", "grand_total", "paid_amount",
                "posting_date", "creation", "is_return", "status"],
        order_by="creation asc",
    )

    result = []
    for inv in invoices:
        items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name},
            fields=["item_code", "item_name", "qty", "rate", "amount"],
        )
        for itm in items:
            qty_returned = 0
            if not inv.is_return:
                # Check if there's a return against this invoice
                returns = frappe.get_all(
                    "Sales Invoice",
                    filters={
                        "return_against": inv.name,
                        "docstatus": 1,
                    },
                    fields=["name"],
                )
                for ret in returns:
                    ret_qty = frappe.db.get_value(
                        "Sales Invoice Item",
                        {"parent": ret.name, "item_code": itm.item_code},
                        "qty",
                    )
                    if ret_qty:
                        qty_returned += abs(flt(ret_qty))

            result.append({
                "cashier_name": get_fullname(inv.owner),
                "name": itm.item_name,
                "weight": "0",
                "quantity": str(flt(itm.qty)),
                "sale_date": str(inv.posting_date),
                "created_at": str(inv.creation),
                "barcode": "",
                "quantity_returned": str(qty_returned),
                "amount": str(flt(itm.rate)),
                "customer_name": inv.customer_name or "Walk-in",
                "total_amount": str(flt(itm.amount)),
                "isPaid": 1 if flt(inv.paid_amount) >= flt(inv.grand_total) else 0,
                "order_number": inv.name,
            })

    return result


@frappe.whitelist()
def close_shift(shift_id=None, warehouse=None, closing_time=None,
                items=None, total_sales=0, **kwargs):
    """Close the POS Opening Shift by creating a POS Closing Shift document.
    This uses ERPNext's native POS Closing Shift doctype."""
    if isinstance(items, str):
        items = _json.loads(items)

    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id:
        return {"success": "0", "message": "No open shift found"}

    shift_doc = frappe.get_doc("POS Opening Shift", shift_id)
    pos_profile = shift_doc.pos_profile
    user = shift_doc.user

    # Gather all submitted POS invoices for this shift
    invoices = _get_shift_invoices(shift_id)

    # Calculate payment totals from invoices
    payment_totals = {}
    grand_total = 0.0
    net_total = 0.0
    total_qty = 0.0
    taxes_total = 0.0

    for inv in invoices:
        inv_doc = frappe.get_cached_doc("Sales Invoice", inv.name)
        grand_total += flt(inv_doc.grand_total)
        net_total += flt(inv_doc.net_total)
        total_qty += sum(flt(d.qty) for d in inv_doc.items)
        taxes_total += flt(inv_doc.total_taxes_and_charges)

        for p in inv_doc.payments:
            mode = p.mode_of_payment
            payment_totals[mode] = flt(payment_totals.get(mode, 0)) + flt(p.amount)

    # Build payment_reconciliation from shift balance_details + actual payments
    payment_reconciliation = []
    for bd in shift_doc.balance_details:
        mode = bd.mode_of_payment
        opening = flt(bd.amount)
        expected = flt(payment_totals.get(mode, 0))

        # Use client-provided closing amounts if available
        closing_amount = expected + opening
        difference = 0.0
        if items:
            for itm in items:
                bal_id = itm.get("bal_id")
                if str(bal_id) == str(bd.idx):
                    closing_amount = flt(itm.get("closing", closing_amount))
                    difference = flt(itm.get("difference", 0))
                    break

        payment_reconciliation.append({
            "mode_of_payment": mode,
            "opening_amount": opening,
            "expected_amount": expected + opening,
            "closing_amount": closing_amount,
            "difference": difference,
        })

    # Build POS transactions child table
    pos_transactions = []
    for inv in invoices:
        pos_transactions.append({
            "sales_invoice": inv.name,
            "posting_date": str(inv.posting_date),
            "grand_total": flt(inv.grand_total),
            "customer": inv.customer_name,
        })

    try:
        closing_doc = frappe.get_doc({
            "doctype": "POS Closing Shift",
            "user": user,
            "pos_profile": pos_profile,
            "pos_opening_shift": shift_id,
            "posting_date": getdate(),
            "posting_time": nowtime(),
            "period_start_date": shift_doc.posting_date,
            "period_end_date": getdate(),
            "grand_total": grand_total,
            "net_total": net_total,
            "total_quantity": total_qty,
            "taxes": [],
            "payment_reconciliation": payment_reconciliation,
            "pos_transactions": pos_transactions,
        })
        closing_doc.insert(ignore_permissions=True)
        closing_doc.submit()

        return {"success": "1", "message": "Shift closed successfully",
                "closing_shift": closing_doc.name}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "POS Close Shift Error")
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def get_shift_sales_summary(shift_id=None, warehouse=None):
    """Return a pivot-style summary of shift sales grouped by item."""
    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id:
        return {"summary_data": [], "summary_headers": []}

    invoices = _get_shift_invoices(shift_id)

    # Build summary: Item Name | Qty | Amount | Returns | Net
    item_summary = {}
    for inv in invoices:
        items = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name},
            fields=["item_name", "qty", "amount"],
        )
        for itm in items:
            name = itm.item_name
            if name not in item_summary:
                item_summary[name] = {
                    "qty": 0, "amount": 0, "returns": 0, "return_amount": 0
                }
            if inv.is_return:
                item_summary[name]["returns"] += abs(flt(itm.qty))
                item_summary[name]["return_amount"] += abs(flt(itm.amount))
            else:
                item_summary[name]["qty"] += flt(itm.qty)
                item_summary[name]["amount"] += flt(itm.amount)

    headers = ["Item", "Qty Sold", "Amount", "Qty Returned", "Return Amount", "Net"]
    data = []
    for name, vals in item_summary.items():
        net = vals["amount"] - vals["return_amount"]
        data.append([
            name,
            str(round(vals["qty"], 2)),
            str(round(vals["amount"], 2)),
            str(round(vals["returns"], 2)),
            str(round(vals["return_amount"], 2)),
            str(round(net, 2)),
        ])

    return {"summary_data": data, "summary_headers": headers}


@frappe.whitelist()
def get_all_shift_sales_report(shift_id=None, warehouse=None):
    """Return daily sales detail for a shift (all invoices with key fields)."""
    if not shift_id:
        shift_id = _get_open_shift(warehouse)
    if not shift_id:
        return []

    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "posa_pos_opening_shift": shift_id,
            "docstatus": 1,
            "is_pos": 1,
        },
        fields=[
            "name", "customer_name", "grand_total", "paid_amount",
            "owner", "posting_date", "creation",
        ],
        order_by="creation asc",
    )

    result = []
    for inv in invoices:
        result.append({
            "amount_paid": str(flt(inv.paid_amount)),
            "order_number": inv.name,
            "cashier": get_fullname(inv.owner),
            "sale_date": str(inv.creation),
            "name": inv.customer_name or "Walk-in",
            "total_amount": str(flt(inv.grand_total)),
            "saleId": inv.name,
        })

    return result
