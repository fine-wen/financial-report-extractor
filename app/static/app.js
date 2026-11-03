const state = {
  view: "dashboard",
  dashboard: null,
  companies: [],
  documents: [],
  fields: [],
  currentCompanyId: null,
  reviewDocumentId: null,
  reviewFilter: "all",
  companySearch: "",
  documentSearch: "",
  documentStatus: "all",
  documentType: "all",
  metricOptions: [],
  currentMetricCodes: [],
};

const titles = {
  dashboard: "工作概览",
  companies: "企业档案",
  documents: "文档中心",
  review: "人工复核",
  financial: "财务档案",
  tax: "税务档案",
};

const statusLabels = {
  queued: "等待处理",
  processing: "识别中",
  review_required: "待人工复核",
  failed: "处理失败",
  voided: "已作废",
  pending: "待复核",
  confirmed: "已确认",
  corrected: "已修改确认",
  missing: "已标记缺失",
  reviewed: "已复核完成",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatMoney(field) {
  if (field.value_text === null || field.value_text === undefined) return "—";
  const numeric = Number(String(field.value_text).replaceAll(",", "").replaceAll("，", ""));
  if (Number.isNaN(numeric)) return escapeHtml(field.value_text);
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(numeric)} ${escapeHtml(field.unit || "")}`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    if (response.status === 404 && path.includes("/tax-snapshot")) {
      throw new Error("税务档案接口未加载。请重启平台后刷新页面。");
    }
    let message = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch (_) {
      message = await response.text() || message;
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showToast(message, isError) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  window.setTimeout(() => toast.classList.remove("show"), 3600);
}

function showLoading() {
  document.getElementById("app-content").innerHTML = '<div class="loading"><div><div class="spinner"></div>正在读取数据…</div></div>';
}

function emptyState(title, description, actionLabel, actionId) {
  return `<div class="empty-state"><div class="empty-icon">◇</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p>${actionLabel ? `<button class="primary-button" id="${actionId}">${escapeHtml(actionLabel)}</button>` : ""}</div>`;
}

function badge(status) {
  return `<span class="badge ${escapeHtml(status)}">${escapeHtml(statusLabels[status] || status)}</span>`;
}

const checkStatusLabels = {
  complete: "完整",
  partial: "部分识别",
  missing: "未识别",
  passed: "勾稽通过",
  warning: "勾稽异常",
  unavailable: "无法勾稽",
};

const documentTypeLabels = {
  financial_statement: "审计报告 / 财务报表",
  vat_return: "增值税申报表",
  corporate_income_tax_return: "企业所得税年报",
  corporate_income_tax_prepayment: "企业所得税预缴表",
  tax_payment_certificate: "税收完税证明",
  auto: "待识别类型",
};

function checkPill(status, label) {
  return `<span class="check-pill ${escapeHtml(status)}">${escapeHtml(label)}：${escapeHtml(checkStatusLabels[status] || status)}</span>`;
}

function documentSummary(document) {
  const summary = document.check_summary;
  if (["vat_return", "corporate_income_tax_return", "corporate_income_tax_prepayment", "tax_payment_certificate"].includes(document.document_type)) {
    return `<div class="document-summary"><div><strong>${escapeHtml(documentTypeLabels[document.document_type])}</strong><span>已提取 ${document.field_count} 项税务数据</span></div><div class="summary-progress">${escapeHtml(statusLabels[document.status] || document.status)}</div></div>`;
  }
  if (!summary) return `<span class="subtext">识别完成后生成检查摘要</span>`;
  const periods = summary.periods.length > 0 ? summary.periods.join("、") : "年度待确认";
  return `<div class="document-summary">
    <div><strong>${escapeHtml(periods)}</strong><span>${escapeHtml(summary.statement_scope || "口径待确认")} · ${summary.base_field_count} 项原始数据 + ${summary.calculated_field_count} 项计算指标</span></div>
    <div class="check-pills">${checkPill(summary.balance_sheet_status, "资产负债表")}${checkPill(summary.income_statement_status, "利润表")}${checkPill(summary.cash_flow_statement_status, "现金流量表")}${checkPill(summary.balance_status, "资产勾稽")}</div>
    <div class="summary-progress">待复核 ${summary.pending_count} 项 · 已复核 ${summary.reviewed_count} 项${summary.high_priority_count > 0 ? ` · <b>${summary.high_priority_count} 项重点</b>` : ""}${summary.suspicious_count > 0 ? ` · <b>${summary.suspicious_count} 项疑似异常</b>` : ""}</div>
  </div>`;
}

async function loadCoreData() {
  const [dashboard, companies, documents, metricOptions] = await Promise.all([
    api("/api/dashboard", {}),
    api("/api/companies", {}),
    api("/api/documents", {}),
    api("/api/metrics", {}),
  ]);
  state.dashboard = dashboard;
  state.companies = companies;
  state.documents = documents;
  state.metricOptions = metricOptions;
  if (state.currentCompanyId === null && companies.length > 0) state.currentCompanyId = companies[0].id;
  const availableMetricCodes = new Set(metricOptions.map((metric) => metric.code));
  state.currentMetricCodes = state.currentMetricCodes.filter((code) => availableMetricCodes.has(code));
  if (state.currentMetricCodes.length === 0 && metricOptions.length > 0) {
    state.currentMetricCodes = [metricOptions[0].code];
  }
}

function companyName(companyId) {
  return state.companies.find((company) => company.id === companyId)?.name || `企业 #${companyId}`;
}

