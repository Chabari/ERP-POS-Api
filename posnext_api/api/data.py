import frappe
from frappe import _


@frappe.whitelist()
def get_item_groups():
    """Return item groups matching PosNext ItemGroupList format."""
    groups = frappe.get_all(
        "Item Group",
        filters={"is_group": 0},
        fields=["name", "parent_item_group", "image"],
        order_by="name asc",
    )
    result = []
    for idx, g in enumerate(groups, start=1):
        result.append(
            {
                "id": idx,
                "name": g.name,
                "maintain_stock": 1,
                "show_pos": 1,
                "parent": g.parent_item_group or "",
                "image": g.image or "",
            }
        )
    return result


@frappe.whitelist()
def get_users():
    """Return system users matching PosNext UsersList format."""
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name", "email", "phone", "creation"],
        order_by="full_name asc",
    )
    result = []
    for idx, u in enumerate(users, start=1):
        roles = frappe.get_all(
            "Has Role", filters={"parent": u.name}, fields=["role"]
        )
        role_names = [r.role for r in roles]
        result.append(
            {
                "id": idx,
                "name": u.full_name or u.name,
                "first_name": (u.full_name or u.name).split(" ")[0],
                "last_name": (
                    " ".join((u.full_name or "").split(" ")[1:])
                    if u.full_name
                    else ""
                ),
                "username": u.name,
                "email": u.email or "",
                "phone": u.phone or "",
                "user_role": role_names[0] if role_names else "Guest",
                "isAdmin": 1 if "System Manager" in role_names else 0,
                "isSuper_user": 1 if "Administrator" in role_names else 0,
                "isStaff": 1,
                "isDeleted": 0,
                "isActive": 1,
                "isPermanent": 1,
                "id_number": "",
                "login_pin": "1234",
                "sales_target": "0",
                "basic_pay": "0",
                "overtime_pay": "0",
                "enable_checkin": 0,
                "view_assigned_customers": 0,
                "view_assigned_items": 0,
                "date_of_employment": str(u.creation)[:10],
                "dob": "none",
                "created_at": str(u.creation),
                "updated_at": str(u.creation),
            }
        )
    return result


@frappe.whitelist()
def get_suppliers():
    """Return suppliers matching PosNext SupplierModel format."""
    suppliers = frappe.get_all(
        "Supplier",
        filters={"disabled": 0},
        fields=[
            "name",
            "supplier_name",
            "supplier_group",
            "supplier_type",
            "country",
            "mobile_no",
            "email_id",
            "creation",
        ],
        order_by="supplier_name asc",
    )
    result = []
    for idx, s in enumerate(suppliers, start=1):
        result.append(
            {
                "id": idx,
                "name": s.supplier_name,
                "supplier_name": s.supplier_name,
                "supplier_group": s.supplier_group or "",
                "phone": s.mobile_no or "",
                "email": s.email_id or "",
                "location": s.country or "",
                "address": "",
                "type_of_goods_sold": s.supplier_group or "",
                "supplier_credits": "0",
                "created_at": str(s.creation),
                "updated_at": str(s.creation),
            }
        )
    return result


@frappe.whitelist()
def get_customers():
    """Return customers matching PosNext CustomersModel format."""
    customers = frappe.get_all(
        "Customer",
        filters={"disabled": 0},
        fields=[
            "name",
            "customer_name",
            "customer_group",
            "territory",
            "mobile_no",
            "email_id",
            "creation",
        ],
        order_by="customer_name asc",
    )
    result = []
    for idx, c in enumerate(customers, start=1):
        result.append(
            {
                "id": idx,
                "name": c.customer_name,
                "customer_name": c.customer_name,
                "customer_group": c.customer_group or "",
                "phone": c.mobile_no or "",
                "email": c.email_id or "",
                "location": c.territory or "",
                "id_number": "",
                "allow_credit": 0,
                "customer_credits": "0",
                "credit_amount": "0",
                "tax_id": "",
                "created_at": str(c.creation),
                "updated_at": str(c.creation),
            }
        )
    return result


@frappe.whitelist()
def get_all_warehouses():
    """Return all warehouses matching PosNext WareHouseModel format."""
    warehouses = frappe.get_all(
        "Warehouse",
        filters={"disabled": 0, "is_group": 0},
        fields=["name", "warehouse_name", "is_group", "warehouse_type", "creation"],
        order_by="warehouse_name asc",
    )
    result = []
    for idx, w in enumerate(warehouses, start=1):
        is_shop = 1 if (w.warehouse_type or "").lower() in ("shop", "retail") else 0
        result.append(
            {
                "id": idx,
                "name": w.warehouse_name or w.name,
                "erp_name": w.name,
                "warehouse_name": w.warehouse_name,
                "email": "",
                "phone": "",
                "location": "",
                "landmark": "",
                "isDefault": 0,
                "isDeleted": 0,
                "is_published": 1,
                "is_warehouse": 1,
                "is_shop": is_shop,
                "is_cold_room": 0,
                "temperature": "0",
                "humidity": "0",
                "allow_negative_stock": 0,
                "allow_stock_transfer_in": 1,
                "allow_stock_transfer_out": 1,
                "allow_sell_bellow_normal_price": 0,
                "enable_email_notifications": 0,
                "show_stock_for_all_locations": 0,
                "enable_sell_offline": 0,
                "enable_background_receipt_submission": 0,
                "print_final_bill": 1,
                "offline_pin": "0000",
                "offline_type": "full",
                "default_buy_price": "0",
                "default_sell_price": "0",
                "sell_price": "Selling",
                "buy_price": "Buying",
                "total_value_buy": "0",
                "total_value_sell": "0",
                "created_at": str(w.creation),
                "updated_at": str(w.creation),
            }
        )
    return result


@frappe.whitelist()
def get_units():
    """Return UOM list matching PosNext UnitList format."""
    uoms = frappe.get_all(
        "UOM",
        filters={"enabled": 1},
        fields=["name", "must_be_whole_number"],
        order_by="name asc",
    )
    result = []
    for idx, u in enumerate(uoms, start=1):
        result.append(
            {
                "id": idx,
                "name": u.name,
                "short_name": u.name[:3].upper(),
                "isDivisible": 0 if u.must_be_whole_number else 1,
            }
        )
    return result


@frappe.whitelist()
def get_company_header():
    """Return company header/footer for receipt printing."""
    company = frappe.defaults.get_defaults().get("company")
    header = ""
    footer = ""
    if company:
        doc = frappe.get_doc("Company", company)
        header = doc.get("company_description") or doc.company_name or ""
        footer = doc.get("registration_details") or ""
    return {"success": "1", "header": header, "footer": footer}
