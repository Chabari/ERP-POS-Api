import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days, get_first_day, get_last_day, flt


def _wh_conditions(warehouse):
    """Return (wh_cond_alias, wh_cond_no_alias) SQL fragments.
    wh_cond_alias   – uses 'si' as the Sales Invoice alias.
    wh_cond_no_alias – uses the full table name.
    Both check header set_warehouse OR item-level warehouse.
    """
    if not warehouse:
        return "", ""
    alias = """AND (si.set_warehouse = %(warehouse)s
        OR si.name IN (SELECT DISTINCT parent FROM `tabSales Invoice Item`
                       WHERE warehouse = %(warehouse)s))"""
    no_alias = """AND (`tabSales Invoice`.set_warehouse = %(warehouse)s
        OR `tabSales Invoice`.name IN (
            SELECT DISTINCT parent FROM `tabSales Invoice Item`
            WHERE warehouse = %(warehouse)s))"""
    return alias, no_alias


@frappe.whitelist()
def get_home_analytics(date=None, warehouse=None):
    """Return dashboard analytics matching the PosNext Home screen format."""
    if not warehouse:
        frappe.throw(_("Warehouse is required"), title=_("Missing Parameter"))
    if not date:
        date = nowdate()

    target_date = getdate(date)

    wh_cond, wh_cond_no_alias = _wh_conditions(warehouse)

    # Daily sales
    daily_sales = frappe.db.sql(
        f"""SELECT IFNULL(SUM(`tabSales Invoice`.grand_total), 0)
            FROM `tabSales Invoice`
            WHERE `tabSales Invoice`.docstatus = 1 AND `tabSales Invoice`.posting_date = %(date)s {wh_cond_no_alias}""",
        {"date": target_date, "warehouse": warehouse},
    )[0][0] or 0

    # All-time total sales
    all_total_sales = frappe.db.sql(
        f"""SELECT IFNULL(SUM(`tabSales Invoice`.grand_total), 0)
            FROM `tabSales Invoice`
            WHERE `tabSales Invoice`.docstatus = 1 {wh_cond_no_alias}""",
        {"warehouse": warehouse},
    )[0][0] or 0

    # Total revenue (paid invoices)
    total_revenue = frappe.db.sql(
        f"""SELECT IFNULL(SUM(`tabSales Invoice`.grand_total), 0)
            FROM `tabSales Invoice`
            WHERE `tabSales Invoice`.docstatus = 1 AND `tabSales Invoice`.status IN ('Paid', 'Completed') {wh_cond_no_alias}""",
        {"warehouse": warehouse},
    )[0][0] or 0

    # Items count
    items_count = frappe.db.count("Item", {"disabled": 0})

    # Payment methods – all modes from POS Profile linked to warehouse, with daily totals
    pos_profile = None
    if warehouse:
        pos_profile = frappe.db.get_value(
            "POS Profile",
            {"warehouse": warehouse, "disabled": 0},
            "name",
        )
    if not pos_profile:
        # fallback: first enabled POS Profile
        pos_profile = frappe.db.get_value("POS Profile", {"disabled": 0}, "name")

    all_modes = []
    if pos_profile:
        all_modes = frappe.get_all(
            "POS Payment Method",
            filters={"parent": pos_profile, "parenttype": "POS Profile"},
            fields=["mode_of_payment", "default"],
            order_by="idx",
        )

    # Actual sales amounts per mode for the day
    sales_by_mode = {}
    mode_sales = frappe.db.sql(
        f"""
        SELECT sip.mode_of_payment, SUM(sip.amount) as amount
        FROM `tabSales Invoice Payment` sip
        JOIN `tabSales Invoice` si ON si.name = sip.parent
        WHERE si.docstatus = 1 AND si.posting_date = %(date)s
        {wh_cond}
        GROUP BY sip.mode_of_payment
        """,
        {"date": target_date, "warehouse": warehouse},
        as_dict=True,
    )
    for row in mode_sales:
        sales_by_mode[row.mode_of_payment] = float(row.amount)

    # Merge: every POS Profile mode with its daily total (0 if none)
    seen = set()
    payment_methods = []
    for m in all_modes:
        name = m.mode_of_payment
        seen.add(name)
        payment_methods.append({
            "mode_of_payment": name,
            "amount": sales_by_mode.get(name, 0),
        })
    # Include any mode with sales today that isn't on the POS Profile
    for name, amount in sales_by_mode.items():
        if name not in seen:
            payment_methods.append({"mode_of_payment": name, "amount": amount})

    # Weekly sales (last 7 days)
    week_start = add_days(target_date, -6)
    weekly_sales = frappe.db.sql(
        f"""
        SELECT si.posting_date as date, SUM(si.grand_total) as total
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %(start)s AND %(end)s
          {wh_cond}
        GROUP BY si.posting_date
        ORDER BY si.posting_date
        """,
        {"start": week_start, "end": target_date, "warehouse": warehouse},
        as_dict=True,
    )

    return {
        "items_count": items_count,
        "total_revenue": float(total_revenue),
        "all_total_sales": float(all_total_sales),
        "daily_sales": float(daily_sales),
        "payment_methods": payment_methods,
        "weekly_sales": [
            {"date": str(ws.date), "total": float(ws.total)} for ws in weekly_sales
        ],
    }