function matchesSearch(value, query) {
  return String(value || "").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
}

function documentsForCompany(companyId) {
  return state.documents.filter((document) => document.company_id === companyId);
}

function companyDocumentList(companyId) {
  const documents = documentsForCompany(companyId);
  if (documents.length === 0) return '<span class="subtext">暂未上传</span>';
  return `<div class="company-document-list">${documents.map((document) => `<div><span title="${escapeHtml(document.filename)}">${escapeHtml(document.filename)}</span>${badge(document.status)}</div>`).join("")}</div>`;
}

function renderDashboard() {
  const data = state.dashboard;
  const recentDocuments = state.documents.slice(0, 5);
  document.getElementById("app-content").innerHTML = `
    <section class="hero">
      <div><p class="eyebrow">可核验的财务数据</p><h2>把散落在PDF里的财务数据，变成可复核、可追溯的企业档案</h2><p>上传资料后，系统读取常用财务指标并保留原文证据。所有数据经过人工确认后再用于项目申报。</p></div>
      <div class="hero-side"><span>今日待办</span><strong>${data.pending_field_count}</strong><span>项财务字段等待人工复核</span></div>
    </section>
    <section class="stats-grid">
      <div class="stat-card"><span>企业档案</span><strong>${data.company_count}</strong><small>已建立企业</small></div>
      <div class="stat-card"><span>资料文件</span><strong>${data.document_count}</strong><small>${data.processing_count} 份正在处理</small></div>
      <div class="stat-card"><span>待复核字段</span><strong>${data.pending_field_count}</strong><small>需要业务人员确认</small></div>
      <div class="stat-card"><span>已确认字段</span><strong>${data.confirmed_field_count}</strong><small>${data.failed_count} 份资料处理失败</small></div>
    </section>
    <section class="panel"><div class="panel-head"><div><h2>最近处理的资料</h2><p>查看识别进度和异常信息</p></div><button class="text-button" data-go="documents">查看全部</button></div>
      ${recentDocuments.length === 0 ? emptyState("还没有财务资料", "先建立企业档案，再上传一份文字型PDF财务报表。", "开始建立企业", "empty-create-company") : documentTable(recentDocuments, false)}
    </section>`;
}

function documentTable(documents, allowVoid) {
  return `<div class="table-wrap"><table><thead><tr><th>文件</th><th>所属企业</th><th>状态</th><th>识别结果检查摘要</th><th>上传时间</th><th>操作</th></tr></thead><tbody>${documents.map((document) => `
    <tr><td><span class="company-name">${escapeHtml(document.filename)}</span><span class="subtext">${escapeHtml(documentTypeLabels[document.document_type] || document.document_type)} · ${document.page_count ? `${document.page_count} 页` : document.sha256.slice(0, 12)}</span></td>
    <td>${escapeHtml(companyName(document.company_id))}</td><td>${badge(document.status)}${document.error_message ? `<span class="subtext document-error">${escapeHtml(document.error_message)}</span>` : ""}</td>
    <td>${documentSummary(document)}</td><td>${formatDate(document.created_at)}</td><td><div class="row-actions">${["failed", "review_required", "reviewed"].includes(document.status) ? `<button class="text-button" data-retry-document="${document.id}">按最新规则重算</button><button class="text-button" data-recognize-document="${document.id}">重新识别原文件</button>` : ""}${(document.status === "failed" && document.error_message?.includes("核心财务报表识别不完整")) || (document.status === "review_required" && document.error_message?.includes("疑似行号或附注号")) ? `<button class="text-button" data-targeted-document="${document.id}">只补读疑点页</button>` : ""}${document.field_count > 0 ? `<button class="text-button" data-review-document="${document.id}">复核数据</button>` : ""}${allowVoid && !["processing", "voided"].includes(document.status) ? `<button class="text-button danger-text" data-void-document="${document.id}">作废文件</button>` : ""}</div></td></tr>`).join("")}</tbody></table></div>`;
}

function filteredCompanies() {
  return state.companies.filter((company) => matchesSearch(
    `${company.name} ${company.unified_code || ""} ${company.industry || ""}`,
    state.companySearch,
  ));
}

function companySearchResults(companies) {
  return companies.length === 0
    ? emptyState("没有匹配企业", "请调整搜索内容，或清空搜索后查看全部企业。", "", "")
    : `<div class="table-wrap"><table><thead><tr><th>企业</th><th>行业</th><th>已上传报表文件</th><th>待复核</th><th>已确认</th><th>建立时间</th><th>操作</th></tr></thead><tbody>${companies.map((company) => `<tr><td><span class="company-name">${escapeHtml(company.name)}</span><span class="subtext">${escapeHtml(company.unified_code || "未填写统一社会信用代码")}</span></td><td>${escapeHtml(company.industry || "—")}</td><td>${companyDocumentList(company.id)}<span class="subtext">共 ${company.document_count} 份</span></td><td>${company.pending_count}</td><td>${company.confirmed_count}</td><td>${formatDate(company.created_at)}</td><td><div class="row-actions"><button class="text-button" data-upload-company="${company.id}">上传资料</button><button class="text-button" data-company-documents="${company.id}">查看文件</button><button class="text-button" data-company-financial="${company.id}">查看财务档案</button></div></td></tr>`).join("")}</tbody></table></div>`;
}

