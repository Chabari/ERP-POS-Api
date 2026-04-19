import frappe
from frappe import _

PAGE_SIZE = 20


@frappe.whitelist()
def get_items(warehouse=None, item_group=None, search=None, page=1):
    """Return items with stock info for the Items screen."""
    page = int(page)
    start = (page - 1) * PAGE_SIZE

    filters = {"disabled": 0}
    if item_group:
        filters["item_group"] = item_group

    or_filters = {}
    if search:
        or_filters = {
            "item_name": ["like", f"%{search}%"],
            "item_code": ["like", f"%{search}%"],
            "barcode": ["like", f"%{search}%"],
        }

    items = frappe.get_all(
        "Item",
        filters=filters,
        or_filters=or_filters if search else None,
        fields=[
            "name",
            "item_name",
            "item_code",
            "item_group",
            "stock_uom",
            "image",
            "standard_rate",
            "last_purchase_rate",
            "disabled",
        ],
        limit_start=start,
        limit_page_length=PAGE_SIZE,
        order_by="item_name asc",
    )

    # Enrich with stock quantities
    for item in items:
        bin_filter_conditions = ["item_code = %(item_code)s"]
        bin_filter_values = {"item_code": item.name}
        if warehouse:
            bin_filter_conditions.append("warehouse = %(warehouse)s")
            bin_filter_values["warehouse"] = warehouse

        actual_qty = frappe.db.sql(
            """SELECT IFNULL(SUM(actual_qty), 0) FROM `tabBin` WHERE {conditions}""".format(
                conditions=" AND ".join(bin_filter_conditions)
            ),
            bin_filter_values,
        )
        item["actual_qty"] = float(actual_qty[0][0]) if actual_qty else 0

        # Fetch barcodes
        barcodes = frappe.get_all(
            "Item Barcode",
            filters={"parent": item.name},
            fields=["barcode"],
        )
        item["barcodes"] = barcodes

        # Reorder level
        reorder = frappe.db.get_value(
            "Item Reorder",
            {"parent": item.name, "warehouse": warehouse} if warehouse else {"parent": item.name},
            "warehouse_reorder_level",
        )
        item["reorder_level"] = float(reorder or 0)

        # Selling price from Item Price matching the item's stock_uom
        selling_price_list = frappe.db.get_single_value(
            "Selling Settings", "selling_price_list"
        )
        if selling_price_list:
            price_rate = frappe.db.get_value(
                "Item Price",
                {
                    "item_code": item.name,
                    "selling": 1,
                    "price_list": selling_price_list,
                    "uom": item.stock_uom,
                },
                "price_list_rate",
            )
            if price_rate is None:
                # Fallback: Item Price with no UOM set
                price_rate = frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": item.name,
                        "selling": 1,
                        "price_list": selling_price_list,
                        "uom": ["in", ["", None]],
                    },
                    "price_list_rate",
                )
            if price_rate is not None:
                item["standard_rate"] = float(price_rate)

    return [_item_to_laravel_format(item) for item in items]


@frappe.whitelist()
def get_pos_items(warehouse=None, item_group=None, search=None, page=1):
    """Return items formatted for the POS screen (same data, filtered for POS)."""
    return get_items(
        warehouse=warehouse, item_group=item_group, search=search, page=page
    )


@frappe.whitelist()
def get_items_by_category(cat_id=None, warehouse=None):
    """Return items filtered by item group (category)."""
    return get_items(warehouse=warehouse, item_group=cat_id)


