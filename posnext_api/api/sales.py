import frappe
from frappe import _
from frappe.utils import getdate, flt, nowdate, nowtime
import json as _json


@frappe.whitelist()
def get_receipts(warehouse=None, start_date=None, end_date=None):
    """Return Sales Invoices as receipts for the Receipts screen."""
    filters = {"docstatus": ["in", [0, 1, 2]]}

    if warehouse:
        filters["set_warehouse"] = warehouse
    if start_date:
        filters["posting_date"] = [">=", getdate(start_date)]
    if end_date:
        if "posting_date" in filters:
            filters["posting_date"] = [
                "between",
                [getdate(start_date), getdate(end_date)],
            ]
        else:
            filters["posting_date"] = ["<=", getdate(end_date)]

    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name",
            "customer",
            "customer_name",
            "owner",
            "set_warehouse",
            "grand_total",
            "paid_amount",
            "outstanding_amount",
            "total_taxes_and_charges",
            "is_pos",
            "status",
            "docstatus",
            "posting_date",
            "creation",
            "modified",
            "pos_closing_entry",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=100,
    )

    for inv in invoices:
        # Fetch items
        inv["items"] = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name},
            fields=[
                "name",
                "item_code",
                "item_name",
                "qty",
                "rate",
                "amount",
                "uom",
                "net_amount",
            ],
        )

        # Fetch payments
        inv["payments"] = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": inv.name},
            fields=["name", "mode_of_payment", "amount"],
        )

    return invoices


@frappe.whitelist()
def get_bills(warehouse=None, shift_id=None):
    """Return unpaid or partially-paid POS Sales Invoices for a shift."""
    filters = {
        "docstatus": 0,  # Draft invoices only (not yet fully paid/submitted)
        "is_pos": 1,
    }

    if warehouse:
        filters["set_warehouse"] = warehouse
    if shift_id and shift_id != "none":
        filters["posa_pos_opening_shift"] = shift_id

    invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name",
            "customer",
            "customer_name",
            "owner",
            "set_warehouse",
            "grand_total",
            "paid_amount",
            "outstanding_amount",
            "total_taxes_and_charges",
            "is_pos",
            "status",
            "docstatus",
            "posting_date",
            "creation",
            "modified",
            "posa_pos_opening_shift",
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=100,
    )

    for inv in invoices:
        inv["items"] = frappe.get_all(
            "Sales Invoice Item",
            filters={"parent": inv.name},
            fields=[
                "name",
                "item_code",
                "item_name",
                "qty",
                "rate",
                "amount",
                "uom",
                "net_amount",
            ],
        )
        inv["payments"] = frappe.get_all(
            "Sales Invoice Payment",
            filters={"parent": inv.name},
            fields=["name", "mode_of_payment", "amount"],
        )

    return invoices


def _get_pos_profile_for_warehouse(warehouse=None):
    """Find the POS Profile linked to the given warehouse (or first active)."""
    if warehouse:
        profile_name = frappe.db.get_value(
            "POS Profile", {"disabled": 0, "warehouse": warehouse}, "name"
        )
        if profile_name:
            return profile_name
    # fallback to first active POS Profile
    return frappe.db.get_value("POS Profile", {"disabled": 0}, "name")


def _get_applicable_users(pos_profile):
    """Return the list of users from POS Profile's Applicable for Users table."""
    if not pos_profile:
        return []
    users = frappe.get_all(
        "POS Profile User",
        filters={"parent": pos_profile, "parenttype": "POS Profile"},
        fields=["user"],
    )
    return [u["user"] for u in users]