function updateCompanySearchResults() {
  const companies = filteredCompanies();
  const count = document.getElementById("company-filter-result");
  const results = document.getElementById("company-search-results");
  if (count) count.textContent = `显示 ${companies.length} / ${state.companies.length} 家企业`;
  if (results) results.innerHTML = companySearchResults(companies);
}

function renderCompanies() {
  const companies = filteredCompanies();
  document.getElementById("app-content").innerHTML = `<section class="panel"><div class="panel-head"><div><h2>企业档案</h2><p>每家企业拥有独立的资料和财务数据</p></div><div class="row-actions"><button class="ghost-button" id="create-companies-batch" data-testid="create-companies-batch">批量新建</button><button class="primary-button" id="create-company" data-testid="create-company">＋ 新建企业</button></div></div>
    ${state.companies.length === 0 ? emptyState("还没有企业档案", "建立第一家企业后即可上传财务资料。", "新建企业", "empty-create-company") : `<div class="filterbar"><input id="company-search" data-testid="company-search" type="search" value="${escapeHtml(state.companySearch)}" placeholder="搜索企业名称、统一社会信用代码或行业" autocomplete="off"><span class="filter-result" id="company-filter-result">显示 ${companies.length} / ${state.companies.length} 家企业</span></div><div id="company-search-results">${companySearchResults(companies)}</div>`}
  </section>`;
}

function filteredDocuments() {
  return state.documents.filter((document) => (
    matchesSearch(
      `${document.filename} ${companyName(document.company_id)}`,
      state.documentSearch,
    ) && (state.documentStatus === "all" || document.status === state.documentStatus)
      && (state.documentType === "all" || (state.documentType === "tax"
        ? ["vat_return", "corporate_income_tax_return", "corporate_income_tax_prepayment", "tax_payment_certificate"].includes(document.document_type)
        : document.document_type === state.documentType))
  ));
}

function documentSearchResults(documents) {
  return documents.length === 0
    ? emptyState("没有匹配文件", "请调整搜索内容或处理状态后再查看。", "", "")
    : documentTable(documents, true);
}

function updateDocumentSearchResults() {
  const documents = filteredDocuments();
  const count = document.getElementById("document-filter-result");
  const results = document.getElementById("document-search-results");
  if (count) count.textContent = `显示 ${documents.length} / ${state.documents.length} 份文件`;
  if (results) results.innerHTML = documentSearchResults(documents);
}

function renderDocuments() {
  const documents = filteredDocuments();
  const statusOptions = [
    ["all", "全部处理状态"],
    ["failed", "处理失败"],
    ["review_required", "处理完成待复核"],
    ["reviewed", "已复核确认"],
    ["queued", "等待处理"],
    ["processing", "正在处理"],
    ["voided", "已作废"],
  ];
  const typeOptions = [["all", "全部资料类型"], ["financial_statement", "审计 / 财务报表"], ["tax", "税务资料"]];
  document.getElementById("app-content").innerHTML = `<section class="panel"><div class="panel-head"><div><h2>文档中心</h2><p>原始文件、处理状态和识别结果统一留存</p></div><div class="row-actions"><button class="ghost-button" id="auto-upload">按内容匹配企业</button><button class="ghost-button" id="batch-folder-upload" data-testid="batch-folder-upload">批量导入企业文件夹</button><button class="primary-button" id="document-upload">＋ 上传PDF</button></div></div>${state.documents.length === 0 ? emptyState("还没有上传文档", "上传财务或税务PDF后会自动识别目标数据。", "上传第一份资料", "empty-upload") : `<div class="filterbar"><input id="document-search" data-testid="document-search" type="search" value="${escapeHtml(state.documentSearch)}" placeholder="搜索企业名称或文件名" autocomplete="off"><select id="document-type" aria-label="按资料类型筛选">${typeOptions.map(([value, label]) => `<option value="${value}" ${state.documentType === value ? "selected" : ""}>${label}</option>`).join("")}</select><select id="document-status" data-testid="document-status" aria-label="按处理状态筛选">${statusOptions.map(([value, label]) => `<option value="${value}" ${state.documentStatus === value ? "selected" : ""}>${label}</option>`).join("")}</select><span class="filter-result" id="document-filter-result">显示 ${documents.length} / ${state.documents.length} 份文件</span></div><div id="document-search-results">${documentSearchResults(documents)}</div>`}</section>`;
}

