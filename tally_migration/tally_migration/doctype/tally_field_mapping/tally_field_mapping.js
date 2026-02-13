// Copyright (c) 2025, Frappe Technologies and contributors
// For license information, please see license.txt

let my_global_var = null;

frappe.ui.form.on('Tally Field Mapping', {
	refresh: function(frm) {

        frm.add_custom_button(
            "Confirm Tally Creation",
            () => {
                frappe.call({					
                    method: "tally_migration.tally_migration.doctype.tally_field_mapping.tally_field_mapping.confirm_tally_creation",
                    args: {
                        tally_field_mapping: frm.doc.name						
                    },
                    freeze: true,
                    callback(r) {
                        if (!r.exc) {
                            frappe.msgprint(r.message);
                            frm.reload_doc();
                        }
                    }
                });
            }
        );

        frm.add_custom_button(
            "Revert Tally Creation",
            () => {
                frappe.call({
                    method: "tally_migration.tally_migration.doctype.tally_field_mapping.tally_field_mapping.revert_tally_creation",
                    args: {
                        tally_field_mapping: frm.doc.name
                    },
                    freeze: true,
                    callback(r) {
                        if (!r.exc) {
                            frappe.msgprint(r.message);
                            frm.reload_doc();
                        }
                    }
                });
            }
        );

		// Add custom buttons or actions if needed
		if (!frm.is_new()) {
			frm.add_custom_button(__('View Tally Migration Report'), function() {
				frappe.set_route('query-report', 'Tally Migration Report', {
					'doctype': frm.doc.name1
				});
			});
		}
		if (frm.doc.doctype_name) {						
			frappe.call({
				method: 'tally_migration.tally_migration.doctype.tally_field_mapping.tally_field_mapping.get_doctype_fields',
				args: {
					doctype: cur_frm.doc.doctype_name
				}
			}).then((r) => {
				if (r.message) {
					frappe.meta.get_docfield('Tally Field Mapping Item', 'erp_field', cur_frm.doc.name).options = r.message.map(r=>r.label);
					frappe.meta.get_docfield('Tally Field Mapping Item', 'erp_field').options = r.message.map(r=>r.label);
					my_global_var = r.message
                    cur_frm.refresh_field('field_mappings');					
				}
			});
		}
	},
	doctype_name: function(frm) {		
		if (frm.doc.doctype_name) {						
			frappe.call({
				method: 'tally_migration.tally_migration.doctype.tally_field_mapping.tally_field_mapping.get_doctype_fields',
				args: {
					doctype: cur_frm.doc.doctype_name
				}
			}).then((r) => {
				if (r.message) {
					frappe.meta.get_docfield('Tally Field Mapping Item', 'erp_field', cur_frm.doc.name).options = r.message.map(r=>r.label);
					frappe.meta.get_docfield('Tally Field Mapping Item', 'erp_field').options = r.message.map(r=>r.label);
					my_global_var = r.message
                    cur_frm.refresh_field('field_mappings');					
				}
			});
		}else{
			frappe.msgprint(__('Please select a Doctype first'));
		}
		cur_frm.clear_table("field_mappings")
		cur_frm.refresh_field("field_mappings")

	}
		
});

frappe.ui.form.on('Tally Field Mapping Item', {
	erp_field: function(frm, cdt, cdn) {
		let row = frappe.get_doc(cdt, cdn);

		my_global_var.forEach(field => {
			if (field.label === row.erp_field) {
				if (field.is_child_table) {
					frappe.model.set_value(cdt, cdn, 'is_child_table', field.is_child_table);
					frappe.model.set_value(cdt, cdn, 'child_table_name', field.parent);	
					frappe.model.set_value(cdt, cdn, 'options', field.options);				
				}		
				frappe.model.set_value(cdt, cdn, 'erp_field_name', field.fieldname);		
				frappe.model.set_value(cdt, cdn, 'erp_field_cdn', field.field_cdn);		
				frappe.model.set_value(cdt, cdn, 'erp_field_type', field.fieldtype);
				frappe.model.set_value(cdt, cdn, 'options', field.options);
			}
		})
			
	}
});