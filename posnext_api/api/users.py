import frappe
from frappe import _
from frappe.utils import flt, getdate


@frappe.whitelist()
def get_user_profile_data(start_date=None, end_date=None):
    """Return profile data and sales totals for the logged-in user."""
    user = frappe.session.user

    # User name and job title
    full_name = frappe.db.get_value("User", user, "full_name") or user
    employee = frappe.db.get_value(
        "Employee", {"user_id": user}, ["employee_name", "designation"], as_dict=True
    )
    job_title = ""
    if employee:
        job_title = employee.get("designation") or ""
        full_name = employee.get("employee_name") or full_name

    # Total sales in date range
    total_sales = 0
    filters = {"docstatus": 1, "owner": user}
    if start_date and end_date:
        filters["posting_date"] = ["between", [getdate(start_date), getdate(end_date)]]
    elif start_date:
        filters["posting_date"] = [">=", getdate(start_date)]
    elif end_date:
        filters["posting_date"] = ["<=", getdate(end_date)]

    sales = frappe.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[{"SUM": "grand_total", "as": "total"}],
    )
    if sales and sales[0].get("total"):
        total_sales = flt(sales[0]["total"])

    # Also check POS Invoice
    pos_sales = frappe.get_all(
        "POS Invoice",
        filters=filters,
        fields=[{"SUM": "grand_total", "as": "total"}],
    )
    if pos_sales and pos_sales[0].get("total"):
        total_sales += flt(pos_sales[0]["total"])

    return {
        "success": "1",
        "totalSales": total_sales,
        "daily_target": "0",
        "name": full_name,
        "job_title": job_title,
    }
