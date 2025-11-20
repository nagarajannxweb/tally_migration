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
	columns, data = get_columns_and_data(filters)		
	return columns, data


def get_columns_and_data(filters):
	parent = filters.get("doctype")	
	tall_field_mapping = frappe.get_doc("Tally Field Mapping", parent)	
	tables = []
	tally_fields = []
	query_data = {}
	column_name = []
	columns = []
	order_by = None
	for i in tall_field_mapping.field_mappings:
		if frappe.scrub(i.tally_field_name) not in column_name:
			columns.append({
				"fieldname": frappe.scrub(i.tally_field_name),
				"label": _(i.tally_field_name),
				"fieldtype": "Data",
				"width": 150
			})
			column_name.append(frappe.scrub(i.tally_field_name))
		if i.child_table_name != parent:
			tables.append(i.child_table_name)
		if f"`{frappe.scrub(i.tally_field_name)}`" not in tally_fields:
			tally_fields.append(f"`{frappe.scrub(i.tally_field_name)}`")
		if i.child_table_name:
			if i.child_table_name not in query_data:
				query_data[i.child_table_name] = {"fields":{}, "alias":""}
		if i.erp_field == "ID":
			order_by = frappe.scrub(i.tally_field_name)
	
	tables = list(set(tables))	
	
	tables.insert(0, parent)

	for idx, table in enumerate(tables):		
		query_data[table]["alias"] = frappe.scrub(table)	
		for i in tall_field_mapping.field_mappings:		
			col_field_name = frappe.scrub(i.tally_field_name)
			if i.child_table_name == table:				
				query_data[table]["fields"][col_field_name] = f"{query_data[table]["alias"]}.{i.erp_field_name} as `{col_field_name}`"
			else:
				if col_field_name not in query_data[table]["fields"]:
					if i.value:
						query_data[table]["fields"][col_field_name] = f"{i.value} as `{col_field_name}`"
					elif i.erp_field == "ID":
						query_data[table]["fields"][col_field_name] = f"{query_data[table]["alias"]}.parent as `{col_field_name}`"
					else:
						query_data[table]["fields"][col_field_name] = f"NULL as `{col_field_name}`"
	query = ""	
	parent_query = None
	for idx, key in enumerate(tables):
		query += f"SELECT {','.join([query_data[key]['fields'][i] for i in query_data[key]['fields']])} FROM `tab{key}` AS {query_data[key]['alias']}"
		if key == filters.get('doctype'):
			query_parts = []			
			for fltr_key, value in filters.items():
				if fltr_key != "doctype":
					query_parts.append(f"{query_data[key]['alias']}.{fltr_key} = '{value}'")
			if query_parts:
				query += " WHERE " + " AND ".join(query_parts)
				parent_query = f"""
				SELECT {query_data[key]['alias']}.name
				FROM `tab{key}` AS {query_data[key]['alias']}
				WHERE {'AND'.join(query_parts)}
				"""
		else:
			query += f""" WHERE {query_data[key]['alias']}.parent in (
			{parent_query}
			)"""
				

			
		if idx < len(tables) - 1:
			query += " UNION ALL "		


	query1 = f"""
			SELECT
				{','.join(tally_fields)}
			FROM({query})		
			AS final_data									
			"""
	if order_by:
		query1 += f"ORDER BY {order_by}"

	data = frappe.db.sql(query1, as_dict=1)
	return columns, data

# def query_builder(filters=None, parent= None, 
# 				  tall_field_mapping=None, tables=None, 
# 				  tally_fields=None, query_data=None, column_name=None, columns=None, order_by=None):

			

@frappe.whitelist()
def set_filters(doctype):
	tall_field_mapping = frappe.get_doc("Tally Field Mapping", doctype)	
	filters = []
	for i in tall_field_mapping.field_mappings:
		if i.is_filter:
			filters.append({
				"fieldname": frappe.scrub(i.erp_field_name),
				"label": i.erp_field,
				"fieldtype": i.erp_field_type,
				"options": i.options,
				"reqd": 0,
				"default": "",
			})
	return filters

