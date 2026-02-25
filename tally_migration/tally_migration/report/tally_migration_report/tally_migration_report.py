# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from collections import Counter

def execute(filters=None):
	if not filters or not filters.get("doctype"):
		frappe.msgprint(_("Please select a DocType"))
		return [], []

	columns, data = get_columns_and_data(filters)

	# Tally does not understand HTML line-break tags inside address fields,
	# so we replace them with real newline characters.
	_clean_address_field(data)

	return columns, data


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def get_columns_and_data(filters):
	"""
	Build the report columns and fetch all rows from the database.

	Steps:
	  1. Load the Tally Field Mapping document for the selected DocType.
	  2. Derive the column list for the report grid.
	  3. Discover which DB tables are involved (parent + child tables).
	  4. For every table, build one *or more* SELECT statements.
	     Multiple SELECTs per table are needed when the same table contributes
	     more than one ledger row (e.g. Supplier row AND Rounding Adjustment row
	     both come from the Purchase Invoice parent table).
	  5. Join all SELECTs with UNION ALL and wrap them in an outer SELECT that
	     picks only the Tally columns, ordered for correct Tally import sequence.
	  6. Post-process negative amounts so Dr/Cr signs are always positive.
	"""
	mapping_doc = frappe.get_doc("Tally Field Mapping", filters.get("doctype"))

	columns = _build_columns(mapping_doc)
	tally_fields = _get_tally_field_list(mapping_doc)
	tables = _get_ordered_tables(mapping_doc)
	parent_filter_sql = _build_parent_filter_sql(mapping_doc, filters)

	# Build one or more SELECT blocks per table and join with UNION ALL.
	# table_index is passed so each block gets a unique sort_order value that
	# preserves the mapping-defined sequence in the final ORDER BY.
	union_parts = []
	for table_index, table in enumerate(tables):
		is_parent = (table == mapping_doc.doctype_name)
		select_blocks = _build_select_blocks_for_table(
			table, mapping_doc, is_parent, parent_filter_sql, filters, table_index
		)
		union_parts.extend(select_blocks)

	final_sql = _build_final_sql(union_parts, tally_fields, mapping_doc)

	frappe.log_error("Tally Migration Report SQL", final_sql)
	data = frappe.db.sql(final_sql, as_dict=1)

	_fix_negative_amounts(data, mapping_doc.doctype_name)
	
	return columns, data


# ---------------------------------------------------------------------------
# Column helpers
# ---------------------------------------------------------------------------

def _build_columns(mapping_doc):
	"""
	Return the list of column dicts for the Frappe report grid.

	We deduplicate by tally field name so the same Tally column (e.g.
	"Ledger Name") does not appear twice even when multiple ERP fields
	map to it.  The Dr/Cr column is injected right after the first column
	that carries a ledger_entry_type.
	"""
	columns = []
	seen = set()

	for mapping in mapping_doc.field_mappings:
		scrubbed = frappe.scrub(mapping.tally_field_name)

		if scrubbed not in seen:
			columns.append({
				"fieldname": scrubbed,
				"label": _(mapping.tally_field_name),
				"fieldtype": "Data",
				"width": 150,
			})
			seen.add(scrubbed)

		# Add the Dr/Cr column once, the first time we encounter a ledger mapping
		if mapping.ledger_entry_type and "ledger_amount_dr/cr" not in seen:
			columns.append({
				"fieldname": "ledger_amount_dr/cr",
				"label": _("Ledger Amount Dr/Cr"),
				"fieldtype": "Data",
				"width": 150,
			})
			seen.add("ledger_amount_dr/cr")

	return columns


def _get_tally_field_list(mapping_doc):
	"""
	Return backtick-quoted column names for the outer SELECT.

	Example: ['`voucher_date`', '`ledger_name`', '`ledger_amount`', '`ledger_amount_dr/cr`']
	"""
	fields = []
	seen = set()

	for mapping in mapping_doc.field_mappings:
		col = f"`{frappe.scrub(mapping.tally_field_name)}`"
		if col not in seen:
			fields.append(col)
			seen.add(col)

		if mapping.ledger_entry_type and "`ledger_amount_dr/cr`" not in seen:
			fields.append("`ledger_amount_dr/cr`")
			seen.add("`ledger_amount_dr/cr`")

	return fields


