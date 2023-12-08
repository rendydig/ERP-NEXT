# Copyright (c) 2023, Ahmad Saifuddin Azhar and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns, data = [], []

	columns = [
        {
            'fieldname': 'date',
            'label': 'Date',
            'fieldtype': 'Date',
        },
        {
            'fieldname': 'quantity',
            'label': 'Quantity',
            'fieldtype': 'Int',
        },
    ]
	
	data = frappe.db.get_all('Test DocType', ['date', 'quantity'])
	chart_data = get_chart_data(data)
	
	return columns, data, None, chart_data

def get_chart_data(data):
	return {
		"data": {
			"labels": ['Date', 'Quantity'],
			"datasets": data,
		},
		"type": "line",
		"lineOptions": {"regionFill": 1},
		"fieldtype": "Currency",
    }
