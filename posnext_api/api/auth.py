import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password
from frappe.utils import cint
import json


def _get_printer_and_layout(warehouse=None):
    """Return printer and invoice-layout dicts for the given warehouse (or default)."""
    printer = None
    layout = None

    printer_filters = {}
    layout_filters = {}
    if warehouse:
        printer_filters["warehouse"] = warehouse
        layout_filters["warehouse"] = warehouse

    # Printer
    printers = frappe.get_all(
        "POS Printer",
        filters=printer_filters,
        fields=[
            "name as id",
            "printer_name",
            "address",
            "port",
            "connection_type",
            "printer_size",
            "warehouse",
            "is_default",
            "printer_warehouse",
            "printer_location",
            "printer_email",
            "printer_phone",
        ],
        order_by="is_default desc",
        limit=1,
    )
    if not printers and warehouse:
        # Fallback: pick the first printer regardless of warehouse
        printers = frappe.get_all(
            "POS Printer",
            fields=[
                "name as id",
                "printer_name",
                "address",
                "port",
                "connection_type",
                "printer_size",
                "warehouse",
                "is_default",
                "printer_warehouse",
                "printer_location",
                "printer_email",
                "printer_phone",
            ],
            order_by="is_default desc",
            limit=1,
        )
    if printers:
        p = printers[0]
        printer = {
            "id": p["id"],
            "name": p.get("printer_name", ""),
            "address": p.get("address", ""),
            "port": p.get("port", "9100"),
            "connection_type": p.get("connection_type", "Network"),
            "printer_size": p.get("printer_size", "80 mm"),
            "warehouse": p.get("warehouse", ""),
            "isDefault": cint(p.get("is_default", 0)),
            "printer_warehouse": p.get("printer_warehouse", ""),
            "printer_location": p.get("printer_location", ""),
            "printer_email": p.get("printer_email", ""),
            "printer_phone": p.get("printer_phone", ""),
        }

    # Invoice Layout
    layouts = frappe.get_all(
        "POS Invoice Layout",
        filters=layout_filters,
        fields=[
            "name as id",
            "is_default",
            "include_kra_pin",
            "include_receipt_no",
            "include_location",
            "include_warehouse",
            "include_landmark",
            "include_cashier",
            "include_company_logo",
            "show_email",
            "show_phone_number",
            "footer_text",
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
        order_by="is_default desc",
        limit=1,
    )
    if not layouts and warehouse:
        # Fallback: pick the first layout regardless of warehouse
        layouts = frappe.get_all(
            "POS Invoice Layout",
            fields=[
                "name as id",
                "is_default",
                "include_kra_pin",
                "include_receipt_no",
                "include_location",
                "include_warehouse",
                "include_landmark",
                "include_cashier",
                "include_company_logo",
                "show_email",
                "show_phone_number",
                "footer_text",
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
            order_by="is_default desc",
            limit=1,
        )
    if layouts:
        lo = layouts[0]
        layout = {
            "id": lo["id"],
            "isDefault": cint(lo.get("is_default", 0)),
            "includeKraPin": cint(lo.get("include_kra_pin", 0)),
            "includeReceiptNo": cint(lo.get("include_receipt_no", 0)),
            "includeLocation": cint(lo.get("include_location", 0)),
            "includeWarehouse": cint(lo.get("include_warehouse", 0)),
            "includeLandmark": cint(lo.get("include_landmark", 0)),
            "includeCashier": cint(lo.get("include_cashier", 0)),
            "includeCompanyLogo": cint(lo.get("include_company_logo", 0)),
            "showEmail": cint(lo.get("show_email", 0)),
            "showPhoneNumber": cint(lo.get("show_phone_number", 0)),
            "footerText": lo.get("footer_text") or "",
            "logo": lo.get("logo") or "none",
            "email": lo.get("email") or "none",
            "phone": lo.get("phone") or "none",
            "location": lo.get("location") or "none",
            "landmark": lo.get("landmark") or "none",
            "kra": lo.get("kra") or "none",
            "warehouse_name": lo.get("warehouse_name") or "none",
            "selected_size": lo.get("selected_size") or "size2",
            "paybill_number": lo.get("paybill_number") or "none",
            "invoice_warehouse": lo.get("invoice_warehouse") or "",
            "invoice_aging": lo.get("invoice_aging") or "7",
            "warehouse": lo.get("warehouse") or "",
        }

    return printer, layout


@frappe.whitelist(allow_guest=True)
def login(usr=None, pwd=None):
    """Authenticate user and return session details matching PosNext format."""
    if not usr or not pwd:
        frappe.throw(_("Username and password are required"))

    from frappe.auth import LoginManager

    login_manager = LoginManager()
    login_manager.authenticate(usr, pwd)
    login_manager.post_login()

    # Re-fetch after post_login to get any changes Frappe made
    user = frappe.get_doc("User", frappe.session.user)

    # Build warehouse list
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"disabled": 0, "is_group": 0},
        fields=["name", "warehouse_name"],
    )

    # Generate API token using Frappe's password utility
    api_key = user.api_key
    if not api_key:
        api_key = frappe.generate_hash(length=15)
        user.api_key = api_key

    api_secret = frappe.generate_hash(length=15)
    user.api_secret = api_secret
    user.flags.ignore_permissions = True
    user.save()
    frappe.db.commit()

    token = f"{api_key}:{api_secret}"

    _printer, _layout = _get_printer_and_layout()

    return {
        "success": "1",
        "message": "Login successful",
        "token": token,
        "user": {
            "id": user.name,
            "name": user.full_name,
            "username": user.name,
            "email": user.email,
            "phone": user.phone or "",
            "user_role": (
                user.roles[0].role if user.roles else "Guest"
            ),
            "isAdmin": 1 if "System Manager" in [r.role for r in user.roles] else 0,
            "isSuper_user": (
                1 if "Administrator" in [r.role for r in user.roles] else 0
            ),
            "isStaff": 1,
            "id_number": "",
            "user_permissions": _get_permissions(user),
            "signature": "",
            "enable_checkin": 0,
            "view_today_data": False,
            "restrict_view_sales": False,
        },
        "tenant_id": frappe.local.site,
        "tenant": {
            "id": frappe.local.site,
            "name": frappe.db.get_single_value("Website Settings", "app_name")
            or frappe.local.site,
            "email": "",
            "phone": "",
            "location": "",
            "landmark": "",
            "isActive": 1,
            "backup_email": "",
            "tenancy_db_name": frappe.conf.db_name,
            "backend": "ERP",
            "api_link": frappe.local.site,
            "created_at": str(frappe.utils.now_datetime()),
        },
        "header": frappe.db.get_single_value("Letter Head", "content") or "",
        "footer": "",
        "logo": (
            frappe.db.get_single_value("Website Settings", "app_logo") or "none"
        ),
        "image_url": "",
        "isActive": True,
        "isButchery": False,
        "shift_id": "0",
        "warehouses": warehouses,
        "printer": _printer,
        "invoicelayout": _layout,
    }


