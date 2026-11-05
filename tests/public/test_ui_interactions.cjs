const { test } = require('node:test');
const assert = require('node:assert/strict');
const UI = require('../../app/static/ui-utils.js');

test('pagination reaches every record without dropping or modifying data', () => {
  const rows = Array.from({length: 123}, (_, id) => Object.freeze({id}));
  Object.freeze(rows);
  const pages = [1, 2, 3, 4, 5].flatMap(page => UI.page(rows, page, 25).items);
  assert.deepEqual(pages, rows);
  assert.equal(UI.page(rows, 99, 25).page, 5);
  assert.equal(UI.page([], 99, 25).start, 0);
  assert.equal(UI.page(rows, -10, 25).page, 1);
});

test('review filters combine company, year, priority, and search without changing fields', () => {
  const rows = [
    {id:1, label:'营业收入', company_id:1, company_name:'甲企业', period:'2025', review_priority:'high', status:'pending'},
    {id:2, label:'营业收入', company_id:2, company_name:'乙企业', period:'2025', review_priority:'high', status:'pending'},
    {id:3, label:'营业收入', company_id:1, company_name:'甲企业', period:'2024', review_priority:'high', status:'confirmed'},
  ];
  rows.forEach(Object.freeze); Object.freeze(rows);
  const result = UI.filterFields(rows, {company:'1', period:'2025', query:' 营业 ', priority:'high'});
  assert.deepEqual(result.map(r => r.id), [1]);
  assert.equal(UI.filterFields(rows, {query:'不存在'}).length, 0);
  assert.deepEqual(UI.filterFields(rows, {priority:'pending'}).map(r => r.id), [1, 2]);
  assert.equal(rows[0].status, 'pending');
});

test('bulk selection accepts explicit zero, excludes revoked or incomplete evidence', () => {
  const field = {status:'pending', normalized_value:'0', source_page:7, source_quote:'营业收入 | 0.00'};
  assert.equal(UI.canSelect(field), true);
  for (const override of [{normalized_value:null}, {source_page:null}, {source_quote:' '}, {status:'confirmed'}]) {
    assert.equal(UI.canSelect({...field, ...override}), false);
  }
});

test('continue review remains in the filtered queue and skips current or confirmed rows', () => {
  const rows = [
    {id:1, company_id:1, status:'pending'}, {id:2, company_id:2, status:'pending'},
    {id:3, company_id:1, status:'confirmed'}, {id:4, company_id:1, status:'pending'},
    {id:5, company_id:1, status:'pending'},
  ];
  const filtered = UI.filterFields(rows, {company:'1'});
  assert.deepEqual(UI.nextPendingIds(filtered, 4), [5, 1]);
  assert.deepEqual(UI.nextPendingIds(filtered, 5), [1, 4]);
  assert.deepEqual(UI.nextPendingIds(filtered, 3), [1, 4, 5]);
  assert.deepEqual(UI.nextPendingIds([{id:1,status:'pending'}], 1), []);
});