@frappe.whitelist()
def check_shift(warehouse=None):
    """Check if there is an open POS Opening Shift for the current user
    (or any applicable user) linked to the POS Profile of the selected
    warehouse."""
    user = frappe.session.user
    pos_profile = _get_pos_profile_for_warehouse(warehouse)
    if not pos_profile:
        return {"success": "0", "message": "No active POS Profile found"}

    # 1. Check for an open shift created by the current user
    open_entry = frappe.db.get_value(
        "POS Opening Shift",
        {"user": user, "docstatus": 1, "pos_profile": pos_profile,
         "status": "Open"},
        ["name"],
    )
    if open_entry:
        customer = frappe.db.get_value(
            "POS Opening Shift",
            {"name": open_entry},
            ["customer"],
        )
        return {"success": "1", "shift": open_entry, "customer": customer, "message": "Shift found"}

    # 2. Check for an open shift created by any other applicable user
    applicable_users = _get_applicable_users(pos_profile)
    if applicable_users:
        shared_entry = frappe.db.get_value(
            "POS Opening Shift",
            {"user": ["in", applicable_users], "docstatus": 1,
             "pos_profile": pos_profile, "status": "Open"},
            ["name"],
        )
        if shared_entry:
            customer = frappe.db.get_value(
                "POS Opening Shift",
                {"name": shared_entry},
                ["customer"],
            )
            return {"success": "1", "shift": shared_entry, "customer": customer,
                    "message": "Shift found"}

    # 3. Check if there is an unreconciled POS Closing Shift (by user or
    #    any applicable user)
    closing = frappe.db.get_value(
        "POS Closing Shift",
        {"user": user, "docstatus": 0, "pos_profile": pos_profile},
        ["name"],
    )
    if closing:
        return {"success": "2", "shift": closing, "message": "Unreconciled shift"}

    if applicable_users:
        shared_closing = frappe.db.get_value(
            "POS Closing Shift",
            {"user": ["in", applicable_users], "docstatus": 0,
             "pos_profile": pos_profile},
            ["name"],
        )
        if shared_closing:
            return {"success": "2", "shift": shared_closing,
                    "message": "Unreconciled shift"}

    return {"success": "0", "message": "No open shift"}


@frappe.whitelist()
def open_shift(warehouse=None, items=None, opening_amount="0",
               isButchery=False, stockItems=None, opening_time=None):
    """Create a new POS Opening Shift for the warehouse's POS Profile."""
    if isinstance(items, str):
        items = _json.loads(items)

    user = frappe.session.user
    pos_profile = _get_pos_profile_for_warehouse(warehouse)
    if not pos_profile:
        return {"success": "0", "message": "No active POS Profile found"}

    # Check if already open (by current user or any applicable user)
    existing = frappe.db.get_value(
        "POS Opening Shift",
        {"user": user, "docstatus": 1, "pos_profile": pos_profile,
         "status": "Open"},
        ["name"],
    )
    if existing:
        return {"success": "3", "shift": existing, "message": "Shift already open"}

    applicable_users = _get_applicable_users(pos_profile)
    if applicable_users:
        shared_existing = frappe.db.get_value(
            "POS Opening Shift",
            {"user": ["in", applicable_users], "docstatus": 1,
             "pos_profile": pos_profile, "status": "Open"},
            ["name"],
        )
        if shared_existing:
            return {"success": "3", "shift": shared_existing,
                    "message": "Shift already open"}

    # Build balance_details from the POS Profile's payment methods table,
    # using any opening amounts the client sent (matched by mode name).
    client_amounts = {}
    for itm in (items or []):
        mode = itm.get("mode") or ""
        amt = flt(itm.get("amount") or 0)
        if mode:
            client_amounts[mode] = amt

    profile_payments = frappe.get_all(
        "POS Payment Method",
        filters={"parent": pos_profile, "parenttype": "POS Profile"},
        fields=["mode_of_payment"],
    )

    balance_details = []
    for pp in profile_payments:
        mode = pp.get("mode_of_payment")
        balance_details.append({
            "mode_of_payment": mode,
            "amount": client_amounts.get(mode, 0),
        })

    if not balance_details:
        # Fallback if POS Profile has no payment methods configured
        balance_details.append({
            "mode_of_payment": "Cash",
            "amount": flt(opening_amount),
        })

    doc = frappe.get_doc({
        "doctype": "POS Opening Shift",
        "user": user,
        "pos_profile": pos_profile,
        "posting_date": getdate(),
        "period_start_date": frappe.utils.now_datetime(),
        "balance_details": balance_details,
    })
    doc.insert(ignore_permissions=True)
    doc.submit()

    return {"success": "1", "shift": doc.name, "message": "Shift opened"}