@frappe.whitelist(allow_guest=True)
def login_pin(pin=None, user_id=None):
    """PIN-based quick login for cashiers.

    user_id is the sequential integer index (1-based) matching the order
    returned by refresh_session's users list.
    """
    if not pin or user_id is None:
        frappe.throw(_("PIN and user_id are required"))

    user_id = int(user_id)

    # Reproduce the same user list and order as refresh_session
    pos_users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name", "email", "phone", "ury_pos_pin"],
        order_by="full_name asc",
    )

    if user_id < 1 or user_id > len(pos_users):
        return {"success": "0", "message": "User not found"}

    target = pos_users[user_id - 1]

    stored_pin = frappe.db.get_value("User", target.name, "ury_pos_pin")
    if not stored_pin or str(stored_pin) != str(pin):
        return {"success": "0", "message": "Invalid PIN", "stored_pin": stored_pin, "provided_pin": pin, "target": target}

    user_doc = frappe.get_doc("User", target.name)
    role_names = [r.role for r in user_doc.roles]

    # Generate a fresh API token for this user
    api_key = user_doc.api_key
    api_secret = frappe.generate_hash(length=15)
    if not api_key:
        api_key = frappe.generate_hash(length=15)
        user_doc.api_key = api_key
    user_doc.api_secret = api_secret
    user_doc.save(ignore_permissions=True)
    frappe.db.commit()

    token = f"{api_key}:{api_secret}"

    # Build users list (same as refresh_session)
    users = []
    for idx, u in enumerate(pos_users, start=1):
        users.append(
            {
                "id": idx,
                "name": u.full_name or u.name,
                "username": u.name,
                "email": u.email or "",
                "login_pin": u.ury_pos_pin or "1234",
                "selected": False,
            }
        )

    _pin_printer, _pin_layout = _get_printer_and_layout()

    return {
        "success": "1",
        "message": "Login successful",
        "token": token,
        "user": {
            "id": target.name,
            "name": target.full_name or target.name,
            "username": target.name,
            "email": target.email or "",
            "phone": target.phone or "",
            "user_role": role_names[0] if role_names else "Guest",
            "isAdmin": 1 if "System Manager" in role_names else 0,
            "isSuper_user": 1 if "Administrator" in role_names else 0,
            "isStaff": 1,
            "id_number": "",
            "user_permissions": _get_permissions(user_doc),
            "signature": "",
            "enable_checkin": 0,
            "view_today_data": False,
            "restrict_view_sales": False,
        },
        "users": users,
        "tenant_id": frappe.local.site,
        "tenant": {
            "id": frappe.local.site,
            "name": frappe.db.get_single_value("Website Settings", "app_name")
            or frappe.local.site,
            "email": "",
            "phone": "",
            "location": "",
            "landmark": "",
            "isActive": 1,
            "backup_email": "",
            "tenancy_db_name": frappe.conf.db_name,
            "backend": "ERP",
            "api_link": frappe.local.site,
            "created_at": str(frappe.utils.now_datetime()),
        },
        "header": frappe.db.get_single_value("Letter Head", "content") or "",
        "footer": "",
        "logo": frappe.db.get_single_value("Website Settings", "app_logo")
        or "none",
        "image_url": "",
        "isActive": True,
        "isButchery": False,
        "shift_id": "0",
        "printer": _pin_printer,
        "invoicelayout": _pin_layout,
    }