@frappe.whitelist()
def check_item_details(items=None, warehouse=None, item_id=None):
    """Return stock levels for one or more items across all warehouses.

    Accepts either:
      - ``items``: a list of dicts ``[{"item_id": "<item_code>"}, ...]``
      - ``item_id``: a single item code (legacy / fallback)

    Returns a JSON list matching the Flutter ``ItemStockLevel`` model::

        [
          {
            "item_id": "<item_code>",
            "available": "<qty_in_current_warehouse>",
            "stockLevels": [
              {"id": 0, "name": "<warehouse>", "available_quantity": "<qty>", "order_level": "0"},
              ...
            ]
          },
          ...
        ]
    """
    import json as _json

    # ── Normalise input ──────────────────────────────────────────────
    if isinstance(items, str):
        items = _json.loads(items)

    if not items and item_id:
        items = [{"item_id": item_id}]

    if not items:
        return {"success": "0", "message": "No item_id provided"}

    item_codes = [it["item_id"] for it in items if it.get("item_id")]
    if not item_codes:
        return {"success": "0", "message": "No item_id provided"}

    # ── Fetch stock across ALL warehouses for the requested items ─────
    bin_rows = frappe.db.sql(
        """SELECT item_code, warehouse, IFNULL(actual_qty, 0) AS actual_qty
           FROM `tabBin`
           WHERE item_code IN %(codes)s""",
        {"codes": item_codes},
        as_dict=True,
    )

    # Group by item_code → list of warehouse entries
    from collections import defaultdict
    stock_map = defaultdict(list)
    for row in bin_rows:
        stock_map[row.item_code].append(row)

    result = []
    for code in item_codes:
        wh_entries = stock_map.get(code, [])
        available = 0
        levels = []
        for entry in wh_entries:
            qty = float(entry.actual_qty)
            if warehouse and entry.warehouse == warehouse:
                available = qty
                continue
            levels.append({
                "id": 0,
                "name": entry.warehouse,
                "available_quantity": str(qty),
                "order_level": "0",
            })
        # If current warehouse had no bin row, available stays 0
        result.append({
            "item_id": code,
            "available": str(available),
            "stockLevels": levels,
        })

    return result


@frappe.whitelist()
def search_items(query=None, warehouse=None, **kwargs):
    """Search items by name, code, or barcode."""
    if not query:
        return get_items(warehouse=warehouse)
    return get_items(warehouse=warehouse, search=query)


@frappe.whitelist()
def get_item_analysis(item_id=None, warehouse_id=None):
    """Return stock analysis for a specific item."""
    if not item_id:
        return {"success": "0", "message": "No item_id provided"}

    item_code = str(item_id)
    wh = warehouse_id

    actual_qty = 0
    if wh:
        qty_result = frappe.db.sql(
            """SELECT IFNULL(SUM(actual_qty), 0) FROM `tabBin`
               WHERE item_code = %(item_code)s AND warehouse = %(warehouse)s""",
            {"item_code": item_code, "warehouse": wh},
        )
        actual_qty = float(qty_result[0][0]) if qty_result else 0

    # Reorder level for this warehouse
    reorder_level = 0
    if wh:
        rl = frappe.db.get_value(
            "Item Reorder",
            {"parent": item_code, "warehouse": wh},
            "warehouse_reorder_level",
        )
        reorder_level = float(rl or 0)

    # Helper to sum SLE qty by voucher type
    def _sum_sle(voucher_types, positive=True):
        if not voucher_types:
            return 0
        op = ">" if positive else "<"
        types_placeholder = ", ".join([f"'{v}'" for v in voucher_types])
        sql = f"""SELECT IFNULL(SUM(ABS(actual_qty)), 0) FROM `tabStock Ledger Entry`
                  WHERE item_code = %(item_code)s AND docstatus = 1
                  AND actual_qty {op} 0 AND voucher_type IN ({types_placeholder})"""
        if wh:
            sql += " AND warehouse = %(warehouse)s"
        result = frappe.db.sql(sql, {"item_code": item_code, "warehouse": wh})
        return float(result[0][0]) if result else 0

    total_purchases = _sum_sle(["Purchase Receipt", "Purchase Invoice"], positive=True)
    opening_stock = _sum_sle(["Stock Reconciliation"], positive=True)
    total_sell_return = _sum_sle(["Delivery Note"], positive=True)  # returns come in positive
    stock_transfer_in = _sum_sle(["Stock Entry"], positive=True)
    stock_adjustment_in = 0
    stock_take_in = 0
    work_order_in = _sum_sle(["Work Order"], positive=True)

    total_sold = _sum_sle(["Delivery Note", "Sales Invoice", "POS Invoice"], positive=False)
    total_purchase_return = _sum_sle(["Purchase Receipt", "Purchase Invoice"], positive=False)
    stock_transfer_out = _sum_sle(["Stock Entry"], positive=False)
    stock_adjustment_out = 0
    stock_take_out = 0
    work_order_out = _sum_sle(["Work Order"], positive=False)
    waste = 0

    total_in = total_purchases + opening_stock + total_sell_return + stock_transfer_in + stock_adjustment_in + stock_take_in + work_order_in
    total_out = total_sold + total_purchase_return + stock_transfer_out + stock_adjustment_out + stock_take_out + work_order_out + waste

    return {
        "currentStock": actual_qty,
        "reorderLevel": reorder_level,
        "totalPurchases": total_purchases,
        "openingStock": opening_stock,
        "totalSellReturn": total_sell_return,
        "stockTransferIn": stock_transfer_in,
        "stockAdjustmentIn": stock_adjustment_in,
        "stockTakeIn": stock_take_in,
        "workOrderIn": work_order_in,
        "totalsold": total_sold,
        "totalpurchasereturn": total_purchase_return,
        "stocktransferout": stock_transfer_out,
        "toatladjustmentOut": stock_adjustment_out,
        "stockTakeOut": stock_take_out,
        "workOrderOut": work_order_out,
        "waste": waste,
        "totalin": total_in,
        "totalout": total_out,
    }


