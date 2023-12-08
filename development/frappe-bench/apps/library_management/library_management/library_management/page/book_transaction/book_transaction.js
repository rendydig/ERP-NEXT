frappe.pages['book-transaction'].on_page_load = function(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Book Transaction',
		single_column: true
	});

	let $btnPrimary = page.set_primary_action('New', () => create_new(), 'octicon octicon-plus')
	let $btnSecondary = page.set_secondary_action('Refresh', () => refresh(), 'octicon octicon-sync')

	$(frappe.render_template('book_transaction_helloworld', {title: 'Hello this is title'})).appendTo(page.main);
}