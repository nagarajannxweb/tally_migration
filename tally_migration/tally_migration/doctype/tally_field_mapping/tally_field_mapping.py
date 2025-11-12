# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TallyFieldMapping(Document):
	def before_save(self):
		self.set_parent_doctype()
	def set_parent_doctype(self):
		for i in self.field_mappings:
			if i.is_child_table == 0:
				i.child_table_name = self.doctype_name
		
	

	



@frappe.whitelist()
def get_doctype_fields(doctype):
	"""Get all fields for a specific DocType including child table fields"""
	if not doctype:
		return []
	
	try:
		meta = frappe.get_meta(doctype)
		fields = []
		
		# Add parent DocType fields
		for field in meta.fields:
			if field.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML"]:
				fields.append({
					"label": field.label or field.fieldname,
					"fieldname": field.fieldname,
					"fieldtype": field.fieldtype,
					"field_cdn": field.name,
					"parent": doctype,
					"is_child_table": 0
				})
				
				# If it's a table field, add its child fields
				if field.fieldtype == "Table" and field.options:
					child_meta = frappe.get_meta(field.options)
					for child_field in child_meta.fields:
						if child_field.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML"]:
							fields.append({
								"label": f"{child_field.label or child_field.fieldname} ({field.label})",
								"fieldname": child_field.fieldname,
								"fieldtype": child_field.fieldtype,
								"parent": field.options,
								"is_child_table": 1,
								"field_cdn": child_field.name,
								"child_table_name": field.options
							})
		fields.append({
					"label": "ID",
					"fieldname": "name",
					"fieldtype": "Data",					
					"parent": doctype,
					"is_child_table": 0
				})
		return fields
	except Exception as e:
		frappe.log_error(f"Error fetching fields for {doctype}: {str(e)}")
		return []
	

# Additional method to add to tally_field_mapping.py

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_filtered_docfields(doctype, txt, searchfield, start, page_len, filters):
	"""Custom query to filter DocFields based on parent DocType"""
	parent_doctype = filters.get('parent_doctype')
	
	if not parent_doctype:
		return []
	
	try:
		meta = frappe.get_meta(parent_doctype)
		field_list = []
		
		# Add parent DocType fields
		for field in meta.fields:
			if field.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML"]:
				if txt.lower() in field.fieldname.lower() or txt.lower() in (field.label or '').lower():
					# Get the DocField name
					docfield_name = frappe.db.get_value(
						'DocField',
						{'parent': parent_doctype, 'fieldname': field.fieldname},
						'name'
					)
					if docfield_name:
						field_list.append([docfield_name, f"{field.label or field.fieldname} ({field.fieldtype})"])
				
				# If it's a table field, add its child fields
				if field.fieldtype == "Table" and field.options:
					child_meta = frappe.get_meta(field.options)
					for child_field in child_meta.fields:
						if child_field.fieldtype not in ["Section Break", "Column Break", "Tab Break", "HTML"]:
							if txt.lower() in child_field.fieldname.lower() or txt.lower() in (child_field.label or '').lower():
								# Get the child DocField name
								child_docfield_name = frappe.db.get_value(
									'DocField',
									{'parent': field.options, 'fieldname': child_field.fieldname},
									'name'
								)
								if child_docfield_name:
									field_list.append([
										child_docfield_name,
										f"{field.label} > {child_field.label or child_field.fieldname} ({child_field.fieldtype})"
									])
		
		# Return limited results
		return field_list[:page_len]
	
	except Exception as e:
		frappe.log_error(f"Error in get_filtered_docfields: {str(e)}")
		return []