# ---------------------------------------------------------------------------
# Table / query-structure helpers
# ---------------------------------------------------------------------------

def _get_ordered_tables(mapping_doc):
	"""
	Return an ordered list of DB table names: parent table first, then children.

	Frappe stores child rows in separate tables (e.g. 'Purchase Invoice Item').
	We put the parent first so the UNION ALL result is grouped naturally.
	"""
	seen = set()
	tables = [mapping_doc.doctype_name]
	seen.add(mapping_doc.doctype_name)

	for mapping in mapping_doc.field_mappings:
		tbl = mapping.child_table_name
		if tbl and tbl != mapping_doc.doctype_name and tbl not in seen:
			tables.append(tbl)
			seen.add(tbl)

	return tables


def _build_parent_filter_sql(mapping_doc, filters):
	"""
	Build a sub-SELECT that returns the names of parent documents matching
	all active filters.  Child-table queries use this sub-SELECT in their
	WHERE … parent IN (…) clause.

	Example output:
	  SELECT purchase_invoice.name
	  FROM `tabPurchase Invoice` AS purchase_invoice
	  WHERE purchase_invoice.docstatus = '1'
	    AND purchase_invoice.custom_created_in_tally = '0'
	"""
	alias = frappe.scrub(mapping_doc.doctype_name)
	conditions = _collect_filter_conditions(mapping_doc, filters, alias)

	where_clause = ""
	if conditions:
		where_clause = "WHERE " + " AND ".join(conditions)

	return f"""
		SELECT {alias}.name
		FROM `tab{mapping_doc.doctype_name}` AS {alias}
		{where_clause}
	"""


def _collect_filter_conditions(mapping_doc, filters, alias):
	"""
	Gather all WHERE conditions for the parent table from two sources:
	  1. Filters passed in by the user through the report UI.
	  2. Hardcoded default filters stored in the Tally Field Mapping document
	     (e.g. docstatus = 1, custom_created_in_tally = 0).
	"""
	conditions = []

	# User-supplied filters (skip the 'doctype' key which selects the mapping)
	for key, value in filters.items():
		if key != "doctype":
			conditions.append(f"{alias}.{key} = '{value}'")

	# Default filters from the mapping document
	for f in mapping_doc.filters:
		conditions.append(f"{alias}.{f.field_name} = '{f.default}'")

	return conditions


# ---------------------------------------------------------------------------
# SELECT block builders
# ---------------------------------------------------------------------------

def _build_select_blocks_for_table(table, mapping_doc, is_parent, parent_filter_sql, filters, table_index=0):
	"""
	Return a list of SQL SELECT strings for one DB table.

	WHY a list?
	  A single ERP table can feed multiple Tally ledger rows.  For example, the
	  Purchase Invoice parent table may contribute:
	    • One row for the Supplier (Cr)
	    • One row for Rounding Adjustment (Dr)
	  Each of those becomes its own SELECT so they appear as separate lines in
	  the Tally import file.

	HOW we detect "multiple ledger rows":
	  We group all field_mappings that belong to this table by their
	  'ledger group index' — every time a mapping has a ledger_entry_type we
	  treat it as starting a new ledger row group.  Non-ledger fields (like
	  Voucher Date, Voucher Number) are shared across all groups.

	sort_order:
	  Every SELECT gets a literal integer column `sort_order` so the outer
	  ORDER BY can guarantee the exact row sequence defined in the mapping,
	  regardless of how MySQL/MariaDB chooses to return UNION ALL results.

	  sort_order = table_index * 1000 + group_index_within_table
	    • table_index — position of this table in the tables list
	                    (parent=0, first child=1, second child=2 …)
	    • group_index — position of this ledger group within the table
	                    (Supplier=0, RoundOff=1 for the parent table)

	  This guarantees for Purchase Invoice:
	    Parent Supplier   → sort_order 0
	    Parent RoundOff   → sort_order 1
	    Items child rows  → sort_order 1000, 1001 …
	    Tax child rows    → sort_order 2000, 2001 …
	"""
	alias = frappe.scrub(table)

	# Separate the mappings that belong to this table from the rest
	own_mappings = [m for m in mapping_doc.field_mappings if m.child_table_name == table]
	other_mappings = [m for m in mapping_doc.field_mappings if m.child_table_name != table]

	# Split own_mappings into ledger groups.
	# Each group represents one UNION ALL row (one Tally ledger entry).
	ledger_groups = _split_into_ledger_groups(own_mappings)

	select_blocks = []
	for group_index, group in enumerate(ledger_groups):
		# sort_order ensures rows appear in mapping-defined sequence within each voucher
		sort_order = table_index * 1000 + group_index
		fields_sql = _build_field_expressions(
			table, alias, group, other_mappings, mapping_doc
		)
		where_sql = _build_where_clause(
			table, alias, mapping_doc, is_parent, parent_filter_sql, filters
		)
		select_blocks.append(
			f"SELECT {', '.join(fields_sql + [f'{sort_order} AS sort_order', 'creation'])} "
			f"FROM `tab{table}` AS {alias} {where_sql}"
		)

	return select_blocks