@frappe.whitelist()
def get_warehouses():
    """Return warehouses accessible by the current user.

    Stock Manager / System Manager → all warehouses.
    Others → only warehouses linked to POS Profiles assigned to them.
    """
    user_roles = frappe.get_roles(frappe.session.user)

    if "Stock Manager" in user_roles or "System Manager" in user_roles:
        warehouses = frappe.get_all(
            "Warehouse",
            filters={"disabled": 0, "is_group": 0},
            fields=["name", "warehouse_name", "is_group", "warehouse_type"],
        )
    else:
        # Get POS Profiles assigned to this user via POS Profile User child table
        pos_profiles = frappe.get_all(
            "POS Profile User",
            filters={"user": frappe.session.user},
            fields=["parent"],
        )
        profile_names = list({p.parent for p in pos_profiles})

        if profile_names:
            # Get warehouses from those POS Profiles
            wh_names = frappe.get_all(
                "POS Profile",
                filters={"name": ["in", profile_names], "disabled": 0},
                fields=["warehouse"],
                pluck="warehouse",
            )
            wh_names = list({w for w in wh_names if w})

            if wh_names:
                warehouses = frappe.get_all(
                    "Warehouse",
                    filters={"name": ["in", wh_names], "disabled": 0, "is_group": 0},
                    fields=["name", "warehouse_name", "is_group", "warehouse_type"],
                )
            else:
                warehouses = []
        else:
            warehouses = []
    result = []
    for idx, w in enumerate(warehouses, start=1):
        is_shop = 1 if (w.warehouse_type or "").lower() in ("shop", "retail") else 0
        result.append(
            {
                "warehouseID": idx,
                "name": w.warehouse_name or w.name,
                "erp_name": w.name,
                "warehouse_name": w.warehouse_name or w.name,
                "email": "",
                "phone": "",
                "landmark": "",
                "location": "",
                "invoice_aging": "30",
                "default_sales_period": "daily",
                "allow_divisible_items": 1,
                "user_warehouse_id": 0,
                "allow_credit_sale": 1,
                "subtotal_editable": 1,
                "unitprice_editable": 1,
                "display_out_of_stock_items": 1,
                "allow_shift": 1,
                "use_one_shift": 1,
                "is_shop": is_shop,
                "is_cold_room": 0,
                "temperature": "0",
                "humidity": "0",
                "isButchery": 0,
                "print_final_bill": 1,
                "allow_negative_stock": 0,
                "is_warehouse": 1,
                "show_stock_for_all_locations": 0,
                "close_shift_automatically": 0,
                "allow_sell_bellow_normal_price": 0,
                "enable_kot": 0,
                "enable_email_notifications": 0,
                "enable_attendance": 0,
                "show_selling_price": 1,
                "disable_edit_transfer": 0,
                "allow_transfer_others": 0,
                "shift_auto_closing_time": "none",
                "offline_pin": "0000",
                "enable_sell_offline": 0,
                "enable_background_receipt_submission": 0,
                "offline_type": "full",
                "sale_commission_rate": "0",
                "complete_transfer_point": "Receive",
                "allow_stock_transfer_in": 1,
                "allow_stock_transfer_out": 1,
            }
        )
    return result