@frappe.whitelist()
def create_sale(warehouse=None, items=None, cus_id=None, total=0,
                isPaid=False, amount_paid=0, payment_method="Cash",
                payment_method_one="Cash", payment_method_two="none",
                bill_one_payment="0", bill_two_payment="0",
                bill_one_reference="none", bill_two_reference="none",
                isSplit_bill=False, reference_no="none", action="Direct",
                shift_id="none", cashier_id=None, table_name="none",
                sale_date=None, **kwargs):
    """Create a POS Sales Invoice in ERPNext."""
    if isinstance(items, str):
        items = _json.loads(items)
    if isinstance(isPaid, str):
        isPaid = isPaid.lower() in ("true", "1")
    if isinstance(isSplit_bill, str):
        isSplit_bill = isSplit_bill.lower() in ("true", "1")

    pos_profile = _get_pos_profile_for_warehouse(warehouse)
    if not pos_profile:
        return {"success": "0", "message": "No active POS Profile found"}

    pos_doc = frappe.get_doc("POS Profile", pos_profile)
    company = pos_doc.company

    # Resolve customer
    customer = cus_id
    if not customer or customer == "none":
        customer = pos_doc.customer or frappe.db.get_value(
            "Customer", {"disabled": 0}, "name"
        )

    # Build Sales Invoice
    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "is_pos": 1,
        "pos_profile": pos_profile,
        "customer": customer,
        "company": company,
        "set_warehouse": warehouse,
        "posting_date": getdate(sale_date) if sale_date else getdate(),
        "posting_time": nowtime(),
        "due_date": getdate(sale_date) if sale_date else getdate(),
        "update_stock": 1,
        "posa_pos_opening_shift": shift_id if shift_id and shift_id != "none" else None,
    })

    for itm in (items or []):
        item_code = itm.get("item_code") or itm.get("item_id") or itm.get("item_name")
        qty = flt(itm.get("quantity") or itm.get("qty") or 1)
        rate = flt(itm.get("price") or itm.get("rate") or 0)
        si.append("items", {
            "item_code": item_code,
            "qty": qty,
            "rate": rate,
            "warehouse": warehouse,
        })

    # Payments
    amount_paid = flt(amount_paid)
    total_amt = flt(total) or si.grand_total or 0

    if action == "Credit" or action == "KOT":
        # No payment — save as draft
        si.insert(ignore_permissions=True)
        return _sale_response(si)

    if isSplit_bill:
        b1 = flt(bill_one_payment)
        b2 = flt(bill_two_payment)
        if b1 > 0:
            si.append("payments", {
                "mode_of_payment": payment_method_one or "Cash",
                "amount": b1,
            })
        if b2 > 0 and payment_method_two and payment_method_two != "none":
            si.append("payments", {
                "mode_of_payment": payment_method_two,
                "amount": b2,
            })
    else:
        if amount_paid > 0:
            si.append("payments", {
                "mode_of_payment": payment_method or payment_method_one or "Cash",
                "amount": amount_paid,
            })

    si.insert(ignore_permissions=True)

    # Submit if fully paid
    if isPaid or amount_paid >= total_amt:
        try:
            si.submit()
        except Exception:
            pass  # stay as draft if submission fails

    return _sale_response(si)