def _split_into_ledger_groups(own_mappings):
	"""
	Divide a table's own field mappings into ledger groups.

	A "ledger group" = one Tally import row.  Each group is anchored by a
	mapping whose `ledger_entry_type` is set (i.e. a "Ledger Amount" row in
	the mapping table).  All mappings that appear *between* two such anchors
	(or before the first anchor) belong to that anchor's group.

	Mappings that appear AFTER the last anchor (trailing non-ledger rows) are
	treated as shared header fields and appended to every group — they carry
	things like Voucher Date, Voucher Number, Change Mode that should repeat
	on every output row.

	Why not just split on ledger_entry_type == True?
	─────────────────────────────────────────────────
	In the Tally Field Mapping table, "Ledger Name" (e.g. Supplier, Round Off)
	has NO ledger_entry_type — only the paired "Ledger Amount" row does.
	So if we put all non-ledger-entry-type rows into a shared "header" pool,
	both Supplier and Round Off - AB end up in the header and the dict lookup
	in _build_field_expressions makes the second one overwrite the first.

	Instead we scan the mapping list sequentially and bucket each mapping into
	the "current open group".  A new group opens each time we see a mapping
	with ledger_entry_type set (that mapping closes the current group).

	Example — Purchase Invoice parent table (rows in idx order):
	  idx 1  Voucher Date        (no ledger_entry_type) → pre-header
	  idx 2  Voucher Type Name   (no ledger_entry_type) → pre-header
	  idx 3  Voucher Number      (no ledger_entry_type) → pre-header
	  idx 4  Buyer/Supplier Addr (no ledger_entry_type) → pre-header
	  idx 5  Ledger Name=Supplier (no ledger_entry_type)→ open group 1
	  idx 6  Ledger Amount       ledger_entry_type='Cr' → CLOSES group 1
	  idx 11 Ledger Name=Round Off (no ledger_entry_type) → open group 2
	  idx 12 Ledger Amount       ledger_entry_type='Dr' → CLOSES group 2
	  idx N  Change Mode         (no ledger_entry_type) → trailing header

	Output groups:
	  Group 1: [VoucherDate, VoucherTypeName, VoucherNumber, Address,
	            LedgerName=Supplier, LedgerAmount=Cr, ChangeMode]
	  Group 2: [VoucherDate, VoucherTypeName, VoucherNumber, Address,
	            LedgerName=RoundOff,  LedgerAmount=Dr, ChangeMode]
	"""
	if not own_mappings:
		return []

	# ── Pass 1: find anchor positions (rows that have ledger_entry_type) ──────
	anchor_indices = [i for i, m in enumerate(own_mappings) if m.ledger_entry_type]

	if not anchor_indices:
		# No ledger entries on this table at all — one group with everything
		return [list(own_mappings)]

	# ── Pass 2: split into three zones ──────────────────────────────────────
	first_anchor = anchor_indices[0]
	last_anchor  = anchor_indices[-1]

	# Identify which tally column names are "ledger columns" — i.e. they appear
	# in at least one mapping that IS part of a ledger pair (the anchor itself,
	# or the Ledger Name row immediately before an anchor).
	# Typically: {'ledger_name', 'ledger_amount'}
	# These must NOT be treated as shared header fields because each ledger group
	# has its own distinct value for them.
	ledger_col_names = set()
	for anchor_pos in anchor_indices:
		# The anchor row itself (e.g. Ledger Amount)
		ledger_col_names.add(frappe.scrub(own_mappings[anchor_pos].tally_field_name))
		# The row(s) immediately before the anchor that share the same "pair"
		# (e.g. Ledger Name). We walk backwards from the anchor to the previous
		# anchor (or start) and collect any rows whose scrubbed tally name
		# appears more than once across all own_mappings — those are ledger cols.
	# Simpler: count how many times each tally col name appears in own_mappings.
	# Cols that appear more than once are ledger cols (they repeat per group).
	col_counts = Counter(frappe.scrub(m.tally_field_name) for m in own_mappings)
	for col, count in col_counts.items():
		if count > 1:
			ledger_col_names.add(col)

	# Pre-header: rows BEFORE the first anchor whose tally col is NOT a ledger col.
	# These are shared fields (Voucher Date, Voucher Number, Address, etc.) that
	# must appear on every output row.
	pre_header_fields = [
		m for m in own_mappings[:first_anchor]
		if frappe.scrub(m.tally_field_name) not in ledger_col_names
	]

	# Trailing fields: everything AFTER the last anchor (e.g. Change Mode).
	# Also must not be ledger cols (safety check).
	trailing_fields = [
		m for m in own_mappings[last_anchor + 1:]
		if frappe.scrub(m.tally_field_name) not in ledger_col_names
	]

	# ── Pass 3: build one group per anchor ────────────────────────────────────
	# Each group = pre_header + the slice between the previous anchor and this
	# anchor (i.e. the Ledger Name + Ledger Amount pair) + trailing_fields.
	groups = []
	for i, anchor_pos in enumerate(anchor_indices):
		# For the first group, the "previous anchor" is conceptually before the
		# start of the list (-1), so the middle slice begins at index 0 of
		# own_mappings.  For subsequent groups it starts just after the previous
		# anchor.
		prev_anchor = anchor_indices[i - 1] if i > 0 else -1

		# The middle slice: Ledger Name + Ledger Amount for this particular entry
		# e.g. [LedgerName=Supplier, LedgerAmount=Cr]  or  [LedgerName=RoundOff, LedgerAmount=Dr]
		# We keep only the rows that ARE ledger cols (the shared header rows have
		# already been captured in pre_header_fields above).
		middle_rows = [
			m for m in own_mappings[prev_anchor + 1 : anchor_pos + 1]
			if frappe.scrub(m.tally_field_name) in ledger_col_names
		]

		groups.append(pre_header_fields + middle_rows + trailing_fields)

	return groups


