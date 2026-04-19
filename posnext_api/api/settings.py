import frappe
from frappe import _
from frappe.utils import flt, cint


# ─── Printers ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_printers():
    """Return all POS Printer records for the current user's context."""
    printers = frappe.get_all(
        "POS Printer",
        fields=[
            "name as id",
            "printer_name",
            "address",
            "port",
            "connection_type as connectionType",
            "printer_size as printerSize",
            "warehouse",
            "is_default as isDefault",
            "printer_warehouse as printerWarehouse",
            "printer_location as printerLocation",
            "printer_email as printerEmail",
            "printer_phone as printerPhone",
        ],
        order_by="modified desc",
    )
    for p in printers:
        p["name"] = p.get("printer_name", "")
    return {"success": "1", "printers": printers}


@frappe.whitelist()
def set_printer(
    printer_name=None,
    address=None,
    port=None,
    connection_type=None,
    printer_size=None,
    warehouse=None,
    is_default=0,
    printer_warehouse=None,
    printer_location=None,
    printer_email=None,
    printer_phone=None,
):
    """Create a new POS Printer."""
    if not printer_name:
        frappe.throw(_("Printer name is required"))

    doc = frappe.new_doc("POS Printer")
    doc.printer_name = printer_name
    doc.address = address or ""
    doc.port = port or "9100"
    doc.connection_type = connection_type or "Network"
    doc.printer_size = printer_size or "80 mm"
    doc.warehouse = warehouse or ""
    doc.is_default = cint(is_default)
    doc.printer_warehouse = printer_warehouse or ""
    doc.printer_location = printer_location or ""
    doc.printer_email = printer_email or ""
    doc.printer_phone = printer_phone or ""
    doc.insert()
    frappe.db.commit()
    return {"success": "1", "message": "Printer added successfully", "id": doc.name}


@frappe.whitelist()
def update_printer(
    id=None,
    printer_name=None,
    address=None,
    port=None,
    connection_type=None,
    printer_size=None,
    warehouse=None,
    is_default=0,
    printer_warehouse=None,
    printer_location=None,
    printer_email=None,
    printer_phone=None,
):
    """Update an existing POS Printer."""
    if not id:
        frappe.throw(_("Printer ID is required"))

    doc = frappe.get_doc("POS Printer", id)
    if printer_name is not None:
        doc.printer_name = printer_name
    if address is not None:
        doc.address = address
    if port is not None:
        doc.port = port
    if connection_type is not None:
        doc.connection_type = connection_type
    if printer_size is not None:
        doc.printer_size = printer_size
    if warehouse is not None:
        doc.warehouse = warehouse
    doc.is_default = cint(is_default)
    if printer_warehouse is not None:
        doc.printer_warehouse = printer_warehouse
    if printer_location is not None:
        doc.printer_location = printer_location
    if printer_email is not None:
        doc.printer_email = printer_email
    if printer_phone is not None:
        doc.printer_phone = printer_phone
    doc.save()
    frappe.db.commit()
    return {"success": "1", "message": "Printer updated successfully"}


@frappe.whitelist()
def delete_printer(id=None):
    """Delete a POS Printer."""
    if not id:
        frappe.throw(_("Printer ID is required"))

    frappe.delete_doc("POS Printer", id, force=True)
    frappe.db.commit()
    return {"success": "1", "message": "Printer deleted successfully"}


@frappe.whitelist()
def get_printer_data(warehouse=None):
    """Get default printer and invoice layout for a warehouse."""
    printer = None
    layout = None

    if warehouse:
        printers = frappe.get_all(
            "POS Printer",
            filters={"warehouse": warehouse},
            fields=[
                "name as id",
                "printer_name",
                "address",
                "port",
                "connection_type as connectionType",
                "printer_size as printerSize",
                "warehouse",
                "is_default as isDefault",
                "printer_warehouse as printerWarehouse",
                "printer_location as printerLocation",
                "printer_email as printerEmail",
                "printer_phone as printerPhone",
            ],
            order_by="is_default desc",
            limit=1,
        )
        if printers:
            printer = printers[0]
            printer["name"] = printer.get("printer_name", "")

        layouts = frappe.get_all(
            "POS Invoice Layout",
            filters={"warehouse": warehouse},
            fields=[
                "name as id",
                "is_default as isDefault",
                "include_kra_pin as includeKraPin",
                "include_receipt_no as includeReceiptNo",
                "include_location as includeLocation",
                "include_warehouse as includeWarehouse",
                "include_landmark as includeLandmark",
                "include_cashier as includeCashier",
                "include_company_logo as includeCompanyLogo",
                "show_email as showEmail",
                "show_phone_number as showPhoneNumber",
                "footer_text as footerText",
                "logo",
                "email",
                "phone",
                "location",
                "landmark",
                "kra",
                "warehouse_name",
                "selected_size",
                "paybill_number",
                "invoice_warehouse",
                "invoice_aging",
            ],
            order_by="is_default desc",
            limit=1,
        )
        if layouts:
            layout = layouts[0]

    return {
        "success": "1",
        "printer": printer,
        "invoicelayout": layout,
    }


