/* Pure view helpers: no requests, storage writes, or changes to source records. */
const WorkbenchUI = Object.freeze({
  page(items, requestedPage, pageSize) {
    const size = Math.max(1, Math.trunc(Number(pageSize)) || 25);
    const totalPages = Math.max(1, Math.ceil(items.length / size));
    const page = Math.max(1, Math.min(totalPages, Math.trunc(Number(requestedPage)) || 1));
    return { items: items.slice((page - 1) * size, page * size), page, totalPages,
      total: items.length, start: items.length ? (page - 1) * size + 1 : 0,
      end: Math.min(page * size, items.length) };
  },
  matches(value, query) {
    return String(value ?? "").toLocaleLowerCase().includes(String(query ?? "").trim().toLocaleLowerCase());
  },
  canSelect(field) {
    return field.status === "pending" && field.normalized_value != null
      && Number(field.source_page) > 0 && Boolean(String(field.source_quote ?? "").trim());
  },
  nextPendingIds(fields, currentId) {
    const pending = fields.filter(field => field.status === "pending");
    const position = pending.findIndex(field => field.id === Number(currentId));
    return [...pending.slice(position + 1), ...pending.slice(0, Math.max(0, position))]
      .filter(field => field.id !== Number(currentId)).map(field => field.id);
  },
  filterFields(fields, { query = "", company = "all", period = "all", priority = "all" } = {}) {
    return fields.filter((field) => {
      const text = `${field.label ?? ""} ${field.company_name ?? ""} ${field.document_filename ?? ""}`;
      const priorityMatch = priority === "all" || (priority === "pending" ? field.status === "pending"
        : field.status === "pending" && field.review_priority === priority);
      return this.matches(text, query) && (company === "all" || String(field.company_id) === company)
        && (period === "all" || field.period === period) && priorityMatch;
    });
  },
});
if (typeof module !== "undefined") module.exports = WorkbenchUI;