def _build_field_expressions(table, alias, group_mappings, other_mappings, mapping_doc):
	"""
	Build the list of SQL column expressions for one SELECT block.

	For columns that belong to THIS table's current group → use the real field
	  or a literal value.
	For all other columns → use NULL (keeps column count identical across all
	  UNION ALL branches).

	Special cases:
	  • mapping.value set       → emit SQL string literal  'SomeValue'
	  • mapping.erp_field="ID"  → emit alias.name  (parent PK)
	  • ledger_entry_type set on a tax table → CASE on add_deduct_tax
	  • ledger_entry_type set on other tables → emit literal 'Dr' / 'Cr'

	WHY we use a list scan instead of a dict:
	  The same Tally column name (e.g. "ledger_name") can appear more than once
	  in a group (theoretically).  Using a dict would lose duplicates.  More
	  importantly, we need to map each OUTPUT column position to exactly one
	  group mapping — we do that by scanning group_mappings for a match each
	  time rather than building a dict upfront.
	"""
	# All distinct tally column names, in definition order — one per output column
	all_col_names = _ordered_unique_tally_cols(mapping_doc)

	# Build a lookup: col_name → the ONE mapping in this group that provides it.
	# If multiple mappings in the group share the same tally col name, the LAST
	# one wins (matches idx ordering — the more specific/later mapping takes
	# precedence).  In practice each group has at most one mapping per col.
	group_col_map = {}
	for m in group_mappings:
		group_col_map[frappe.scrub(m.tally_field_name)] = m

	expressions = []
	for col in all_col_names:
		if col in group_col_map:
			expressions.append(_expr_for_own_mapping(col, alias, group_col_map[col]))
		else:
			# Column not provided by this group — emit NULL or a cross-table fallback
			expressions.append(_find_fallback_expression(col, alias, other_mappings, mapping_doc))

	# Append the Dr/Cr column — present only when this group has a ledger anchor
	ledger_mapping = next((m for m in group_mappings if m.ledger_entry_type), None)
	if ledger_mapping:
		expressions.append(_dr_cr_expression(alias, ledger_mapping))

	return expressions


