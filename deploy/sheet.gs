// Sarge -> Google Sheet mirror. Paste into the sheet via Extensions > Apps Script,
// then Deploy > New deployment > Web app (Execute as: Me, Who has access: Anyone).
// The bot POSTs a full snapshot of one day; this replaces that day's rows (idempotent).

const SECRET = '__SHEET_SECRET__';

const DAILY_HEADERS = ['Date', 'Calories', 'Protein (g)', 'Carbs (g)', 'Fat (g)', 'Water (L)', 'Steps',
                       'Vitamin D', 'Calories OK', 'Protein OK', 'Updated'];
const LOG_HEADERS = ['Date', 'Time', 'Meal', 'Item', 'Grams', 'Calories', 'Protein (g)', 'Carbs (g)', 'Fat (g)'];

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.secret !== SECRET) return json({ ok: false, error: 'bad secret' });

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const daily = sheet(ss, 'Daily', DAILY_HEADERS);
    const log = sheet(ss, 'Log', LOG_HEADERS);
    const d = body.daily;

    // Daily: upsert the row for this date
    const row = [d.date, d.kcal, d.protein, d.carbs, d.fat, d.water_l, d.steps, d.vitd ? 'yes' : 'no',
                 d.kcal_ok ? 'yes' : 'no', d.protein_ok ? 'yes' : 'no', new Date()];
    const at = findRows(daily, d.date);
    if (at.length) daily.getRange(at[0], 1, 1, row.length).setValues([row]);
    else daily.appendRow(row);
    sortByDate(daily);

    // Log: drop this date's rows, write the fresh snapshot
    findRows(log, d.date).reverse().forEach(r => log.deleteRow(r));
    if (body.items.length) {
      const rows = body.items.map(i => [d.date, i.time, i.meal, i.name, i.grams || '', i.kcal, i.protein, i.carbs, i.fat]);
      log.getRange(log.getLastRow() + 1, 1, rows.length, LOG_HEADERS.length).setValues(rows);
      sortByDate(log);
    }
    return json({ ok: true });
  } finally {
    lock.releaseLock();
  }
}

function sheet(ss, name, headers) {
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.appendRow(headers);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sh.setFrozenRows(1);
    sh.getRange('A:A').setNumberFormat('@'); // keep dates as plain yyyy-mm-dd text
    const blank = ss.getSheetByName('Sheet1');
    if (blank && blank.getLastRow() === 0) ss.deleteSheet(blank);
  }
  return sh;
}

function findRows(sh, date) {
  const n = sh.getLastRow() - 1;
  if (n < 1) return [];
  return sh.getRange(2, 1, n, 1).getDisplayValues()
    .map((v, i) => (v[0] === date ? i + 2 : 0)).filter(Boolean);
}

function sortByDate(sh) {
  const n = sh.getLastRow() - 1;
  if (n > 1) sh.getRange(2, 1, n, sh.getLastColumn()).sort([{ column: 1, ascending: true }, { column: 2, ascending: true }]);
}

function json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