def _build_pos_users_list():
    """Build the cashier/user list shown on the POS login screen.

    Matches PosNext's LoginUser format (id, name, login_pin) consumed by
    both `refresh_session` and the standalone `get_pos_users` endpoint.
    """
    users = []
    pos_users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name", "email", "ury_pos_pin"],
        order_by="full_name asc",
    )
    for idx, u in enumerate(pos_users, start=1):
        users.append(
            {
                "id": idx,
                "name": u.full_name,
                "username": u.name,
                "email": u.email or "",
                "login_pin": u.ury_pos_pin or "1234",
                "selected": False,
            }
        )
    return users

@frappe.whitelist()
def get_pos_users():
    """Return the cashier/user list for the POS login (user-switch) screen.

    ERPNext equivalent of Laravel's `getPosUsers` endpoint — used by the
    tablet/web POS login flow (see AppService.getPosUsers()) so it doesn't
    need a full `refresh_session` round trip just to list users.
    """
    return _build_pos_users_list()



@frappe.whitelist()
def refresh_session(token=None, warehouse=None):
    """Refresh session data — ERPNext equivalent of Laravel's refresh-new.

    Returns the same structure as login() so setSharedPref can consume it
    uniformly.  Does NOT regenerate the API token — the token from login()
    stays valid until the next explicit login.
    """
    user_doc = frappe.get_doc("User", frappe.session.user)

    # Read existing API credentials (don't regenerate)
    api_key = user_doc.api_key
    try:
        api_secret = get_decrypted_password(
            "User", user_doc.name, fieldname="api_secret"
        )
    except Exception:
        # If secret can't be decrypted, generate a fresh pair
        if not api_key:
            api_key = frappe.generate_hash(length=15)
            user_doc.api_key = api_key
        api_secret = frappe.generate_hash(length=15)
        user_doc.api_secret = api_secret
        user_doc.flags.ignore_permissions = True
        user_doc.save()
        frappe.db.commit()

    existing_token = f"{api_key}:{api_secret}"

    _rs_printer, _rs_layout = _get_printer_and_layout(warehouse)

    # Build users list for POS login screen (cashiers)
    users = _build_pos_users_list()
    # pos_users = frappe.get_all(
    #     "User",
    #     filters={"enabled": 1, "user_type": "System User"},
    #     fields=["name", "full_name", "email", "ury_pos_pin"],
    #     order_by="full_name asc",
    # )
    # for idx, u in enumerate(pos_users, start=1):
    #     users.append(
    #         {
    #             "id": idx,
    #             "name": u.full_name,
    #             "username": u.name,
    #             "email": u.email or "",
    #             "login_pin": u.ury_pos_pin or "1234",
    #             "selected": False,
    #         }
    #     )

    return {
        "success": "1",
        "message": "Session refreshed",
        "token": existing_token,
        "user": {
            "id": user_doc.name,
            "name": user_doc.full_name,
            "username": user_doc.name,
            "email": user_doc.email or "",
            "phone": user_doc.phone or "",
            "user_role": (
                user_doc.roles[0].role if user_doc.roles else "Guest"
            ),
            "isAdmin": (
                1
                if "System Manager" in [r.role for r in user_doc.roles]
                else 0
            ),
            "isSuper_user": (
                1
                if "Administrator" in [r.role for r in user_doc.roles]
                else 0
            ),
            "isStaff": 1,
            "id_number": "",
            "user_permissions": _get_permissions(user_doc),
            "signature": "",
            "enable_checkin": 0,
            "view_today_data": False,
            "restrict_view_sales": False,
        },
        "users": users,
        "tenant_id": frappe.local.site,
        "tenant": {
            "id": frappe.local.site,
            "name": frappe.db.get_single_value("Website Settings", "app_name")
            or frappe.local.site,
            "email": "",
            "phone": "",
            "location": "",
            "landmark": "",
            "isActive": 1,
            "backup_email": "",
            "tenancy_db_name": frappe.conf.db_name,
            "backend": "ERP",
            "api_link": frappe.local.site,
            "created_at": str(frappe.utils.now_datetime()),
        },
        "header": frappe.db.get_single_value("Letter Head", "content") or "",
        "footer": "",
        "proforma_text": None,
        "printer": _rs_printer,
        "invoicelayout": _rs_layout,
        "logo": (
            frappe.db.get_single_value("Website Settings", "app_logo")
            or "none"
        ),
        "image_url": "",
        "isActive": True,
        "isButchery": False,
    }