async function renderReview(documentId) {
  showLoading();
  state.reviewDocumentId = documentId;
  const query = documentId ? `?document_id=${documentId}` : "?field_status=pending";
  state.fields = await api(`/api/fields${query}`, {});
  const pendingFields = state.fields.filter((field) => field.status === "pending");
  const highCount = pendingFields.filter((field) => field.review_priority === "high").length;
  const normalCount = pendingFields.filter((field) => field.review_priority === "normal").length;
  const calculatedCount = pendingFields.filter((field) => field.review_priority === "calculated").length;
  const visibleFields = state.fields.filter((field) => {
    if (state.reviewFilter === "pending") return field.status === "pending";
    if (["high", "normal", "calculated"].includes(state.reviewFilter)) return field.review_priority === state.reviewFilter && field.status === "pending";
    return true;
  });
  document.getElementById("app-content").innerHTML = `<section class="panel"><div class="panel-head"><div><h2>${documentId ? "文档字段复核" : "待复核字段"}</h2><p>已在导出表格和原件中完成核对的指标，可勾选后一次性确认，包括重点和计算指标。</p></div><button class="primary-button" id="confirm-selected" disabled>确认已勾选项</button></div>
    <div class="review-stats"><button data-review-filter="high" class="review-stat ${state.reviewFilter === "high" ? "active" : ""}"><strong>${highCount}</strong><span>重点待核</span></button><button data-review-filter="normal" class="review-stat ${state.reviewFilter === "normal" ? "active" : ""}"><strong>${normalCount}</strong><span>普通待核</span></button><button data-review-filter="calculated" class="review-stat ${state.reviewFilter === "calculated" ? "active" : ""}"><strong>${calculatedCount}</strong><span>计算指标</span></button><button data-review-filter="all" class="review-stat ${state.reviewFilter === "all" ? "active" : ""}"><strong>${state.fields.length}</strong><span>全部字段</span></button></div>
    ${state.fields.length === 0 ? emptyState("没有待复核内容", "新上传资料处理完成后，识别结果会出现在这里。", "去上传资料", "empty-upload") : `<div class="table-wrap"><table><thead><tr><th><input class="row-check" type="checkbox" id="select-visible" aria-label="勾选当前列表全部待复核项"></th><th>指标</th><th>识别数值</th><th>企业 / 文件</th><th>原文证据</th><th>可信度</th><th>状态</th><th>操作</th></tr></thead><tbody>${visibleFields.map((field) => `<tr class="review-row ${escapeHtml(field.review_priority)}"><td>${field.status === "pending" ? `<input class="row-check field-check" type="checkbox" value="${field.id}" aria-label="勾选${escapeHtml(field.label)}">` : ""}</td><td><span class="company-name">${escapeHtml(field.label)}</span><span class="subtext">${escapeHtml(field.period || "年度待确认")}${field.risk_reasons.length > 0 ? ` · ${escapeHtml(field.risk_reasons.join("、"))}` : field.review_priority === "calculated" ? " · 自动计算" : ""}</span></td><td>${formatMoney(field)}</td><td>${escapeHtml(field.company_name)}<span class="subtext">${escapeHtml(field.document_filename)}</span></td><td class="evidence-cell">第 ${field.source_page || "—"} 页 · ${escapeHtml(field.source_quote || "无原文证据")}</td><td class="confidence ${Number(field.confidence) < 0.95 ? "low" : ""}">${Math.round(Number(field.confidence) * 100)}%</td><td>${badge(field.status)}</td><td><button class="text-button" data-open-review="${field.id}">打开复核</button></td></tr>`).join("")}</tbody></table></div>`}
  </section>`;
}

async function renderFinancial() {
  if (state.companies.length === 0) {
    document.getElementById("app-content").innerHTML = `<section class="panel">${emptyState("还没有企业档案", "建立企业并上传资料后，可在这里查看财务档案。", "新建企业", "empty-create-company")}</section>`;
    return;
  }
  const companyId = state.currentCompanyId || state.companies[0].id;
  state.currentCompanyId = companyId;
  const fields = await api(`/api/companies/${companyId}/financial-snapshot`, {});
  const exportUrl = metricExportUrl();
  const metricExport = state.metricOptions.length === 0
    ? '<span class="subtext">暂无可汇总指标</span>'
    : `<details class="metric-picker" data-testid="financial-metric"><summary id="metric-picker-summary">已选 ${state.currentMetricCodes.length} 项指标</summary><div class="metric-menu"><div class="metric-menu-actions"><button type="button" class="text-button" data-metric-action="all">全选</button><button type="button" class="text-button" data-metric-action="clear">清空</button></div>${state.metricOptions.map((metric) => `<label class="metric-option"><input class="metric-check" type="checkbox" value="${escapeHtml(metric.code)}" ${state.currentMetricCodes.includes(metric.code) ? "checked" : ""}><span>${escapeHtml(metric.label)}</span></label>`).join("")}</div></details><a class="primary-button ${exportUrl ? "" : "disabled"}" id="metric-export" data-testid="metric-export" ${exportUrl ? `href="${escapeHtml(exportUrl)}"` : 'aria-disabled="true"'}>导出全部企业</a>`;
  document.getElementById("app-content").innerHTML = `<section class="panel"><div class="panel-head"><div><h2>企业财务档案</h2><p>已识别数据与复核状态一览</p></div><div class="row-actions"><select id="financial-company" data-testid="financial-company">${state.companies.map((company) => `<option value="${company.id}" ${company.id === companyId ? "selected" : ""}>${escapeHtml(company.name)}</option>`).join("")}</select><a class="primary-button" href="/api/companies/${companyId}/export.xlsx">导出Excel</a></div></div>
    <div class="filterbar"><span><strong>按指标汇总所有企业</strong><span class="subtext">可多选指标，导出全部年度、复核状态和原文来源</span></span><div class="row-actions">${metricExport}</div></div>
    ${fields.length === 0 ? emptyState("该企业还没有财务数据", "上传财务PDF并完成识别后，数据会集中显示在这里。", "上传财务资料", "empty-upload") : `<div class="table-wrap"><table><thead><tr><th>指标</th><th>数值</th><th>年度</th><th>状态</th><th>来源页码</th><th>原文证据</th></tr></thead><tbody>${fields.map((field) => `<tr><td class="company-name">${escapeHtml(field.label)}</td><td>${formatMoney(field)}</td><td>${escapeHtml(field.period || "—")}</td><td>${badge(field.status)}</td><td>第 ${field.source_page || "—"} 页</td><td class="evidence-cell">${escapeHtml(field.source_quote || "—")}</td></tr>`).join("")}</tbody></table></div>`}
  </section>`;
}

