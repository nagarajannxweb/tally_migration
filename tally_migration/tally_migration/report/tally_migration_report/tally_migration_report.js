// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

frappe.query_reports["Tally Migration Report"] = {
    filters: [
		{
			fieldname: "doctype",
			label: __("Tally Field Mapping"),
			fieldtype: "Link",
			options: "Tally Field Mapping",
			reqd: 1,
			change: load_dynamic_filters
		},

		// placeholders
		{ fieldname: "dyn_1", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_2", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_3", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_4", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_5", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_6", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_7", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_8", label: "", fieldtype: "Data", hidden: 1 },
		{ fieldname: "dyn_9", label: "", fieldtype: "Data", hidden: 1 },
	],
	onload: function(report) {

        report.page.add_inner_button("Update Tally Status", function () {

            frappe.call({
                method: "tally_migration.tally_migration.report.tally_migration_report.tally_migration_report.update_tally_creation_status",
                args: {
                    doctype: "Purchase Invoice"
                },
                callback: function (r) {
                    if (!r.exc) {
                        frappe.msgprint("Updated Successfully");
                    }
                }
            });

        });

    }
};

function load_dynamic_filters() {
    let doctype = frappe.query_report.get_filter_value("doctype");
    if (!doctype) return;

    frappe.call({
        method: "tally_migration.tally_migration.report.tally_migration_report.tally_migration_report.set_filters",
        args: { doctype },
        callback: function(r) {
            if (!r.message) return;
			console.log("ji")
            apply_filters_to_placeholders(r.message);
        }
    });
}

function apply_filters_to_placeholders(fields) {
    let slots = [
        "dyn_1","dyn_2","dyn_3","dyn_4","dyn_5",
        "dyn_6","dyn_7","dyn_8","dyn_9"
    ];

	frappe.query_reports["Tally Migration Report"].filters[0] = 		{
			fieldname: "doctype",
			label: __("Tally Field Mapping"),
			fieldtype: "Link",
			options: "Tally Field Mapping",
			reqd: 1,
			change: load_dynamic_filters,
			default: frappe.query_report.get_filter("doctype").value
		},
    fields.forEach((fld, idx) => {
        let slot = slots[idx];
        if (!slot) return;
		frappe.query_reports["Tally Migration Report"].filters[idx+1] = {
                ...fld
            };
    });

    // Reinitialize all filters
    frappe.query_report.setup_filters();
    
    // Show only the configured ones
    fields.forEach((fld, idx) => {
        let slot = slots[idx];
        let f = frappe.query_report.get_filter(slot);
        if (f) {
            f.$wrapper.show();
        }
    });
}


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

