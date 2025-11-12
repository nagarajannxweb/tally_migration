# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate


def execute(filters=None):
	"""
	Generate a report showing Sales Invoice data mapped to Tally field names
	"""
	if not filters or not filters.get("doctype"):
		frappe.msgprint(_("Please select a DocType"))
		return [], []
	
	columns, data = get_columns(filters)	
	return columns, data



def get_columns(filters):
	"""Generate columns dynamically based on Tally Field Mapping"""
	doctype = filters.get("doctype")
	
	# Check if mapping exists
	if not frappe.db.exists("Tally Field Mapping", doctype):
		return []
	
	# Get the mapping document
	mapping_doc = frappe.get_doc("Tally Field Mapping", doctype)	
	tables = [mapping_doc.doctype_name] + list(set( [i.child_table_name for i in mapping_doc.field_mappings if i.is_child_table]	))
	fields = {frappe.scrub(i):[] for i in tables}	
	tally_fields = {}
	for i in mapping_doc.field_mappings:
		if i.child_table_name:
			tally_fields.setdefault(frappe.scrub(i.child_table_name), []).append(i.tally_field_name)
	
	columns = [{
			"fieldname": 'dr_cr',
			"label": 'Ledger Amount Dr/Cr',
			"fieldtype": "Data",
			"width": 150
		},{
			"fieldname": 'voucher_type',
			"label": 'Voucher Type Name',
			"fieldtype": "Data",
			"width": 150
		},{
			"fieldname": 'change_mode',
			"label": 'Change Mode',
			"fieldtype": "Data",
			"width": 150
		}]
	column_name = []
	where ={}
	all_fields = ["dr_cr"]
	for row in mapping_doc.field_mappings:	
		all_fields.append(f"`{frappe.scrub(row.tally_field_name)}`")
		if frappe.scrub(row.child_table_name) not in where:
			if row.is_child_table == 0:
				where[frappe.scrub(mapping_doc.doctype_name)] = f"WHERE ({frappe.scrub(mapping_doc.doctype_name)}.posting_date BETWEEN '{filters.get('from_date')}' AND '{filters.get('to_date')}') AND {frappe.scrub(mapping_doc.doctype_name)}.docstatus = 1"
			else:
				where[frappe.scrub(row.child_table_name)] = f""" 
				WHERE {frappe.scrub(row.child_table_name)}.parent IN (
					SELECT name
					FROM `tab{mapping_doc.doctype_name}`				
					WHERE 
					(posting_date BETWEEN '{filters.get('from_date')}' AND '{filters.get('to_date')}')
					  AND docstatus = 1
				)
				"""		
		if frappe.scrub(row.tally_field_name) not in column_name:
			columns.append({
				"fieldname": frappe.scrub(row.tally_field_name),
				"label": _(row.tally_field_name),
				"fieldtype": "Data",
				"width": 150
			})
			column_name.append(frappe.scrub(row.tally_field_name))
		for table in tables:
			if row.child_table_name == table:
				if row.ledger_entry_type in ['Cr', 'Dr']:
					fields[frappe.scrub(table)].append(f"'{row.ledger_entry_type}' AS dr_cr")
				# else:
				fields[frappe.scrub(table)].append(f"{frappe.scrub(table)}.{row.erp_field_name} AS '{frappe.scrub(row.tally_field_name)}'")
			else:
				if row.erp_field_name == "name":
					if row.is_child_table == 0:
						fields[frappe.scrub(table)].append(f"{frappe.scrub(table)}.parent AS {frappe.scrub(row.tally_field_name)}")
				else:	
					# if row.ledger_entry_type not in ['Cr', 'Dr']:	
						if row.tally_field_name not in tally_fields[frappe.scrub(table)]:
							fields[frappe.scrub(table)].append(f"NULL AS '{frappe.scrub(row.tally_field_name)}'")

	query = ""
	for idx, i in enumerate(tables):		
		query += f"""
		SELECT
		'{mapping_doc.voucher_type_name}' AS voucher_type,		
		{",".join(list(set(all_fields)))},
		'{mapping_doc.change_mode}' AS change_mode
		FROM (		
		SELECT {','.join(fields[frappe.scrub(i)])}
		FROM `tab{i}` AS {frappe.scrub(i)}
		"""
		query += " " + where.get(frappe.scrub(i), "")
		query += ") AS " + frappe.scrub(i)+str(idx)
		

		if idx < len(tables) - 1:
			query += " UNION ALL "
	query += """
		ORDER BY voucher_number, 
				CASE 
					WHEN voucher_date IS NULL THEN 2 
					ELSE 1 
				END;
		"""
	
	# frappe.throw(f"{query}")
	data = frappe.db.sql(query, as_dict=1)
	return columns, data