async function renderTax() {
  if (state.companies.length === 0) {
    document.getElementById("app-content").innerHTML = `<section class="panel">${emptyState("还没有企业档案", "建立企业后即可上传税务资料。", "新建企业", "empty-create-company")}</section>`;
    return;
  }
  const companyId = state.currentCompanyId || state.companies[0].id;
  state.currentCompanyId = companyId;
  const fields = await api(`/api/companies/${companyId}/tax-snapshot`, {});
  document.getElementById("app-content").innerHTML = `<section class="panel"><div class="panel-head"><div><h2>企业税务档案</h2><p>完税证明按原表逐行保存，同一税种的不同记录不合并；结果需人工复核，不同税务口径不可直接相加。</p></div><div class="row-actions"><select id="tax-company">${state.companies.map((company) => `<option value="${company.id}" ${company.id === companyId ? "selected" : ""}>${escapeHtml(company.name)}</option>`).join("")}</select>${fields.length ? `<a class="primary-button" href="/api/companies/${companyId}/tax-export.xlsx">导出税务Excel</a>` : ""}</div></div>
    ${fields.length === 0 ? emptyState("该企业还没有税务数据", "上传完税证明、增值税申报表或企业所得税申报表后显示在这里。", "上传税务资料", "empty-upload") : `<div class="table-wrap"><table><thead><tr><th>税务指标</th><th>数值</th><th>所属期间</th><th>状态</th><th>来源文件 / 页码</th><th>原文证据</th></tr></thead><tbody>${fields.map((field) => `<tr><td class="company-name">${escapeHtml(field.label)}</td><td>${formatMoney(field)}</td><td>${escapeHtml(field.period || "—")}</td><td>${badge(field.status)}</td><td>${escapeHtml(field.document_filename || "—")}<span class="subtext">第 ${field.source_page || "—"} 页</span></td><td class="evidence-cell">${escapeHtml(field.source_quote || "—")}</td></tr>`).join("")}</tbody></table></div>`}
  </section>`;
}

function metricExportUrl() {
  if (state.currentMetricCodes.length === 0) return null;
  const parameters = new URLSearchParams();
  state.currentMetricCodes.forEach((code) => parameters.append("field_codes", code));
  return `/api/metrics/export.xlsx?${parameters.toString()}`;
}

function updateMetricExportControls() {
  const summary = document.getElementById("metric-picker-summary");
  if (summary) summary.textContent = `已选 ${state.currentMetricCodes.length} 项指标`;
  const link = document.getElementById("metric-export");
  if (!link) return;
  const exportUrl = metricExportUrl();
  if (exportUrl) {
    link.href = exportUrl;
    link.classList.remove("disabled");
    link.removeAttribute("aria-disabled");
  } else {
    link.removeAttribute("href");
    link.classList.add("disabled");
    link.setAttribute("aria-disabled", "true");
  }
}

async function renderCurrentView() {
  showLoading();
  document.getElementById("page-title").textContent = titles[state.view];
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === state.view));
  if (state.view === "dashboard") renderDashboard();
  if (state.view === "companies") renderCompanies();
  if (state.view === "documents") renderDocuments();
  if (state.view === "review") await renderReview(state.reviewDocumentId);
  if (state.view === "financial") await renderFinancial();
  if (state.view === "tax") await renderTax();
}

async function refresh() {
  try {
    await loadCoreData();
    await renderCurrentView();
  } catch (error) {
    document.getElementById("app-content").innerHTML = `<section class="panel">${emptyState("读取失败", error.message, "重新加载", "reload-app")}</section>`;
    showToast(error.message, true);
  }
}

function populateCompanySelect(selectedId) {
  const select = document.getElementById("upload-company");
  const searchInput = document.getElementById("upload-company-search");
  const query = searchInput?.value || "";
  const companies = state.companies.filter((company) => matchesSearch(
    `${company.name} ${company.unified_code || ""}`,
    query,
  ));
  select.innerHTML = companies.length === 0
    ? '<option value="" disabled selected>没有匹配企业</option>'
    : companies.map((company) => `<option value="${company.id}" ${company.id === selectedId ? "selected" : ""}>${escapeHtml(company.name)}</option>`).join("");
}

function openUploadDialog(companyId) {
  if (state.companies.length === 0) {
    showToast("请先建立企业档案", true);
    document.getElementById("company-dialog").showModal();
    return;
  }
  document.getElementById("upload-company-search").value = "";
  populateCompanySelect(companyId || state.currentCompanyId || state.companies[0].id);
  document.getElementById("upload-dialog").showModal();
}

function openReviewDialog(fieldId) {
  const field = state.fields.find((item) => item.id === fieldId);
  if (!field) return;
  const form = document.getElementById("review-form");
  form.elements.field_id.value = field.id;
  form.elements.value_text.value = field.value_text || "";
  form.elements.unit.value = field.unit || "";
  form.elements.period.value = field.period || "";
  form.elements.source_page.value = field.source_page || "";
  form.elements.source_quote.value = field.source_page ? (field.source_quote || "") : "";
  form.elements.status.value = field.status === "pending"
    ? (field.source_page ? "confirmed" : "corrected") : field.status;
  document.getElementById("review-title").textContent = `复核：${field.label}`;
  document.getElementById("review-evidence").textContent = field.source_quote || "没有定位到原文证据";
  document.getElementById("review-source").textContent = `${field.company_name} · ${field.document_filename} · 第 ${field.source_page || "—"} 页 · 可信度 ${Math.round(Number(field.confidence) * 100)}%`;
  document.getElementById("review-dialog").showModal();
}

