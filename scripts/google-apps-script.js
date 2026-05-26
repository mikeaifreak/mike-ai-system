/**
 * google-apps-script.js — P&L Spreadsheet API
 *
 * Deploy this as a web app on Mike's P&L Google Sheet:
 *   Extensions → Apps Script → paste this → Deploy → New deployment
 *   Type: Web app | Execute as: Me | Who has access: Anyone
 *
 * doGet  — returns all rows for the current (or ?sheet=MAY) month tab
 * doPost — writes revenue/adspend_google/adspend_pinterest/refunds for a date
 *
 * Writable columns (0-indexed, matches Mike's MAY+ layout):
 *   B(1)  revenue
 *   D(3)  adspend_google
 *   E(4)  adspend_pinterest
 *   O(14) refunds
 *
 * Column C (COG) is never touched — Mike enters it manually.
 */

var HEADER_ROW   = 6;
var DATA_START_ROW = 7;

var COL = {
  DATE:               0,
  REVENUE:            1,
  COG:                2,   // READ ONLY — never written
  ADSPEND_GOOGLE:     3,
  ADSPEND_PINTEREST:  4,
  REFUNDS:            14
};

// Only these fields may be written via doPost
var WRITABLE = {
  revenue:           COL.REVENUE,
  adspend_google:    COL.ADSPEND_GOOGLE,
  adspend_pinterest: COL.ADSPEND_PINTEREST,
  refunds:           COL.REFUNDS
};

// ─── READ ─────────────────────────────────────────────────────────────────────

function doGet(e) {
  try {
    var ss     = SpreadsheetApp.getActiveSpreadsheet();
    var params = e ? e.parameter : {};
    var sheetName = params.sheet || getCurrentMonthSheet(ss);
    var dateFilter = params.date || null;   // optional ?date=YYYY-MM-DD

    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return jsonResponse({ success: false, error: 'Sheet not found: ' + sheetName });
    }

    var data    = sheet.getDataRange().getValues();
    var headers = data[HEADER_ROW - 1];
    var rows    = [];

    for (var i = DATA_START_ROW - 1; i < data.length; i++) {
      var row = data[i];
      if (!row[COL.DATE] || !(row[COL.DATE] instanceof Date)) continue;

      var isoDate = Utilities.formatDate(row[COL.DATE], 'Europe/Amsterdam', 'yyyy-MM-dd');

      // Single-date filter (used by sheets_writer.read_row_for_date)
      if (dateFilter && isoDate !== dateFilter) continue;

      var obj = { _date_iso: isoDate, _sheet: sheetName };
      for (var j = 0; j < headers.length; j++) {
        var header = headers[j];
        if (!header) continue;
        var val = row[j];
        // Convert Excel errors and blanks to null
        if (val === '#DIV/0!' || val === '#N/A' || val === '#VALUE!' ||
            val === '#REF!'   || val === '#NULL!'|| val === '') {
          val = null;
        }
        // Date cells → ISO string so Python can parse without guessing format
        if (val instanceof Date) {
          val = Utilities.formatDate(val, 'Europe/Amsterdam', 'yyyy-MM-dd');
        }
        obj[header] = val;
      }
      rows.push(obj);
    }

    return jsonResponse({ success: true, sheet: sheetName, rows: rows });

  } catch (err) {
    return jsonResponse({ success: false, error: err.toString() });
  }
}

// ─── WRITE ────────────────────────────────────────────────────────────────────

/**
 * Accepts the multi-field format sent by sheets_writer.py:
 *   { "date": "2026-05-26", "revenue": 12345.67, "adspend_google": 567.89 }
 *
 * Also accepts the legacy single-field format for manual testing:
 *   { "date": "2026-05-26", "field": "revenue", "value": 12345.67 }
 *
 * Only fields listed in WRITABLE are accepted. COG is never touched.
 */
function doPost(e) {
  try {
    var payload   = JSON.parse(e.postData.contents);
    var date      = payload.date;
    var sheetName = payload.sheet || getSheetForDate(date);

    if (!date) {
      return jsonResponse({ success: false, error: 'Missing required field: date' });
    }

    var ss    = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return jsonResponse({ success: false, error: 'Sheet not found: ' + sheetName });
    }

    var rowIndex = findRowByDate(sheet, date);
    if (rowIndex === -1) {
      return jsonResponse({ success: false, error: 'Date not found in sheet: ' + date });
    }

    var wrote = [];

    // Multi-field format: { revenue: 123, adspend_google: 456, ... }
    for (var field in WRITABLE) {
      if (payload.hasOwnProperty(field) && payload[field] !== null && payload[field] !== undefined) {
        sheet.getRange(rowIndex, WRITABLE[field] + 1).setValue(Number(payload[field]));
        wrote.push(field);
      }
    }

    // Legacy single-field format: { field: "revenue", value: 123 }
    if (wrote.length === 0 && payload.field) {
      if (!WRITABLE.hasOwnProperty(payload.field)) {
        return jsonResponse({ success: false, error: 'Field not writable: ' + payload.field });
      }
      sheet.getRange(rowIndex, WRITABLE[payload.field] + 1).setValue(Number(payload.value));
      wrote.push(payload.field);
    }

    if (wrote.length === 0) {
      return jsonResponse({ success: false, error: 'No writable fields found in payload' });
    }

    // Flush forces formula recalculation before returning
    SpreadsheetApp.flush();

    return jsonResponse({ success: true, wrote: wrote, date: date, row: rowIndex, sheet: sheetName });

  } catch (err) {
    return jsonResponse({ success: false, error: err.toString() });
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function findRowByDate(sheet, dateStr) {
  var lastRow = sheet.getLastRow();
  if (lastRow < DATA_START_ROW) return -1;
  var data = sheet.getRange(DATA_START_ROW, 1, lastRow - DATA_START_ROW + 1, 1).getValues();
  for (var i = 0; i < data.length; i++) {
    var cell = data[i][0];
    if (cell instanceof Date) {
      if (Utilities.formatDate(cell, 'Europe/Amsterdam', 'yyyy-MM-dd') === dateStr) {
        return DATA_START_ROW + i;
      }
    }
  }
  return -1;
}

function getCurrentMonthSheet(ss) {
  var MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  var month  = MONTHS[new Date().getMonth()];
  var sheets = ss.getSheets().map(function(s) { return s.getName().toUpperCase(); });
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].indexOf(month) !== -1) return ss.getSheets()[i].getName();
  }
  return ss.getSheets()[0].getName();
}

function getSheetForDate(dateStr) {
  var MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  var month  = MONTHS[parseInt(dateStr.split('-')[1]) - 1];
  var ss     = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = ss.getSheets().map(function(s) { return s.getName().toUpperCase(); });
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].indexOf(month) !== -1) return ss.getSheets()[i].getName();
  }
  return ss.getSheets()[0].getName();
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
