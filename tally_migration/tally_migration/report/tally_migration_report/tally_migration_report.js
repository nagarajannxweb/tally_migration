// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Tally Migration Report"] = {
	"filters": [
		{
			"fieldname": "doctype",
			"label": __("DocType"),
			"fieldtype": "Link",
			"options": "DocType",
			"reqd": 1,
			"default": "",
			"get_query": function() {
				return {
					"filters": {
						"name": ["in", get_mapped_doctypes()]
					}
				};
			}
		},
		{
			"fieldname": "from_date",
			"label": __("From Date"),
			"fieldtype": "Date",
			"reqd": 1
		},{
			"fieldname": "to_date",
			"label": __("To Date"),
			"fieldtype": "Date",	
			"reqd": 1		
		}		
	],	
};

function get_mapped_doctypes() {
	// Get list of DocTypes that have field mappings
	let doctypes = [];
	frappe.call({
		method: 'frappe.client.get_list',
		args: {
			doctype: 'Tally Field Mapping',
			fields: ['doctype_name']
		},
		async: false,
		callback: function(r) {
			if (r.message) {
				doctypes = r.message.map(d => d.doctype_name);
			}
		}
	});
	
	return doctypes.length > 0 ? doctypes : ['xxxxx']; // Return impossible value if empty
}