def _expr_for_own_mapping(col, alias, mapping):
	"""
	Build a SQL expression for a field that belongs to the current table.

	Priority:
	  1. Static value defined in the mapping  →  'literal_value' AS `col`
	  2. ERP field type is "ID"               →  alias.name AS `col`  (parent PK)
	  3. Normal ERP field                     →  alias.field_name AS `col`
	"""
	if mapping.value:
		return f"'{mapping.value}' AS `{col}`"
	elif mapping.erp_field == "ID":
		# For parent table the primary key column is `name`;
		# for child tables the link back to parent is `parent` — but since
		# ID mappings are only placed on the parent table this is always .name
		return f"{alias}.name AS `{col}`"
	else:
		return f"{alias}.{mapping.erp_field_name} AS `{col}`"


def _find_fallback_expression(col, alias, other_mappings, mapping_doc):
	"""
	For a column that is NOT contributed by the current table, decide what
	SQL expression to emit so the UNION ALL column count stays consistent.

	Rules:
	  • If the column is the voucher_number / ID column → emit alias.parent
	    so child rows still link back to the parent document.
	  • If a static value exists in any mapping for this column → emit that literal.
	  • Otherwise → emit NULL.
	"""
	for m in other_mappings:
		if frappe.scrub(m.tally_field_name) == col:
			if m.value:
				return f"'{m.value}' AS `{col}`"
			elif m.erp_field == "ID":
				# Child table: link back to parent via the `parent` column
				return f"{alias}.parent AS `{col}`"
			else:
				return f"NULL AS `{col}`"

	# Column exists nowhere else either — just emit NULL
	return f"NULL AS `{col}`"


def _dr_cr_expression(alias, mapping):
	"""
	Build the SQL expression for the Ledger Amount Dr/Cr column.

	Tax tables (e.g. 'Purchase Taxes and Charges') store whether a tax is
	additive or deductive in their own `add_deduct_tax` column, so we use
	a CASE expression.  All other tables use the literal from the mapping.
	"""
	TAX_TABLES = {"Purchase Taxes and Charges"}

	if mapping.child_table_name in TAX_TABLES:
		return (
			f"CASE WHEN {alias}.add_deduct_tax = 'Add' THEN 'Dr' ELSE 'Cr' END "
			f"AS `ledger_amount_dr/cr`"
		)
	else:
		return f"'{mapping.ledger_entry_type}' AS `ledger_amount_dr/cr`"


def _ordered_unique_tally_cols(mapping_doc):
	"""
	Return all distinct scrubbed tally column names in the order they first
	appear in the field_mappings child table.  This order determines the
	column sequence in every SELECT block.
	"""
	seen = set()
	cols = []
	for m in mapping_doc.field_mappings:
		col = frappe.scrub(m.tally_field_name)
		if col not in seen:
			cols.append(col)
			seen.add(col)
	return cols


def _build_where_clause(table, alias, mapping_doc, is_parent, parent_filter_sql, filters):
	"""
	Build the WHERE clause for one SELECT block.

	• Parent table → apply all user and default filters directly.
	• Child tables  → restrict rows to children of the filtered parent docs
	                  using a WHERE parent IN (sub-select).
	"""
	if is_parent:
		conditions = _collect_filter_conditions(mapping_doc, filters, alias)
		if conditions:
			return "WHERE " + " AND ".join(conditions)
		return ""
	else:
		return f"WHERE {alias}.parent IN ({parent_filter_sql})"


# ---------------------------------------------------------------------------
# Final SQL assembly
# ---------------------------------------------------------------------------