def _sale_response(si):
    """Build a standardised success response from a Sales Invoice.
    Field names must match ReceiptList.fromJson expectations exactly."""
    sale = {
        "id": abs(hash(si.name)) % (2**31),
        "order_number": si.name,
        "customer_name": si.customer_name or si.customer,
        "customer_id": si.customer,
        "customer_location": "",
        "cashier_name": frappe.utils.get_fullname(si.owner),
        "cashier_id": si.owner,
        "total_amount": str(flt(si.grand_total)),
        "amount_paid": str(flt(si.paid_amount)),
        "isPaid": 1 if flt(si.paid_amount) >= flt(si.grand_total) else 0,
        "isSubmitted": si.docstatus,
        "isCancelled": 1 if si.docstatus == 2 else 0,
        "isDeleted": 0,
        "is_sent": 1,
        "sync_id": si.name,
        "reference_no": "none",
        "action": "",
        "tax_amount": str(flt(si.total_taxes_and_charges or 0)),
        "sale_type": "POS" if si.is_pos else "Invoice",
        "sale_date": str(si.posting_date),
        "shift": "",
        "shift_id": "",
        "total_items": len(si.items),
        "warehouse_name": si.set_warehouse or "",
        "table_name": "none",
        "kot_status": "",
        "reason_cancelled": "",
        "date_cancelled": "",
        "created_at": str(si.creation),
        "updated_at": str(si.modified),
        "items": [],
        "salepayments": [],
    }
    for item in si.items:
        sale["items"].append({
            "id": abs(hash(item.name)) % (2**31),
            "item_id": item.item_code,
            "item_name": item.item_name,
            "quantity": str(flt(item.qty)),
            "amount": str(flt(item.rate)),
            "total_amount": str(flt(item.amount)),
            "unit_name": item.uom or "",
            "barcode": "",
            "image": "",
            "receipt_id": si.name,
            "sale_id": si.name,
            "tax_amount": "0.0",
            "weight": "0",
            "quantity_available": "0",
            "created_at": str(si.creation),
            "updated_at": str(si.modified),
        })
    for pay in (si.payments or []):
        sale["salepayments"].append({
            "id": abs(hash(pay.name)) % (2**31),
            "payment_method": pay.mode_of_payment or "",
            "amount": str(flt(pay.amount)),
            "sale_id": si.name,
            "warehouse_name": si.set_warehouse or "",
            "shift_id": "",
            "reference": "",
            "user": si.owner or "",
            "receipt_number": si.name,
            "isReturn": 0,
            "created_at": str(si.creation),
            "updated_at": str(si.modified),
        })
    return {"success": "1", "message": "Sale created", "sale": sale}


@frappe.whitelist()
def clear_bill(sale_id=None, amount_paid=0, payment_method="Cash",
               payment_method_one="Cash", payment_method_two="none",
               bill_one_payment="0", bill_two_payment="0",
               isSplit_bill=False, reference="none",
               bill_one_reference="none", bill_two_reference="none", **kwargs):
    """Add payment and submit a Sales Invoice (clear bill)."""
    if not sale_id:
        return {"success": "0", "message": "No sale_id provided"}
    if isinstance(isSplit_bill, str):
        isSplit_bill = isSplit_bill.lower() in ("true", "1")
    try:
        doc = frappe.get_doc("Sales Invoice", sale_id)
        if doc.docstatus == 2:
            return {"success": "0", "message": "Invoice is cancelled"}

        amount_paid = flt(amount_paid)

        # Add payments if not already present
        if doc.docstatus == 0:
            if isSplit_bill:
                b1 = flt(bill_one_payment)
                b2 = flt(bill_two_payment)
                if b1 > 0:
                    doc.append("payments", {
                        "mode_of_payment": payment_method_one or "Cash",
                        "amount": b1,
                    })
                if b2 > 0 and payment_method_two != "none":
                    doc.append("payments", {
                        "mode_of_payment": payment_method_two,
                        "amount": b2,
                    })
            else:
                if amount_paid > 0:
                    doc.append("payments", {
                        "mode_of_payment": payment_method or "Cash",
                        "amount": amount_paid,
                    })
            doc.save(ignore_permissions=True)

        if doc.docstatus == 0:
            doc.submit()

        return {"success": "1", "message": "Bill cleared",
                "sale": _sale_response(doc.reload())["sale"]}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def get_shift_items(shift_id=None, warehouse=None):
    """Return items associated with a shift (butchery stock snapshot)."""
    return []


