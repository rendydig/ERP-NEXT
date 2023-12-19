import base64
import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import cstr
from datetime import datetime


def verify_request():
	woocommerce_settings = frappe.get_doc("Woocommerce Settings")
	sig = base64.b64encode(
		hmac.new(
			woocommerce_settings.secret.encode("utf8"), frappe.request.data, hashlib.sha256
		).digest()
	)

	if (
		frappe.request.data
		and not sig == frappe.get_request_header("X-Wc-Webhook-Signature", "").encode()
	):
		frappe.throw(_("Unverified Webhook Data"))
	frappe.set_user(woocommerce_settings.creation_user)


@frappe.whitelist(allow_guest=True)
def order(*args, **kwargs):
	try:
		_order(*args, **kwargs)
	except Exception:
		error_message = (
			frappe.get_traceback() + "\n\n Request Data: \n" + json.loads(frappe.request.data).__str__()
		)
		frappe.log_error("WooCommerce Error", error_message)
		raise


def _order(*args, **kwargs):
	woocommerce_settings = frappe.get_doc("Woocommerce Settings")
	if frappe.flags.woocomm_test_order_data:
		order = frappe.flags.woocomm_test_order_data
		event = "created"

	elif frappe.request and frappe.request.data:
		verify_request()
		try:
			order = json.loads(frappe.request.data)
		except ValueError:
			# woocommerce returns 'webhook_id=value' for the first request which is not JSON
			order = frappe.request.data
		event = frappe.get_request_header("X-Wc-Webhook-Event")

	else:
		return "success"

	if event == "created":
		sys_lang = frappe.get_single("System Settings").language or "en"
		raw_billing_data = order.get("billing")
		raw_shipping_data = order.get("shipping")
		customer_name = raw_billing_data.get("first_name") + " " + raw_billing_data.get("last_name")
		
		#customer
		link_customer_and_address(raw_billing_data, raw_shipping_data, customer_name)
		
		#order
		link_items(order.get("line_items"), woocommerce_settings, sys_lang)
		new_sales_order = create_sales_order(order, woocommerce_settings, customer_name, sys_lang)

		#payment
		date_paid = order.get("date_paid")
		if date_paid is not None and date_paid != "":
			if woocommerce_settings.is_auto_generate_payment_if_paid:
				new_sales_invoice = create_sales_invoice(new_sales_order, woocommerce_settings, customer_name, sys_lang)
				create_payment(order, new_sales_invoice, woocommerce_settings, customer_name, sys_lang)
			if woocommerce_settings.is_auto_reduce_stock_if_paid:
				create_delivery_note(new_sales_order, woocommerce_settings, customer_name, sys_lang)

#region customer and address
def link_customer_and_address(raw_billing_data, raw_shipping_data, customer_name):
	customer_woo_com_email = raw_billing_data.get("email")
	customer_exists = frappe.get_value("Customer", {"woocommerce_email": customer_woo_com_email})
	if not customer_exists:
		# Create Customer
		customer = frappe.new_doc("Customer")
	else:
		# Edit Customer
		customer = frappe.get_doc("Customer", {"woocommerce_email": customer_woo_com_email})
		old_name = customer.customer_name

	customer.customer_name = customer_name
	customer.woocommerce_email = customer_woo_com_email
	customer.flags.ignore_mandatory = True
	customer.save()

	if customer_exists:
		if customer_name != old_name:
			frappe.rename_doc("Customer", old_name, customer_name)
		
		for address_type in (
			"Billing",
			"Shipping",
		):
			try:
				address = frappe.get_doc(
					"Address", {"woocommerce_email": customer_woo_com_email, "address_type": address_type}
				)
				rename_address(address, customer)
			except (
				frappe.DoesNotExistError,
				frappe.DuplicateEntryError,
				frappe.ValidationError,
			):
				pass
	else:
		create_address(raw_billing_data, customer, "Billing")
		create_address(raw_shipping_data, customer, "Shipping")
		create_contact(raw_billing_data, customer)

def create_contact(data, customer):
	email = data.get("email", None)
	phone = data.get("phone", None)

	if not email and not phone:
		return

	contact = frappe.new_doc("Contact")
	contact.first_name = data.get("first_name")
	contact.last_name = data.get("last_name")
	contact.is_primary_contact = 1
	contact.is_billing_contact = 1

	if phone:
		contact.add_phone(phone, is_primary_mobile_no=1, is_primary_phone=1)

	if email:
		contact.add_email(email, is_primary=1)

	contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	contact.flags.ignore_mandatory = True
	contact.save()