# ─── Period helpers ───────────────────────────────────────────────

def _period_range(period):
    """Return (start_date, end_date, group_by_field, label_format) for a period."""
    today = getdate(nowdate())
    if period == "7days":
        return add_days(today, -6), today, "posting_date", "day"
    elif period == "30days":
        return add_days(today, -29), today, "posting_date", "day"
    elif period == "12months":
        return add_days(today, -365), today, "DATE_FORMAT(si.posting_date, '%%Y-%%m')", "month"
    else:  # today
        return today, today, "posting_date", "day"


def _pct_change(current, previous):
    """Return a '±X%' string comparing two numbers."""
    if not previous:
        return "+100%" if current else "0%"
    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


@frappe.whitelist()
def get_dashboard_analytics(period="today", warehouse=None):
    """Full analytics endpoint matching the Flutter HomeAnalyticsTab structure."""
    today = getdate(nowdate())
    start_date, end_date, group_expr, label_fmt = _period_range(period)
    wh_cond, wh_cond_no_alias = _wh_conditions(warehouse)
    params = {"warehouse": warehouse, "start": start_date, "end": end_date}

    # ── Previous period (for % change) ──
    delta = (getdate(end_date) - getdate(start_date)).days + 1
    prev_end = add_days(start_date, -1)
    prev_start = add_days(prev_end, -(delta - 1))
    prev_params = {"warehouse": warehouse, "start": prev_start, "end": prev_end}

    # ── KPI: Total Sales ──
    total_sales = frappe.db.sql(
        f"""SELECT IFNULL(SUM(si.grand_total), 0)
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        params,
    )[0][0] or 0

    prev_total_sales = frappe.db.sql(
        f"""SELECT IFNULL(SUM(si.grand_total), 0)
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        prev_params,
    )[0][0] or 0

    # ── KPI: Total Orders ──
    total_orders = frappe.db.sql(
        f"""SELECT COUNT(si.name)
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        params,
    )[0][0] or 0

    prev_total_orders = frappe.db.sql(
        f"""SELECT COUNT(si.name)
            FROM `tabSales Invoice` si
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        prev_params,
    )[0][0] or 0

    avg_order = (total_sales / total_orders) if total_orders else 0
    prev_avg_order = (prev_total_sales / prev_total_orders) if prev_total_orders else 0

    # ── KPI: Gross Profit (sales - buying cost) ──
    buying_cost = frappe.db.sql(
        f"""SELECT IFNULL(SUM(sii.qty * sii.incoming_rate), 0)
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        params,
    )[0][0] or 0

    gross_profit = flt(total_sales) - flt(buying_cost)

    prev_buying_cost = frappe.db.sql(
        f"""SELECT IFNULL(SUM(sii.qty * sii.incoming_rate), 0)
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        prev_params,
    )[0][0] or 0
    prev_gross_profit = flt(prev_total_sales) - flt(prev_buying_cost)

    # ── KPI: Items Sold ──
    items_sold = frappe.db.sql(
        f"""SELECT IFNULL(SUM(sii.qty), 0)
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        params,
    )[0][0] or 0

    prev_items_sold = frappe.db.sql(
        f"""SELECT IFNULL(SUM(sii.qty), 0)
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}""",
        prev_params,
    )[0][0] or 0

    # ── KPI: New Customers ──
    new_customers = frappe.db.sql(
        """SELECT COUNT(name) FROM `tabCustomer`
           WHERE creation BETWEEN %(start)s AND %(end)s""",
        params,
    )[0][0] or 0
    prev_new_customers = frappe.db.sql(
        """SELECT COUNT(name) FROM `tabCustomer`
           WHERE creation BETWEEN %(start)s AND %(end)s""",
        prev_params,
    )[0][0] or 0

    kpi = {
        "totalSales": float(total_sales),
        "totalSalesChange": _pct_change(total_sales, prev_total_sales),
        "totalOrders": int(total_orders),
        "totalOrdersChange": _pct_change(total_orders, prev_total_orders),
        "avgOrderValue": float(avg_order),
        "avgOrderValueChange": _pct_change(avg_order, prev_avg_order),
        "grossProfit": float(gross_profit),
        "grossProfitChange": _pct_change(gross_profit, prev_gross_profit),
        "itemsSold": float(items_sold),
        "itemsSoldChange": _pct_change(items_sold, prev_items_sold),
        "newCustomers": int(new_customers),
        "newCustomersChange": _pct_change(new_customers, prev_new_customers),
    }

    # ── Sales Trend ──
    if label_fmt == "month":
        trend_rows = frappe.db.sql(
            f"""SELECT DATE_FORMAT(si.posting_date, '%%Y-%%m') as label,
                       SUM(si.grand_total) as value
                FROM `tabSales Invoice` si
                WHERE si.docstatus = 1
                  AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}
                GROUP BY label ORDER BY label""",
            params, as_dict=True,
        )
    else:
        trend_rows = frappe.db.sql(
            f"""SELECT si.posting_date as label, SUM(si.grand_total) as value
                FROM `tabSales Invoice` si
                WHERE si.docstatus = 1
                  AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}
                GROUP BY si.posting_date ORDER BY si.posting_date""",
            params, as_dict=True,
        )
    sales_trend = [
        {"label": str(r.label), "value": float(r.value or 0)} for r in trend_rows
    ]

    # ── Top Selling Products ──
    top_products_rows = frappe.db.sql(
        f"""SELECT sii.item_name as name, SUM(sii.amount) as value
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}
            GROUP BY sii.item_code
            ORDER BY value DESC LIMIT 10""",
        params, as_dict=True,
    )
    top_products = [
        {"name": r.name, "value": float(r.value or 0)} for r in top_products_rows
    ]

    # ── Payment Methods ──
    pm_rows = frappe.db.sql(
        f"""SELECT sip.mode_of_payment as name, SUM(sip.amount) as value
            FROM `tabSales Invoice Payment` sip
            JOIN `tabSales Invoice` si ON si.name = sip.parent
            WHERE si.docstatus = 1
              AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}
            GROUP BY sip.mode_of_payment ORDER BY value DESC""",
        params, as_dict=True,
    )
    payment_methods = [
        {"name": r.name, "value": float(r.value or 0)} for r in pm_rows
    ]

    # ── Hourly Sales (only meaningful for today/7days) ──
    hourly_sales = []
    if period in ("today", "7days"):
        hourly_rows = frappe.db.sql(
            f"""SELECT HOUR(si.posting_time) as hr, SUM(si.grand_total) as value
                FROM `tabSales Invoice` si
                WHERE si.docstatus = 1
                  AND si.posting_date BETWEEN %(start)s AND %(end)s {wh_cond}
                GROUP BY hr ORDER BY hr""",
            params, as_dict=True,
        )
        for r in hourly_rows:
            h = int(r.hr)
            label = f"{h:02d}:00"
            hourly_sales.append({"label": label, "value": float(r.value or 0)})

    # ── Expense Breakdown ──
    expense_rows = frappe.db.sql(
        """SELECT pe.party as name, SUM(pe.paid_amount) as value
           FROM `tabPayment Entry` pe
           WHERE pe.docstatus = 1 AND pe.payment_type = 'Pay'
             AND pe.posting_date BETWEEN %(start)s AND %(end)s
           GROUP BY pe.party ORDER BY value DESC LIMIT 8""",
        params, as_dict=True,
    )
    expense_categories = [
        {"name": r.name or "Other", "value": float(r.value or 0)}
        for r in expense_rows
    ]

    # ── Profit Margin ──
    margin = (gross_profit / total_sales * 100) if total_sales else 0
    profit_margin = {
        "margin": round(margin, 1),
        "revenue": float(total_sales),
        "costs": float(buying_cost),
        "profit": float(gross_profit),
    }

    return {
        "success": "1",
        "kpi": kpi,
        "sales_trend": sales_trend,
        "top_products": top_products,
        "payment_methods": payment_methods,
        "hourly_sales": hourly_sales,
        "expense_categories": expense_categories,
        "profit_margin": profit_margin,
    }


@frappe.whitelist()
def get_stock_value(warehouse=None):
    """Return total stock value at selling price and item count for a warehouse.

    Compares the Bin stock_uom with the Item Price uom so that
    qty * rate is only calculated when units match.  When the UOMs
    differ, the stock qty is converted via the item's UOM Conversion
    Factor before multiplying by the price rate.
    """
    wh_filter = "AND b.warehouse = %(warehouse)s" if warehouse else ""
    result = frappe.db.sql(
        f"""SELECT
                IFNULL(SUM(
                    CASE
                        WHEN ip.uom IS NULL OR ip.uom = '' OR ip.uom = b.stock_uom
                            THEN b.actual_qty * ip.price_list_rate
                        ELSE b.actual_qty
                             / IFNULL(
                                 (SELECT uc.conversion_factor
                                  FROM `tabUOM Conversion Detail` uc
                                  WHERE uc.parent = b.item_code
                                    AND uc.parenttype = 'Item'
                                    AND uc.uom = ip.uom
                                  LIMIT 1), 1)
                             * ip.price_list_rate
                    END
                ), 0) as stock_value,
                COUNT(DISTINCT b.item_code) as item_count
            FROM `tabBin` b
            JOIN `tabItem Price` ip ON ip.name = (
                SELECT ip2.name FROM `tabItem Price` ip2
                WHERE ip2.item_code = b.item_code
                  AND ip2.selling = 1
                  AND ip2.price_list = (
                      SELECT value FROM `tabSingles`
                      WHERE doctype = 'Selling Settings'
                        AND field = 'selling_price_list' LIMIT 1)
                ORDER BY (ip2.uom = b.stock_uom OR ip2.uom IS NULL OR ip2.uom = '') DESC,
                         ip2.modified DESC
                LIMIT 1
            )
            WHERE b.actual_qty > 0 {wh_filter}""",
        {"warehouse": warehouse},
        as_dict=True,
    )
    row = result[0] if result else {}
    return {
        "stock_value": float(row.get("stock_value") or 0),
        "item_count": int(row.get("item_count") or 0),
    }
