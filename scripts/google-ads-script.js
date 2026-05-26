/**
 * Google Ads Script — Daily Campaign Performance Export
 *
 * HOW TO INSTALL (repeat for each Google Ads account):
 * ─────────────────────────────────────────────────────
 * 1. Open Google Ads → Tools & Settings → Bulk Actions → Scripts
 * 2. Click the blue "+" button to create a new script
 * 3. Paste this entire file into the editor
 * 4. Set SHEET_URL below to the URL of the target Google Sheet
 *    (each account should write to its own tab in the same sheet,
 *     or to a completely separate sheet — see SHEET_TAB below)
 * 5. Click "Authorize" and grant the required permissions
 * 6. Click "Run" once manually to verify it works and to confirm
 *    the permission dialog
 * 7. Set the schedule: click "Frequency" → Daily → 06:00 AM
 *    (use the same timezone as your Google Ads account)
 * 8. Save
 *
 * OUTPUT SHEET COLUMNS:
 *   Date | Account Name | Campaign | Spend | Impressions | Clicks | Conversions | CPC
 *
 * The script writes one row per campaign per day.
 * Our Python system aggregates across all campaigns when it reads the sheet.
 * Re-running for the same day is safe — existing rows for that date are
 * deleted before new rows are written (idempotent).
 */

// ─── CONFIGURATION (edit these two lines only) ────────────────────────────
var SHEET_URL = 'https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit';
var SHEET_TAB = 'Ads Data';  // Tab name — use a unique name per account if
                              // multiple accounts write to the same spreadsheet
// ─────────────────────────────────────────────────────────────────────────

var HEADER = ['Date', 'Account Name', 'Campaign', 'Spend', 'Impressions', 'Clicks', 'Conversions', 'CPC'];
var MICROS  = 1000000;

function main() {
  var account    = AdsApp.currentAccount();
  var accountName = account.getName();
  var timezone   = account.getTimeZone();

  // Yesterday in account timezone
  var yesterday  = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var dateStr    = Utilities.formatDate(yesterday, timezone, 'yyyy-MM-dd');

  Logger.log('Running for account: ' + accountName + '  date: ' + dateStr);

  // ── Fetch campaign metrics via GAQL ──────────────────────────────────
  var query = [
    'SELECT',
    '  campaign.name,',
    '  metrics.cost_micros,',
    '  metrics.impressions,',
    '  metrics.clicks,',
    '  metrics.conversions',
    'FROM campaign',
    "WHERE segments.date = '" + dateStr + "'",
    "  AND campaign.status != 'REMOVED'"
  ].join(' ');

  var result = AdsApp.search(query);

  var rows = [];
  while (result.hasNext()) {
    var row        = result.next();
    var costMicros = row['metrics.cost_micros'] || 0;
    var clicks     = row['metrics.clicks']      || 0;
    var spend      = costMicros / MICROS;
    var cpc        = clicks > 0 ? Math.round((spend / clicks) * 10000) / 10000 : 0;

    rows.push([
      dateStr,
      accountName,
      row['campaign.name'],
      spend,
      row['metrics.impressions'] || 0,
      clicks,
      row['metrics.conversions'] || 0,
      cpc
    ]);
  }

  Logger.log('Campaigns with data: ' + rows.length);

  if (rows.length === 0) {
    Logger.log('No campaign data for ' + dateStr + ' — nothing written.');
    return;
  }

  // ── Open sheet ────────────────────────────────────────────────────────
  var ss    = SpreadsheetApp.openByUrl(SHEET_URL);
  var sheet = ss.getSheetByName(SHEET_TAB);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_TAB);
    Logger.log('Created new tab: ' + SHEET_TAB);
  }

  // Write header if sheet is empty
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADER);
    Logger.log('Header row written.');
  }

  // ── Remove existing rows for yesterday (idempotent re-runs) ──────────
  var lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    var dateCol  = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    var toDelete = [];
    for (var i = dateCol.length - 1; i >= 0; i--) {
      if (dateCol[i][0] === dateStr) {
        toDelete.push(i + 2); // +2 because data starts at row 2 (1-indexed)
      }
    }
    toDelete.forEach(function(rowIndex) {
      sheet.deleteRow(rowIndex);
    });
    if (toDelete.length > 0) {
      Logger.log('Removed ' + toDelete.length + ' existing rows for ' + dateStr);
    }
  }

  // ── Append new rows ───────────────────────────────────────────────────
  rows.forEach(function(row) {
    sheet.appendRow(row);
  });

  Logger.log('SUCCESS: wrote ' + rows.length + ' rows for ' + dateStr
             + ' (account: ' + accountName + ')');
}