def create_address(raw_data, customer, address_type):
	address = frappe.new_doc("Address")

	address.address_line1 = raw_data.get("address_1", "Not Provided")
	address.address_line2 = raw_data.get("address_2", "Not Provided")
	address.city = raw_data.get("city", "Not Provided")
	address.woocommerce_email = customer.woocommerce_email
	address.address_type = address_type
	address.country = frappe.get_value("Country", {"code": raw_data.get("country", "IN").lower()})
	address.state = raw_data.get("state")
	address.pincode = raw_data.get("postcode")
	address.phone = raw_data.get("phone")
	address.email_id = customer.woocommerce_email
	address.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	address.flags.ignore_mandatory = True
	address.save()

def rename_address(address, customer):
	old_address_title = address.name
	new_address_title = customer.name + "-" + address.address_type
	address.address_title = customer.customer_name
	address.save()

	frappe.rename_doc("Address", old_address_title, new_address_title)
#endregion

#region items
def link_items(items_list, woocommerce_settings, sys_lang):
	for item_data in items_list:
		item_woo_com_id = cstr(item_data.get("product_id"))

		if not frappe.db.get_value("Item", {"woocommerce_id": item_woo_com_id}, "name"):
			# Create Item
			item = frappe.new_doc("Item")
			item.item_code = _("woocommerce - {0}", sys_lang).format(item_woo_com_id)
			item.stock_uom = woocommerce_settings.uom or _("Nos", sys_lang)
			item.item_group = _("WooCommerce Products", sys_lang)

			item.item_name = item_data.get("name")
			item.woocommerce_id = item_woo_com_id
			item.flags.ignore_mandatory = True
			item.save()
#endregion

#region sales order
def create_sales_order(order, woocommerce_settings, customer_name, sys_lang):
	new_sales_order = frappe.new_doc("Sales Order")
	new_sales_order.customer = customer_name

	new_sales_order.po_no = new_sales_order.woocommerce_id = order.get("id")
	new_sales_order.naming_series = woocommerce_settings.sales_order_series or "SAL-ORD-WOO-"

	created_date = order.get("date_created").split("T")
	new_sales_order.transaction_date = created_date[0]
	delivery_after = woocommerce_settings.delivery_after_days or 7
	new_sales_order.delivery_date = frappe.utils.add_days(created_date[0], delivery_after)

	new_sales_order.company = woocommerce_settings.company

	set_items_in_sales_order(new_sales_order, woocommerce_settings, order, sys_lang)
	new_sales_order.flags.ignore_mandatory = True
	new_sales_order.insert()
	new_sales_order.submit()

	frappe.db.commit()

	return new_sales_order

def set_items_in_sales_order(new_sales_order, woocommerce_settings, order, sys_lang):
	company_abbr = frappe.db.get_value("Company", woocommerce_settings.company, "abbr")

	default_warehouse = _("Stores - {0}", sys_lang).format(company_abbr)
	if not frappe.db.exists("Warehouse", default_warehouse) and not woocommerce_settings.warehouse:
		frappe.throw(_("Please set Warehouse in Woocommerce Settings"))

	for item in order.get("line_items"):
		woocomm_item_id = item.get("product_id")
		found_item = frappe.get_doc("Item", {"woocommerce_id": cstr(woocomm_item_id)})

		ordered_items_tax = item.get("total_tax")

		new_sales_order.append(
			"items",
			{
				"item_code": found_item.name,
				"item_name": found_item.item_name,
				"description": found_item.item_name,
				"delivery_date": new_sales_order.delivery_date,
				"uom": woocommerce_settings.uom or _("Nos", sys_lang),
				"qty": item.get("quantity"),
				"rate": item.get("price"),
				"warehouse": woocommerce_settings.warehouse or default_warehouse,
			},
		)

		add_tax_details(
			new_sales_order, ordered_items_tax, "Ordered Item tax", woocommerce_settings.tax_account
		)

	# shipping_details = order.get("shipping_lines") # used for detailed order

	add_tax_details(
		new_sales_order, order.get("shipping_tax"), "Shipping Tax", woocommerce_settings.f_n_f_account
	)
	add_tax_details(
		new_sales_order,
		order.get("shipping_total"),
		"Shipping Total",
		woocommerce_settings.f_n_f_account,
	)

def add_tax_details(sales_order, price, desc, tax_account_head):
	sales_order.append(
		"taxes",
		{
			"charge_type": "Actual",
			"account_head": tax_account_head,
			"tax_amount": price,
			"description": desc,
		},
	)