document.getElementById("main-nav").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-view]");
  if (!button) return;
  state.view = button.dataset.view;
  if (state.view === "review") state.reviewDocumentId = null;
  await renderCurrentView();
});

document.getElementById("refresh-button").addEventListener("click", refresh);
document.getElementById("quick-upload").addEventListener("click", () => openUploadDialog(null));
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => document.getElementById(button.dataset.close).close()));

document.getElementById("company-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  for (const key of Object.keys(data)) if (data[key] === "") data[key] = null;
  try {
    const company = await api("/api/companies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    state.currentCompanyId = company.id;
    form.reset();
    document.getElementById("company-dialog").close();
    showToast(`已建立企业档案：${company.name}`, false);
    await refresh();
  } catch (error) { showToast(error.message, true); }
});

document.getElementById("company-batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const lines = form.elements.companies.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const companies = lines.map((line) => {
    const columns = line.split("\t").map((column) => column.trim());
    return {
      name: columns[0],
      unified_code: columns[1] || null,
      industry: columns[2] || null,
      contact_name: columns[3] || null,
    };
  });
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    const result = await api("/api/companies/batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ companies }) });
    form.reset();
    document.getElementById("company-batch-dialog").close();
    const skipped = result.skipped_names.length > 0 ? `，跳过重复 ${result.skipped_names.length} 家` : "";
    showToast(`已建立 ${result.created.length} 家企业${skipped}`, false);
    await refresh();
  } catch (error) { showToast(error.message, true); }
  finally { submit.disabled = false; }
});

document.getElementById("pdf-file").addEventListener("change", (event) => {
  const files = Array.from(event.target.files);
  document.getElementById("selected-file").textContent = files.length === 0
    ? "尚未选择文件"
    : files.length === 1 ? files[0].name : `已选择 ${files.length} 份PDF`;
});

document.getElementById("auto-pdf-files").addEventListener("change", (event) => {
  const files = Array.from(event.target.files);
  document.getElementById("auto-selected-files").textContent = files.length
    ? `已选择 ${files.length} 份PDF` : "尚未选择文件";
  document.getElementById("auto-upload-result").hidden = true;
});

document.getElementById("auto-upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const files = Array.from(document.getElementById("auto-pdf-files").files);
  if (!files.length) return;
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  let uploaded = 0;
  const errors = [];
  try {
    for (const file of files) {
      const body = new FormData();
      body.append("file", file);
      try {
        await api("/api/documents/auto-upload", { method: "POST", body });
        uploaded += 1;
      } catch (error) {
        errors.push(`${file.name}：${error.message}`);
      }
    }
    const result = document.getElementById("auto-upload-result");
    result.innerHTML = `<strong>匹配结果</strong><span>已上传 ${uploaded} 份，未入库 ${errors.length} 份。${errors.length ? `<br>${errors.slice(0, 8).map(escapeHtml).join("<br>")}` : ""}</span>`;
    result.hidden = false;
    showToast(`已自动匹配并上传 ${uploaded} 份${errors.length ? `，${errors.length} 份需要确认归属` : ""}`, errors.length > 0);
    state.view = "documents";
    await refresh();
    if (uploaded === files.length) {
      form.reset();
      document.getElementById("auto-selected-files").textContent = "尚未选择文件";
      document.getElementById("auto-upload-dialog").close();
    }
  } finally { submit.disabled = false; }
});

function planBatchFolderFiles(selectedFiles) {
  const pdfFiles = selectedFiles.filter((file) => file.name.toLocaleLowerCase().endsWith(".pdf"));
  const pathParts = pdfFiles.map((file) => file.webkitRelativePath.split("/").filter(Boolean));
  const hasRootFiles = pathParts.some((parts) => parts.length === 2);
  const hasNestedFiles = pathParts.some((parts) => parts.length > 2);
  if (hasRootFiles && hasNestedFiles) {
    throw new Error("所选文件夹同时包含根目录PDF和企业子文件夹，无法可靠判断企业归属，请分别上传");
  }
  const singleCompanyFolder = hasRootFiles;
  const items = pdfFiles.map((file, index) => {
    const parts = pathParts[index];
    const relativePath = singleCompanyFolder ? parts.join("/") : parts.slice(1).join("/");
    const companyFolder = singleCompanyFolder ? parts[0] : parts[1];
    return { file, relativePath, companyFolder };
  });
  return { items, singleCompanyFolder };
}

document.getElementById("batch-folder").addEventListener("change", (event) => {
  try {
    const plan = planBatchFolderFiles(Array.from(event.target.files));
    const companyFolders = new Set(plan.items.map((item) => item.companyFolder).filter(Boolean));
    document.getElementById("selected-folder").textContent = plan.items.length === 0
      ? "选定文件夹中没有PDF"
      : plan.singleCompanyFolder
        ? `已识别单家企业文件夹：${Array.from(companyFolders)[0]}，共 ${plan.items.length} 份PDF`
        : `已发现 ${companyFolders.size} 个企业文件夹、${plan.items.length} 份PDF`;
  } catch (error) {
    document.getElementById("selected-folder").textContent = error.message;
  }
  document.getElementById("batch-folder-result").hidden = true;
});