@frappe.whitelist()
def delete_bill(sale_id=None):
    """Delete a draft Sales Invoice."""
    if not sale_id:
        return {"success": "0", "message": "No sale_id provided"}
    try:
        doc = frappe.get_doc("Sales Invoice", sale_id)
        if doc.docstatus == 0:
            doc.delete()
            return {"success": "1", "message": "Bill deleted"}
        return {"success": "0", "message": "Cannot delete submitted invoice"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def bulk_clear_bill(items=None, date=None):
    """Submit multiple Sales Invoices at once."""
    if isinstance(items, str):
        items = _json.loads(items)
    cleared = 0
    for itm in (items or []):
        sid = itm.get("sale_id")
        if sid:
            try:
                doc = frappe.get_doc("Sales Invoice", sid)
                if doc.docstatus == 0:
                    doc.submit()
                    cleared += 1
            except Exception:
                pass
    return {"success": "1", "message": f"{cleared} bills cleared"}


@frappe.whitelist()
def cancel_bill(sale_id=None, date_cancelled=None, reason_cancelled=None):
    """Cancel a submitted Sales Invoice."""
    if not sale_id:
        return {"success": "0", "message": "No sale_id provided"}
    try:
        doc = frappe.get_doc("Sales Invoice", sale_id)
        if doc.docstatus == 1:
            doc.cancel()
            return {"success": "1", "message": "Bill cancelled"}
        return {"success": "0", "message": "Invoice is not submitted"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def change_to_draft(sale_id=None):
    """Amend a submitted Sales Invoice back to draft."""
    if not sale_id:
        return {"success": "0", "message": "No sale_id provided"}
    try:
        doc = frappe.get_doc("Sales Invoice", sale_id)
        if doc.docstatus == 1:
            amended = frappe.copy_doc(doc)
            amended.amended_from = doc.name
            amended.docstatus = 0
            amended.insert(ignore_permissions=True)
            doc.cancel()
            return {"success": "1", "message": "Changed to draft"}
        return {"success": "0", "message": "Invoice is not submitted"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def get_receipt_items(sale_id=None):
    """Return line items for a specific Sales Invoice."""
    if not sale_id:
        return []
    return frappe.get_all(
        "Sales Invoice Item",
        filters={"parent": sale_id},
        fields=[
            "name", "item_code", "item_name", "qty", "rate",
            "amount", "uom", "net_amount",
        ],
    )


@frappe.whitelist()
def get_edited_items(sale_id=None):
    """Return line items for editing a Sales Invoice."""
    return get_receipt_items(sale_id)


@frappe.whitelist()
def submit_update(sale_id=None, items=None, removed=None, **kwargs):
    """Update line items on a draft Sales Invoice."""
    if isinstance(items, str):
        items = _json.loads(items)
    if isinstance(removed, str):
        removed = _json.loads(removed)
    if not sale_id:
        return {"success": "0", "message": "No sale_id provided"}
    try:
        doc = frappe.get_doc("Sales Invoice", sale_id)
        if doc.docstatus != 0:
            return {"success": "0", "message": "Can only edit draft invoices"}
        # Remove items
        removed_ids = {r.get("item_id") for r in (removed or [])}
        # Update items
        doc.items = []
        for itm in (items or []):
            item_code = itm.get("item_code") or itm.get("item_id")
            if item_code in removed_ids:
                continue
            doc.append("items", {
                "item_code": item_code,
                "qty": flt(itm.get("qty") or itm.get("quantity") or 1),
                "rate": flt(itm.get("rate") or itm.get("price") or 0),
            })
        doc.save(ignore_permissions=True)
        return {"success": "1", "message": "Invoice updated",
                "sale": _sale_response(doc)["sale"]}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def get_payment_modes(warehouse=None):
    """Return available Mode of Payment entries from the POS Profile."""
    pos_profile = _get_pos_profile_for_warehouse(warehouse)
    if not pos_profile:
        return []
    payments = frappe.get_all(
        "POS Payment Method",
        filters={"parent": pos_profile},
        fields=["mode_of_payment as name", "default as is_default"],
    )
    result = []
    for i, p in enumerate(payments):
        result.append({
            "id": i + 1,
            "name": p.get("name"),
            "account_name": p.get("name"),
            "is_default": 1 if p.get("is_default") else 0,
        })
    return result


@frappe.whitelist()
def get_c2b_payments(payment_mode=None, start_date=None, end_date=None):
    """Return M-Pesa C2B payment messages. Stub for ERPNext."""
    return []


@frappe.whitelist()
def initiate_stk_push(payment_mode=None, phone=None, amount=None, ref_id=None):
    """Initiate an M-Pesa STK push. Stub for ERPNext."""
    return {"success": "0", "message": "STK Push not configured for ERPNext"}


@frappe.whitelist()
def load_stk_payments(ref_id=None, action=None):
    """Check STK push payment status. Stub for ERPNext."""
    return {"success": "0", "message": "No payment found"}