def _build_final_sql(union_parts, tally_fields, mapping_doc):
	"""
	Wrap all UNION ALL SELECT blocks in an outer SELECT that:
	  • Picks only the Tally columns (drops internal columns like `sort_order`
	    and `creation` which are used only for ordering).
	  • Orders rows so that all ledger lines for the same voucher appear
	    together AND in the exact sequence defined in the Tally Field Mapping.

	ORDER BY priority:
	  1. creation        — keeps vouchers in chronological order
	  2. voucher_number  — groups all ledger lines of the same voucher together
	  3. sort_order      — within one voucher, enforces the mapping row sequence
	                       (Supplier first, then RoundOff, then Items, then Taxes)

	`sort_order` and `creation` are included in every inner SELECT solely for
	this ordering; they are excluded from the outer SELECT column list.
	"""
	inner_sql = "\nUNION ALL\n".join(union_parts)

	# Base ordering: chronological, then group by voucher, then by mapping sequence
	order_by = "creation ASC"
	if mapping_doc.doctype_name in ("Sales Invoice", "Purchase Invoice", "Journal Entry"):
		order_by += ", voucher_number, sort_order"
	else:
		# For other DocTypes (masters etc.) sort_order still keeps rows tidy
		order_by += ", sort_order"

	if mapping_doc.doctype_name == "Journal Entry":
		order_by += ", ledger_amount"
	frappe.log_error("Query", {f"""
		SELECT {', '.join(tally_fields)}
		FROM (
			{inner_sql}
		) AS final_data
		ORDER BY {order_by}
	"""})
	return f"""
		SELECT {', '.join(tally_fields)}
		FROM (
			{inner_sql}
		) AS final_data
		ORDER BY {order_by}
	"""


# ---------------------------------------------------------------------------
# Post-processing helpers
# ---------------------------------------------------------------------------

def _fix_negative_amounts(data, doctype_name):
	"""
	Tally expects all ledger amounts to be positive.  When ERPNext stores a
	negative amount (e.g. a credit note reduces the invoice total), we flip
	the sign and swap the Dr/Cr flag accordingly.

	  Purchase Invoice negative amount → was Dr, should become Cr (and positive)
	  Sales Invoice    negative amount → was Cr, should become Dr (and positive)
	"""
	if doctype_name not in ("Purchase Invoice", "Sales Invoice"):
		return

	flip_to = "Cr" if doctype_name == "Purchase Invoice" else "Dr"

	for row in data:
		amount = row.get("ledger_amount")
		if amount is not None and amount < 0:
			row["ledger_amount_dr/cr"] = flip_to
			row["ledger_amount"] = -amount


def _clean_address_field(data):
	"""
	Replace HTML <br> tags in the address field with plain newline characters.
	Tally reads the address as plain text, so HTML tags must be stripped out.
	"""
	for row in data:
		addr = row.get("buyer/supplier___address")
		if addr:
			row["buyer/supplier___address"] = (
				addr.replace("<br>", "\n")
					.replace("<br/>", "\n")
					.replace("<br />", "\n")
			)


# ---------------------------------------------------------------------------
# Whitelisted API methods (called from client-side JS)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def set_filters(doctype):
	"""
	Return the list of dynamic filter fields for the report toolbar.

	Only field_mappings rows that have `is_filter` checked are included.
	This lets users filter by (e.g.) company or fiscal year without hardcoding
	those fields in the report definition.
	"""
	mapping_doc = frappe.get_doc("Tally Field Mapping", doctype)
	filters = []

	for mapping in mapping_doc.field_mappings:
		if mapping.is_filter:
			filters.append({
				"fieldname": frappe.scrub(mapping.erp_field_name),
				"label": mapping.erp_field,
				"fieldtype": mapping.erp_field_type,
				"options": mapping.options,
				"reqd": 0,
				"default": "",
			})

	return filters


@frappe.whitelist()
def update_tally_creation_status(doctype):
	"""
	Mark all submitted documents of `doctype` as already created in Tally.

	Called after the user clicks "Confirm Tally Creation" so the same
	vouchers are not exported again on the next run.
	"""
	frappe.db.set_value(doctype, {"docstatus": 1}, "custom_created_in_tally", 1)