@frappe.whitelist()
def get_item_transaction_analysis(item_id=None, warehouse_id=None,
                                   start_date=None, end_date=None):
    """Return item movement/transaction history in Laravel-compatible format."""
    from frappe.utils import getdate as _getdate
    filters = {"item_code": str(item_id), "docstatus": 1}
    if warehouse_id:
        filters["warehouse"] = warehouse_id
    if start_date and end_date:
        filters["posting_date"] = ["between", [_getdate(start_date), _getdate(end_date)]]
    elif start_date:
        filters["posting_date"] = [">=", _getdate(start_date)]
    elif end_date:
        filters["posting_date"] = ["<=", _getdate(end_date)]
    entries = frappe.get_all(
        "Stock Ledger Entry",
        filters=filters,
        fields=[
            "name", "posting_date", "voucher_type", "voucher_no",
            "actual_qty", "qty_after_transaction", "valuation_rate",
            "warehouse",
        ],
        order_by="posting_date desc",
        limit_page_length=100,
    )
    result = []
    for idx, e in enumerate(entries):
        actual = float(e.get("actual_qty", 0))
        result.append({
            "id": idx + 1,
            "type": e.get("voucher_type", ""),
            "transaction_type": "add" if actual >= 0 else "subtract",
            "stock_warehouse": e.get("warehouse", warehouse_id or ""),
            "quantity_change": str(abs(actual)),
            "new_quantity": str(float(e.get("qty_after_transaction", 0))),
            "contact": "",
            "reference_no": e.get("voucher_no", ""),
            "transaction_by": frappe.session.user or "N/A",
            "created_at": str(e.get("posting_date", "")),
            "updated_at": str(e.get("posting_date", "")),
        })
    return result


@frappe.whitelist()
def product_categories(cat_id=None, warehouse=None):
    """Return items for a specific category (item group)."""
    return get_items(warehouse=warehouse, item_group=cat_id)


@frappe.whitelist()
def get_item_attributes(item_id=None):
    """Return item UOMs and variant attributes in Laravel-compatible format."""
    if not item_id:
        return {"attribute_name": "none", "uoms": [], "variants": []}

    item_code = str(item_id)
    if not frappe.db.exists("Item", item_code):
        return {"attribute_name": "none", "uoms": [], "variants": []}

    item_doc = frappe.get_doc("Item", item_code)

    # UOM conversions
    uoms = []
    selling_price_list = frappe.db.get_single_value(
        "Selling Settings", "selling_price_list"
    )
    for uom_row in item_doc.uoms:
        sell_price = ""
        if selling_price_list:
            price_rate = frappe.db.get_value(
                "Item Price",
                {
                    "item_code": item_code,
                    "selling": 1,
                    "price_list": selling_price_list,
                    "uom": uom_row.uom,
                },
                "price_list_rate",
            )
            sell_price = str(float(price_rate)) if price_rate else ""
        uoms.append({
            "name": uom_row.uom,
            "short_name": uom_row.uom,
            "unit_id": uom_row.uom,
            "conversion_factor": float(uom_row.conversion_factor or 1),
            "sell_price": sell_price,
        })

    # Variants
    variants = []
    attribute_name = "none"
    if item_doc.has_variants and item_doc.attributes:
        attribute_name = item_doc.attributes[0].attribute
        for attr_row in item_doc.attributes:
            attr_values = frappe.get_all(
                "Item Attribute Value",
                filters={"parent": attr_row.attribute},
                fields=["attribute_value"],
                order_by="idx asc",
            )
            for av in attr_values:
                variants.append({"value": av.attribute_value})

    return {
        "attribute_name": attribute_name,
        "uoms": uoms,
        "variants": variants,
    }