def _get_permissions(user):
    """Map ERPNext roles to PosNext permission strings."""
    roles = [r.role for r in user.roles]
    permissions = []

    role_map = {
        "view-home-page": ["Sales User", "Sales Manager", "System Manager", "Stock User"],
        "view-pos": ["Sales User", "Sales Manager", "System Manager"],
        "view-products": ["Stock User", "Stock Manager", "Sales User", "System Manager"],
        "view-receipts": ["Sales User", "Sales Manager", "Accounts User", "System Manager"],
        "view-billing": ["Accounts User", "Accounts Manager", "System Manager"],
        "view-procurement": ["Purchase User", "Purchase Manager", "System Manager"],
        "view-stock": ["Stock User", "Stock Manager", "System Manager"],
        "view-reports": ["Sales Manager", "Accounts Manager", "System Manager"],
        "view-contacts": ["Sales User", "System Manager"],
        "view-hrm": ["HR User", "HR Manager", "System Manager"],
        "view-finance": ["Accounts User", "Accounts Manager", "System Manager"],
        "view-stores": ["Stock Manager", "System Manager"],
        "view-business-settings": ["System Manager"],
        "view-sales-reports": ["System Manager"],
        "view-shift": ["Sales User", "Sales Manager", "System Manager"],
        'create-product': ['Stock User', 'Stock Manager', 'System Manager'],
        'create-category': ['Stock User', 'Stock Manager', 'System Manager'],
        'delete-product': ['Stock Manager', 'System Manager'],
        'edit-product': ['Stock Manager', 'System Manager'],
        'create-stock-adjustment': ['Stock Manager', 'System Manager'],
        'edit-sell-price': ['Stock Manager', 'System Manager'],
        'close-shift': ["Sales User", 'Sales Manager', 'System Manager'],
        'open-shift': ["Sales User", 'Sales Manager', 'System Manager'],
        'create-printer': ['System Manager', 'Sales Manager'],
        'create-receipt-layout': ['System Manager', 'Sales Manager'],
        'view-purchase-receipt': ['Purchase User', 'Purchase Manager', 'System Manager'],
        'create-purchase-receipt': ['Purchase Manager', 'System Manager'],
        'view-stock-reconciliation': ['Stock User', 'System Manager'],
        'create-stock-reconciliation': ['Stock Manager', 'System Manager'],
        'view-stock-transfer': ['Stock User', 'System Manager'],
        'create-stock-transfer': ['Stock Manager', 'System Manager'],
    }

    for perm, allowed_roles in role_map.items():
        if any(r in roles for r in allowed_roles):
            permissions.append(perm)

    return permissions