document.getElementById("upload-company-search").addEventListener("input", (event) => {
  const selectedId = Number(document.getElementById("upload-company").value);
  populateCompanySelect(selectedId);
  if (event.currentTarget.value.trim() !== "" && document.getElementById("upload-company").value === "") {
    showToast("没有匹配企业，请先新建企业档案", true);
  }
});

document.getElementById("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const companyId = form.elements.company_id.value;
  const files = Array.from(form.elements.file.files);
  if (files.length === 0) { showToast("请选择PDF文件", true); return; }
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  submit.textContent = "正在上传…";
  let uploaded = 0;
  const errors = [];
  try {
    for (const file of files) {
      const body = new FormData();
      body.append("file", file);
      try {
        await api(`/api/companies/${companyId}/documents`, { method: "POST", body });
        uploaded += 1;
      } catch (error) {
        errors.push(`${file.name}：${error.message}`);
      }
    }
    if (uploaded > 0) {
      form.reset();
      document.getElementById("selected-file").textContent = "尚未选择文件";
      document.getElementById("upload-dialog").close();
      state.view = "documents";
    }
    showToast(`已上传 ${uploaded} 份${errors.length > 0 ? `，${errors.length} 份失败或重复` : "，正在按顺序识别"}`, errors.length > 0);
    await refresh();
    if (uploaded === 0 && errors.length > 0) showToast(errors[0], true);
  } catch (error) { showToast(error.message, true); }
  finally { submit.disabled = false; submit.textContent = "上传并开始识别"; }
});

document.getElementById("batch-folder-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  let plan;
  try {
    plan = planBatchFolderFiles(Array.from(document.getElementById("batch-folder").files));
  } catch (error) {
    showToast(error.message, true);
    return;
  }
  if (plan.items.length === 0) { showToast("选定文件夹中没有PDF", true); return; }
  const body = new FormData();
  for (const item of plan.items) {
    body.append("files", item.file, item.file.name);
    body.append("relative_paths", item.relativePath);
  }
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  submit.textContent = `正在上传 ${plan.items.length} 份…`;
  try {
    const result = await api("/api/documents/batch-upload", { method: "POST", body });
    const resultBox = document.getElementById("batch-folder-result");
    const failures = result.items.filter((item) => item.status === "failed").slice(0, 8);
    const duplicates = result.items.filter((item) => item.status === "duplicate").slice(0, 8);
    const details = [...failures, ...duplicates];
    resultBox.innerHTML = `<strong>导入结果</strong><span>新建企业 ${result.created_company_count} 家，成功上传 ${result.uploaded_count} 份，跳过重复 ${result.duplicate_count} 份，失败 ${result.failed_count} 份。${details.length > 0 ? `<br>${details.map((item) => `${escapeHtml(item.relative_path)}：${escapeHtml(item.message)}`).join("<br>")}` : ""}</span>`;
    resultBox.hidden = false;
    state.view = "documents";
    const toastMessage = result.uploaded_count > 0
      ? `批量上传完成：${result.uploaded_count} 份已排队${result.duplicate_count > 0 ? `，${result.duplicate_count} 份重复` : ""}`
      : result.failed_count > 0
        ? `没有文件入队：${failures[0]?.message || `${result.failed_count} 份上传失败`}`
        : `没有新文件入队：所选 ${result.duplicate_count} 份PDF均已上传过`;
    showToast(toastMessage, result.uploaded_count === 0 || result.failed_count > 0);
    await refresh();
    if (result.uploaded_count > 0 && result.failed_count === 0 && result.duplicate_count === 0) {
      form.reset();
      document.getElementById("selected-folder").textContent = "尚未选择文件夹";
      document.getElementById("batch-folder-dialog").close();
    }
  } catch (error) { showToast(error.message, true); }
  finally { submit.disabled = false; submit.textContent = "批量上传并排队"; }
});