#endregion

#region billing and payment
def create_sales_invoice(sales_order, woocommerce_settings, customer_name, sys_lang):
	new_sales_invoice = frappe.new_doc("Sales Invoice")
	new_sales_invoice.title = customer_name
	new_sales_invoice.naming_series = woocommerce_settings.sales_invoice_series or "ACC_SINV-WOO-"
	new_sales_invoice.customer = customer_name
	new_sales_invoice.customer_name = customer_name
	new_sales_invoice.company = woocommerce_settings.company
	

	set_items_in_sales_invoice(sales_order, new_sales_invoice, woocommerce_settings, sys_lang)

	new_sales_invoice.flags.ignore_mandatory = False
	new_sales_invoice.insert()
	new_sales_invoice.submit()
	return new_sales_invoice

def set_items_in_sales_invoice(sales_order, new_sales_invoice, woocommerce_settings, sys_lang):
	company_abbr = frappe.db.get_value("Company", woocommerce_settings.company, "abbr")
	default_account = _("Sales - {0}", sys_lang).format(company_abbr)

	for item in sales_order.items:
		new_sales_invoice.append(
			"items", 
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"uom": item.uom,
				"qty": item.qty,
				"rate": item.rate,
				"income_account": default_account,
				"sales_order": sales_order.name,
				"so_detail": item.name
			},
		)

def create_payment(order, sales_invoice, woocommerce_settings, customer_name, sys_lang):
	company_abbr = frappe.db.get_value("Company", woocommerce_settings.company, "abbr")

	new_payment = frappe.new_doc("Payment Entry")
	new_payment.naming_series = woocommerce_settings.payment_series or "ACC-PAY-WOO-"
	new_payment.title = customer_name
	new_payment.payment_type = "Receive"
	new_payment.party_type = "Customer"
	new_payment.party = customer_name
	new_payment.party_name = customer_name
	new_payment.paid_from = _("Debtors - {0}", sys_lang).format(company_abbr)
	new_payment.paid_to = woocommerce_settings.payment_account
	date_paid = order.get("date_paid")
	new_payment.reference_no = date_paid
	new_payment.reference_date = datetime.strptime(date_paid, "%Y-%m-%dT%H:%M:%S")
	new_payment.paid_amount = sales_invoice.base_grand_total
	new_payment.received_amount = sales_invoice.base_grand_total
	new_payment.append(
			"references", 
			{
				"reference_doctype": "Sales Invoice",
				"reference_name": sales_invoice.name,
				"total_amount": sales_invoice.base_grand_total,
				"outstanding_amount": 0,
				"allocated_amount": sales_invoice.base_grand_total,
			},
		)
	new_payment.flags.ignore_mandatory = False
	new_payment.insert()
	new_payment.submit()
#endregion
	
#region delivery note
def create_delivery_note(sales_order, woocommerce_settings, customer_name, sys_lang):
	new_delivery_note = frappe.new_doc("Delivery Note")
	new_delivery_note.title = customer_name
	new_delivery_note.naming_series = woocommerce_settings.delivery_note_series or "MAT-DN-WOO-"
	new_delivery_note.customer = customer_name
	new_delivery_note.company = sales_order.company
	new_delivery_note.currency = sales_order.currency
	new_delivery_note.conversion_rate = sales_order.conversion_rate
	new_delivery_note.selling_price_list = sales_order.selling_price_list
	new_delivery_note.price_list_currency = sales_order.price_list_currency
	new_delivery_note.plc_conversion_rate = sales_order.plc_conversion_rate

	set_items_in_delivery_note(sales_order, new_delivery_note, woocommerce_settings, customer_name, sys_lang)

	new_delivery_note.flags.ignore_mandatory = False
	new_delivery_note.insert()

	try:
		new_delivery_note.submit()
	except Exception:
		error_message = (frappe.get_traceback() + "\n\n Request Data: \n" + json.loads(frappe.request.data).__str__())
		frappe.log_error("WooCommerce Error", error_message)
		new_delivery_note.cancel()
		
	return new_delivery_note

def set_items_in_delivery_note(sales_order, new_delivery_note, woocommerce_settings, customer_name, sys_lang):	
	for item in sales_order.items:
		new_delivery_note.append(
			"items", 
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"description": item.description,
				"qty": item.qty,
				"uom": item.uom,
				"conversion_factor": item.conversion_factor,
				"against_sales_order": sales_order.name,
				"so_detail": item.name
			},
		)
#endregion