@frappe.whitelist()
def fetch_all_items(warehouse=None, app=None, query=None, item_type=None):
    """Return all items, optionally filtered by search query."""
    items = get_items(warehouse=warehouse, search=query)
    return {"items_data": items}


def _extract_barcode_from_item(item):
    """Extract barcode from ERPNext item dict."""
    barcodes = item.get("barcodes", [])
    if barcodes and len(barcodes) > 0:
        bc = barcodes[0]
        return bc.get("barcode", "") if isinstance(bc, dict) else ""
    return item.get("barcode", "") or ""


def _item_to_laravel_format(item):
    """Convert ERPNext item dict to Laravel-compatible format."""
    return {
        "id": abs(hash(item.get("name", ""))) % (10 ** 8),
        "name": item.get("item_name", ""),
        "item_code": item.get("item_code", ""),
        "barcode": _extract_barcode_from_item(item),
        "image": item.get("image") or "none",
        "sell_price": str(item.get("standard_rate", 0)),
        "actual_sell_price": str(item.get("standard_rate", 0)),
        "buy_price": str(item.get("last_purchase_rate", 0)),
        "actual_buy_price": str(item.get("last_purchase_rate", 0)),
        "available_quantity": str(item.get("actual_qty", 0)),
        "category": item.get("item_group", ""),
        "category_id": item.get("item_group", ""),
        "unit_name": item.get("stock_uom", "Nos"),
        "unit_id": item.get("stock_uom", "Nos"),
        "reorder_level": str(item.get("reorder_level", 0)),
        "is_divisible": 1 if item.get("stock_uom") in ("Kg", "Litre") else 0,
        "is_published": 0 if item.get("disabled", 0) else 1,
        "item_group": item.get("item_group", ""),
        "tax_id": item.get("default_tax_template", "") or "",
    }