document.getElementById("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const fieldId = data.field_id;
  delete data.field_id;
  for (const key of ["value_text", "unit", "period", "source_page", "source_quote"]) if (data[key] === "") data[key] = null;
  const continueReview = event.submitter?.id === "save-review-next";
  try {
    await api(`/api/fields/${fieldId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
    document.getElementById("review-dialog").close();
    showToast("复核结果已保存", false);
    await refresh();
    if (continueReview) {
      const nextField = state.fields.find((field) => field.status === "pending");
      if (nextField) openReviewDialog(nextField.id);
      else showToast("当前列表已全部复核完成", false);
    }
  } catch (error) { showToast(error.message, true); }
});

document.getElementById("app-content").addEventListener("click", async (event) => {
  const target = event.target;
  if (target.id === "create-company" || target.id === "empty-create-company") document.getElementById("company-dialog").showModal();
  if (target.id === "create-companies-batch") document.getElementById("company-batch-dialog").showModal();
  if (target.id === "document-upload" || target.id === "empty-upload") openUploadDialog(null);
  if (target.id === "batch-folder-upload") {
    document.getElementById("batch-folder-result").hidden = true;
    document.getElementById("batch-folder-dialog").showModal();
  }
  if (target.id === "auto-upload") {
    document.getElementById("auto-upload-result").hidden = true;
    document.getElementById("auto-upload-dialog").showModal();
  }
  if (target.id === "reload-app") await refresh();
  if (target.dataset.go) { state.view = target.dataset.go; await renderCurrentView(); }
  if (target.dataset.uploadCompany) openUploadDialog(Number(target.dataset.uploadCompany));
  if (target.dataset.companyDocuments) {
    state.documentSearch = companyName(Number(target.dataset.companyDocuments));
    state.view = "documents";
    await renderCurrentView();
  }
  if (target.dataset.companyFinancial) { state.currentCompanyId = Number(target.dataset.companyFinancial); state.view = "financial"; await renderCurrentView(); }
  if (target.dataset.reviewDocument) { state.view = "review"; document.getElementById("page-title").textContent = titles.review; await renderReview(Number(target.dataset.reviewDocument)); }
  if (target.dataset.openReview) openReviewDialog(Number(target.dataset.openReview));
  if (target.dataset.reviewFilter) { state.reviewFilter = target.dataset.reviewFilter; await renderReview(state.reviewDocumentId); }
  if (target.dataset.retryDocument) {
    try { await api(`/api/documents/${target.dataset.retryDocument}/retry`, { method: "POST" }); showToast("已按最新规则重新排队，不会重复运行 MinerU", false); await refresh(); }
    catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.targetedDocument) {
    try { await api(`/api/documents/${target.dataset.targetedDocument}/retry-targeted`, { method: "POST" }); showToast("已排队，只对缺指标的疑点页做二次识别", false); await refresh(); }
    catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.recognizeDocument) {
    const confirmed = window.confirm("确定重新运行 MinerU 吗？长报告可能需要数小时；只有原识别结果确实有问题时才需要这样做。");
    if (!confirmed) return;
    try { await api(`/api/documents/${target.dataset.recognizeDocument}/recognize-again`, { method: "POST" }); showToast("已提交 MinerU 重新识别", false); await refresh(); }
    catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.voidDocument) {
    const document = state.documents.find((item) => item.id === Number(target.dataset.voidDocument));
    const confirmed = window.confirm(`确定作废“${document?.filename || "该文件"}”吗？\n\n作废后，这份文件提取的全部字段都会删除。`);
    if (!confirmed) return;
    try { await api(`/api/documents/${target.dataset.voidDocument}/void`, { method: "POST" }); showToast("文件已作废，对应字段数据已删除", false); await refresh(); }
    catch (error) { showToast(error.message, true); }
  }
  if (target.id === "confirm-selected") {
    const ids = [...document.querySelectorAll(".field-check:checked")].map((checkbox) => Number(checkbox.value));
    if (ids.length === 0) { showToast("请先勾选要确认的字段", true); return; }
    try { await api("/api/fields/batch-confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ field_ids: ids, reviewer: "审核员" }) }); showToast(`已确认 ${ids.length} 项字段`, false); await refresh(); }
    catch (error) { showToast(error.message, true); }
  }
  if (target.dataset.metricAction) {
    const selectAll = target.dataset.metricAction === "all";
    document.querySelectorAll(".metric-check").forEach((checkbox) => { checkbox.checked = selectAll; });
    state.currentMetricCodes = selectAll ? state.metricOptions.map((metric) => metric.code) : [];
    updateMetricExportControls();
  }
  if (target.id === "metric-export" && state.currentMetricCodes.length === 0) {
    event.preventDefault();
    showToast("请至少选择一个指标", true);
  }
});

document.getElementById("app-content").addEventListener("change", async (event) => {
  if (event.target.id === "document-status") {
    state.documentStatus = event.target.value;
    updateDocumentSearchResults();
  }
  if (event.target.id === "document-type") {
    state.documentType = event.target.value;
    updateDocumentSearchResults();
  }
  if (event.target.id === "financial-company") {
    state.currentCompanyId = Number(event.target.value);
    await renderFinancial();
  }
  if (event.target.id === "tax-company") {
    state.currentCompanyId = Number(event.target.value);
    await renderTax();
  }
  if (event.target.matches(".metric-check")) {
    state.currentMetricCodes = [...document.querySelectorAll(".metric-check:checked")].map((checkbox) => checkbox.value);
    updateMetricExportControls();
  }
  if (event.target.id === "select-visible") {
    document.querySelectorAll(".field-check").forEach((checkbox) => { checkbox.checked = event.target.checked; });
  }
  if (event.target.matches("#select-visible, .field-check")) {
    const selectedCount = document.querySelectorAll(".field-check:checked").length;
    const confirmButton = document.getElementById("confirm-selected");
    if (confirmButton) {
      confirmButton.disabled = selectedCount === 0;
      confirmButton.textContent = selectedCount === 0 ? "确认已勾选项" : `确认已勾选 ${selectedCount} 项`;
    }
  }
});

document.getElementById("app-content").addEventListener("input", (event) => {
  if (event.isComposing) return;
  if (event.target.id === "company-search") {
    state.companySearch = event.target.value;
    updateCompanySearchResults();
  }
  if (event.target.id === "document-search") {
    state.documentSearch = event.target.value;
    updateDocumentSearchResults();
  }
});

document.getElementById("app-content").addEventListener("compositionend", (event) => {
  if (event.target.id === "company-search") {
    state.companySearch = event.target.value;
    updateCompanySearchResults();
  }
  if (event.target.id === "document-search") {
    state.documentSearch = event.target.value;
    updateDocumentSearchResults();
  }
});

refresh();
