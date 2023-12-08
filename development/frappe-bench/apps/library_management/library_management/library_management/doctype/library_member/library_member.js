// Copyright (c) 2023, Ahmad Saifuddin Azhar and contributors
// For license information, please see license.txt

frappe.ui.form.on('Library Member', {
	refresh: function(frm) {
		frm.add_custom_button('Create Membership', () => {
				frappe.new_doc('Library Membership', {
						library_member: frm.doc.name
				})
		})
	}
});