@frappe.whitelist()
def delete_product(item_id=None):
    """Disable an item (soft delete)."""
    if not item_id:
        return {"success": "0", "message": "No item_id provided"}
    try:
        item = frappe.get_doc("Item", str(item_id))
        item.disabled = 1
        item.save(ignore_permissions=True)
        return {"success": "1", "message": "Item disabled successfully"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def direct_stock_entry(item_id=None, actual_quantity=None,
                       stockEntryType=None, warehouse=None):
    """Create a Stock Reconciliation or Stock Entry for direct stock adjustment."""
    if not item_id or not actual_quantity:
        return {"success": "0", "message": "Missing item_id or quantity"}
    try:
        entry_type = int(stockEntryType or 0)
        # Fetch valuation rate; fall back to 1 if missing
        valuation_rate = frappe.db.get_value(
            "Item", str(item_id), "valuation_rate"
        ) or 0
        if not valuation_rate:
            bin_val = frappe.db.get_value(
                "Bin",
                {"item_code": str(item_id), "warehouse": warehouse},
                "valuation_rate",
            )
            valuation_rate = float(bin_val) if bin_val else 1

        if entry_type == 0:
            # Stock Reconciliation – set quantity to the given value
            doc = frappe.get_doc({
                "doctype": "Stock Reconciliation",
                "purpose": "Stock Reconciliation",
                "items": [{
                    "item_code": str(item_id),
                    "warehouse": warehouse,
                    "qty": float(actual_quantity),
                    "valuation_rate": float(valuation_rate),
                }],
            })
            doc.insert(ignore_permissions=True)
            doc.submit()
            msg = "Stock reconciliation created"
        else:
            # Material Receipt
            doc = frappe.get_doc({
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "items": [{
                    "item_code": str(item_id),
                    "qty": float(actual_quantity),
                    "t_warehouse": warehouse,
                    "basic_rate": float(valuation_rate),
                }],
            })
            doc.insert(ignore_permissions=True)
            doc.submit()
            msg = "Stock entry created"
        updated = get_items(warehouse=warehouse, search=str(item_id))
        return {
            "success": "1",
            "message": msg,
            "item": updated,
        }
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def delete_category(item_id=None):
    """Delete an Item Group (category)."""
    if not item_id:
        return {"success": "0", "message": "No item_id provided"}
    try:
        frappe.delete_doc("Item Group", str(item_id), ignore_permissions=True)
        return {"success": "1", "message": "Category deleted"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def update_price(item_id=None, action=None, amount=None, warehouse=None):
    """Update the selling price for the item's stock_uom in Item Price."""
    if not item_id or not amount:
        return {"success": "0", "message": "Missing item_id or amount"}
    try:
        item = frappe.get_doc("Item", str(item_id))
        selling_price_list = frappe.db.get_single_value(
            "Selling Settings", "selling_price_list"
        )
        if not selling_price_list:
            return {"success": "0", "message": "No default selling price list configured"}

        # Find existing Item Price for stock_uom
        existing = frappe.db.get_value(
            "Item Price",
            {
                "item_code": item.name,
                "selling": 1,
                "price_list": selling_price_list,
                "uom": item.stock_uom,
            },
            "name",
        )
        if not existing:
            # Fallback: check for Item Price with empty UOM
            existing = frappe.db.get_value(
                "Item Price",
                {
                    "item_code": item.name,
                    "selling": 1,
                    "price_list": selling_price_list,
                    "uom": ["in", ["", None]],
                },
                "name",
            )

        if existing:
            price_doc = frappe.get_doc("Item Price", existing)
            price_doc.price_list_rate = float(amount)
            if not price_doc.uom:
                price_doc.uom = item.stock_uom
            price_doc.save(ignore_permissions=True)
        else:
            # Create new Item Price entry
            frappe.get_doc({
                "doctype": "Item Price",
                "item_code": item.name,
                "price_list": selling_price_list,
                "selling": 1,
                "uom": item.stock_uom,
                "price_list_rate": float(amount),
            }).insert(ignore_permissions=True)

        # Also update standard_rate on the Item
        item.standard_rate = float(amount)
        item.save(ignore_permissions=True)
        return {"success": "1", "message": "Price updated successfully"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def create_item(name=None, item_group=None, sell_price=None, cost=None,
                barcode=None, warehouse=None, available_stock=None,
                reorder_level=None, unit_id=None, **kwargs):
    """Create a new Item in ERPNext."""
    if not name:
        return {"success": "0", "message": "Item name is required"}
    try:
        stock_uom = str(unit_id) if unit_id else "Nos"
        # Check if unit_id is a UOM name or needs lookup
        if stock_uom and not frappe.db.exists("UOM", stock_uom):
            stock_uom = "Nos"

        item_doc = frappe.get_doc({
            "doctype": "Item",
            "item_name": name,
            "item_code": name,
            "item_group": item_group or "All Item Groups",
            "stock_uom": stock_uom,
            "is_stock_item": 1,
            "standard_rate": float(sell_price or 0),
            "valuation_rate": float(cost or 0),
        })

        if barcode and barcode != "none":
            item_doc.append("barcodes", {"barcode": barcode})

        item_doc.insert(ignore_permissions=True)

        # Create selling price in Item Price
        selling_price_list = frappe.db.get_single_value(
            "Selling Settings", "selling_price_list"
        )
        # if selling_price_list and float(sell_price or 0) > 0:
        #     frappe.get_doc({
        #         "doctype": "Item Price",
        #         "item_code": item_doc.name,
        #         "price_list": selling_price_list,
        #         "selling": 1,
        #         "uom": stock_uom,
        #         "price_list_rate": float(sell_price),
        #     }).insert(ignore_permissions=True)

        # Create opening stock if provided
        if warehouse and float(available_stock or 0) > 0:
            se = frappe.get_doc({
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Receipt",
                "items": [{
                    "item_code": item_doc.name,
                    "qty": float(available_stock),
                    "t_warehouse": warehouse,
                    "basic_rate": float(cost or 0),
                }],
            })
            se.insert(ignore_permissions=True)
            se.submit()

        # Set reorder level
        if warehouse and float(reorder_level or 0) > 0:
            item_doc.append("reorder_levels", {
                "warehouse": warehouse,
                "warehouse_reorder_level": float(reorder_level),
                "warehouse_reorder_qty": float(reorder_level),
            })
            item_doc.save(ignore_permissions=True)

        updated = get_items(warehouse=warehouse, search=item_doc.name)
        return {
            "success": "1",
            "message": "Item created successfully",
            "item": updated,
        }
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def edit_item(item_id=None, name=None, item_group=None, sell_price=None,
              cost=None, barcode=None, warehouse=None, unit_id=None,
              reorder_level=None, **kwargs):
    """Edit an existing Item in ERPNext."""
    if not item_id:
        return {"success": "0", "message": "No item_id provided"}
    try:
        item_doc = frappe.get_doc("Item", str(item_id))

        if name:
            item_doc.item_name = name
        if item_group:
            item_doc.item_group = item_group
        if unit_id:
            uom = str(unit_id)
            if frappe.db.exists("UOM", uom):
                item_doc.stock_uom = uom
        if sell_price is not None:
            item_doc.standard_rate = float(sell_price)
        if cost is not None:
            item_doc.valuation_rate = float(cost)

        # Update barcodes
        if barcode and barcode != "none":
            existing_barcodes = [b.barcode for b in item_doc.barcodes]
            if barcode not in existing_barcodes:
                item_doc.append("barcodes", {"barcode": barcode})

        # Update reorder level
        if warehouse and reorder_level is not None:
            found = False
            for r in item_doc.reorder_levels:
                if r.warehouse == warehouse:
                    r.warehouse_reorder_level = float(reorder_level or 0)
                    r.warehouse_reorder_qty = float(reorder_level or 0)
                    found = True
                    break
            if not found and float(reorder_level or 0) > 0:
                item_doc.append("reorder_levels", {
                    "warehouse": warehouse,
                    "warehouse_reorder_level": float(reorder_level),
                    "warehouse_reorder_qty": float(reorder_level),
                })

        item_doc.save(ignore_permissions=True)

        # Update selling price in Item Price
        if sell_price is not None:
            selling_price_list = frappe.db.get_single_value(
                "Selling Settings", "selling_price_list"
            )
            if selling_price_list:
                existing = frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": item_doc.name,
                        "selling": 1,
                        "price_list": selling_price_list,
                        "uom": item_doc.stock_uom,
                    },
                    "name",
                )
                if existing:
                    price_doc = frappe.get_doc("Item Price", existing)
                    price_doc.price_list_rate = float(sell_price)
                    price_doc.save(ignore_permissions=True)
                elif float(sell_price) > 0:
                    frappe.get_doc({
                        "doctype": "Item Price",
                        "item_code": item_doc.name,
                        "price_list": selling_price_list,
                        "selling": 1,
                        "uom": item_doc.stock_uom,
                        "price_list_rate": float(sell_price),
                    }).insert(ignore_permissions=True)

        updated = get_items(warehouse=warehouse, search=item_doc.name)
        return {
            "success": "1",
            "message": "Item updated successfully",
            "item": updated,
        }
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def create_category(name=None, **kwargs):
    """Create a new Item Group (category) in ERPNext."""
    if not name:
        return {"success": "0", "message": "Category name is required"}
    try:
        if frappe.db.exists("Item Group", name):
            return {"success": "2", "message": "Category already exists"}
        doc = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": name,
            "parent_item_group": "All Item Groups",
        })
        doc.insert(ignore_permissions=True)
        return {"success": "1", "message": "Category created successfully"}
    except Exception as e:
        return {"success": "0", "message": str(e)}


@frappe.whitelist()
def edit_category(category_id=None, name=None, **kwargs):
    """Rename an Item Group (category) in ERPNext."""
    if not category_id or not name:
        return {"success": "0", "message": "Missing category_id or name"}
    try:
        if not frappe.db.exists("Item Group", str(category_id)):
            return {"success": "0", "message": "Category not found"}
        if str(category_id) != name:
            frappe.rename_doc("Item Group", str(category_id), name, force=True)
        return {"success": "1", "message": "Category updated successfully"}
    except Exception as e:
        return {"success": "0", "message": str(e)}
