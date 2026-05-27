// google-apps-script.js -- P&L Spreadsheet API
// Deploy: Extensions > Apps Script > paste > Deploy > New deployment
// Type: Web app | Execute as: Me | Who has access: Anyone
//
// doGet  -- returns all rows for current month tab (or ?sheet=MAY)
//           Response envelope now includes "currency" field (e.g. "USD", "EUR")
//           detected from the "Store Currency" metadata row (rows 1-5 of the sheet).
//
// doPost -- writes revenue / adspend_google / adspend_pinterest / refunds
//
// Writable columns (0-indexed, Mike's MAY+ layout):
//   B(1)  revenue
//   D(3)  adspend_google
//   E(4)  adspend_pinterest
//   O(14) refunds
// Column C (COG) is never touched -- Mike enters it manually.
//
// Store Currency detection:
//   Scan rows 1-5 of the sheet for a row where the first non-empty cell
//   contains "Store Currency" (case-insensitive). The value in the NEXT
//   non-empty cell on that row is used as the currency code (e.g. "USD").
//   If not found, defaults to "USD".

var HEADER_ROW = 6;
var DATA_START_ROW = 7;
var CURRENCY_SEARCH_ROWS = 5;  // scan only the first 5 rows for metadata

var COL = {
  DATE: 0,
  REVENUE: 1,
  COG: 2,
  ADSPEND_GOOGLE: 3,
  ADSPEND_PINTEREST: 4,
  REFUNDS: 14
};

var WRITABLE = {
  revenue: COL.REVENUE,
  adspend_google: COL.ADSPEND_GOOGLE,
  adspend_pinterest: COL.ADSPEND_PINTEREST,
  refunds: COL.REFUNDS
};

// --- Helpers ---

function detectCurrency(sheet) {
  // Scan first CURRENCY_SEARCH_ROWS rows for a "Store Currency" label.
  // Returns the currency code string (e.g. "USD") or "USD" as default.
  var lastRow = sheet.getLastRow();
  var scanRows = Math.min(CURRENCY_SEARCH_ROWS, lastRow);
  if (scanRows <= 0) { return 'USD'; }

  var data = sheet.getRange(1, 1, scanRows, 10).getValues();
  for (var r = 0; r < data.length; r++) {
    var row = data[r];
    for (var c = 0; c < row.length; c++) {
      var cellStr = String(row[c] || '').toLowerCase().trim();
      if (cellStr.indexOf('store currency') !== -1) {
        // Look for the value in the next non-empty cell on the same row
        for (var nc = c + 1; nc < row.length; nc++) {
          var val = String(row[nc] || '').toUpperCase().trim();
          if (val && val.length >= 3) {
            return val.substring(0, 3);   // return exactly 3 chars e.g. "USD"
          }
        }
        break;
      }
    }
  }
  return 'USD';  // default if metadata row not found
}

function findRowByDate(sheet, dateStr) {
  var lastRow = sheet.getLastRow();
  if (lastRow < DATA_START_ROW) { return -1; }
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
  var month = MONTHS[new Date().getMonth()];
  var allSheets = ss.getSheets();
  for (var i = 0; i < allSheets.length; i++) {
    if (allSheets[i].getName().toUpperCase().indexOf(month) !== -1) {
      return allSheets[i].getName();
    }
  }
  return allSheets[0].getName();
}

function getSheetForDate(dateStr) {
  var MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  var month = MONTHS[parseInt(dateStr.split('-')[1]) - 1];
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var allSheets = ss.getSheets();
  for (var i = 0; i < allSheets.length; i++) {
    if (allSheets[i].getName().toUpperCase().indexOf(month) !== -1) {
      return allSheets[i].getName();
    }
  }
  return allSheets[0].getName();
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// --- READ ---

function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var params = e ? e.parameter : {};
    var sheetName = params.sheet || getCurrentMonthSheet(ss);
    var dateFilter = params.date || null;

    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return jsonResponse({ success: false, error: 'Sheet not found: ' + sheetName });
    }

    // Detect store currency from metadata rows
    var currency = detectCurrency(sheet);

    var data = sheet.getDataRange().getValues();
    var headers = data[HEADER_ROW - 1];
    var rows = [];

    for (var i = DATA_START_ROW - 1; i < data.length; i++) {
      var row = data[i];
      if (!row[COL.DATE] || !(row[COL.DATE] instanceof Date)) { continue; }

      var isoDate = Utilities.formatDate(row[COL.DATE], 'Europe/Amsterdam', 'yyyy-MM-dd');
      if (dateFilter && isoDate !== dateFilter) { continue; }

      var obj = { _date_iso: isoDate, _sheet: sheetName };
      for (var j = 0; j < headers.length; j++) {
        var header = headers[j];
        if (!header) { continue; }
        var val = row[j];
        if (val === '#DIV/0!' || val === '#N/A' || val === '#VALUE!' ||
            val === '#REF!' || val === '#NULL!' || val === '') {
          val = null;
        }
        if (val instanceof Date) {
          val = Utilities.formatDate(val, 'Europe/Amsterdam', 'yyyy-MM-dd');
        }
        obj[header] = val;
      }
      rows.push(obj);
    }

    // Include currency in the response envelope so sheets_parser.py
    // can attach it to every row without an extra DB lookup.
    return jsonResponse({
      success: true,
      sheet: sheetName,
      currency: currency,
      rows: rows
    });

  } catch (err) {
    return jsonResponse({ success: false, error: err.toString() });
  }
}

// --- WRITE ---

function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var date = payload.date;
    var sheetName = payload.sheet || getSheetForDate(date);

    if (!date) {
      return jsonResponse({ success: false, error: 'Missing required field: date' });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      return jsonResponse({ success: false, error: 'Sheet not found: ' + sheetName });
    }

    var rowIndex = findRowByDate(sheet, date);
    if (rowIndex === -1) {
      return jsonResponse({ success: false, error: 'Date not found in sheet: ' + date });
    }

    var wrote = [];

    for (var field in WRITABLE) {
      if (payload.hasOwnProperty(field) && payload[field] !== null && payload[field] !== undefined) {
        sheet.getRange(rowIndex, WRITABLE[field] + 1).setValue(Number(payload[field]));
        wrote.push(field);
      }
    }

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

    SpreadsheetApp.flush();

    return jsonResponse({
      success: true,
      wrote: wrote,
      date: date,
      row: rowIndex,
      sheet: sheetName
    });

  } catch (err) {
    return jsonResponse({ success: false, error: err.toString() });
  }
}