# ─── Invoice Layouts ─────────────────────────────────────────────────────────

@frappe.whitelist()
def get_layouts():
    """Return all POS Invoice Layout records."""
    layouts = frappe.get_all(
        "POS Invoice Layout",
        fields=[
            "name as id",
            "is_default as isDefault",
            "include_kra_pin as includeKraPin",
            "include_receipt_no as includeReceiptNo",
            "include_location as includeLocation",
            "include_warehouse as includeWarehouse",
            "include_landmark as includeLandmark",
            "include_cashier as includeCashier",
            "include_company_logo as includeCompanyLogo",
            "show_email as showEmail",
            "show_phone_number as showPhoneNumber",
            "footer_text as footerText",
            "logo",
            "email",
            "phone",
            "location",
            "landmark",
            "kra",
            "warehouse_name",
            "selected_size",
            "paybill_number",
            "invoice_warehouse",
            "invoice_aging",
            "warehouse",
        ],
        order_by="modified desc",
    )
    return {"success": "1", "layouts": layouts}


@frappe.whitelist()
def add_invoice_layout(
    warehouse=None,
    is_default=0,
    include_warehouse=1,
    include_location=1,
    include_kra_pin=0,
    include_landmark=0,
    include_cashier=1,
    include_company_logo=1,
    show_email=1,
    show_phone_number=1,
    include_receipt_no=1,
    selected_size="size2",
    invoice_aging="7",
    footer_text="",
    paybill_number="",
    logo="",
    email="",
    phone="",
    location="",
    landmark="",
    kra="",
    warehouse_name="",
    invoice_warehouse="",
):
    """Create a new POS Invoice Layout."""
    doc = frappe.new_doc("POS Invoice Layout")
    doc.warehouse = warehouse or ""
    doc.is_default = cint(is_default)
    doc.include_warehouse = cint(include_warehouse)
    doc.include_location = cint(include_location)
    doc.include_kra_pin = cint(include_kra_pin)
    doc.include_landmark = cint(include_landmark)
    doc.include_cashier = cint(include_cashier)
    doc.include_company_logo = cint(include_company_logo)
    doc.show_email = cint(show_email)
    doc.show_phone_number = cint(show_phone_number)
    doc.include_receipt_no = cint(include_receipt_no)
    doc.selected_size = selected_size or "size2"
    doc.invoice_aging = invoice_aging or "7"
    doc.footer_text = footer_text or ""
    doc.paybill_number = paybill_number or ""
    doc.logo = logo or ""
    doc.email = email or ""
    doc.phone = phone or ""
    doc.location = location or ""
    doc.landmark = landmark or ""
    doc.kra = kra or ""
    doc.warehouse_name = warehouse_name or ""
    doc.invoice_warehouse = invoice_warehouse or ""
    doc.insert()
    frappe.db.commit()
    return {"success": "1", "message": "Layout added successfully", "id": doc.name}


@frappe.whitelist()
def update_invoice_layout(
    id=None,
    warehouse=None,
    is_default=0,
    include_warehouse=1,
    include_location=1,
    include_kra_pin=0,
    include_landmark=0,
    include_cashier=1,
    include_company_logo=1,
    show_email=1,
    show_phone_number=1,
    include_receipt_no=1,
    selected_size="size2",
    invoice_aging="7",
    footer_text="",
    paybill_number="",
    logo="",
    email="",
    phone="",
    location="",
    landmark="",
    kra="",
    warehouse_name="",
    invoice_warehouse="",
):
    """Update an existing POS Invoice Layout."""
    if not id:
        frappe.throw(_("Layout ID is required"))

    doc = frappe.get_doc("POS Invoice Layout", id)
    if warehouse is not None:
        doc.warehouse = warehouse
    doc.is_default = cint(is_default)
    doc.include_warehouse = cint(include_warehouse)
    doc.include_location = cint(include_location)
    doc.include_kra_pin = cint(include_kra_pin)
    doc.include_landmark = cint(include_landmark)
    doc.include_cashier = cint(include_cashier)
    doc.include_company_logo = cint(include_company_logo)
    doc.show_email = cint(show_email)
    doc.show_phone_number = cint(show_phone_number)
    doc.include_receipt_no = cint(include_receipt_no)
    doc.selected_size = selected_size or "size2"
    doc.invoice_aging = invoice_aging or "7"
    doc.footer_text = footer_text or ""
    doc.paybill_number = paybill_number or ""
    doc.logo = logo or ""
    doc.email = email or ""
    doc.phone = phone or ""
    doc.location = location or ""
    doc.landmark = landmark or ""
    doc.kra = kra or ""
    doc.warehouse_name = warehouse_name or ""
    doc.invoice_warehouse = invoice_warehouse or ""
    doc.save()
    frappe.db.commit()
    return {"success": "1", "message": "Layout updated successfully"}
