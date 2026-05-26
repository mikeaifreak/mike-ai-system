// Google Ads Script -- Daily Campaign Performance Export
//
// INSTALL (repeat for each Google Ads account):
// 1. Google Ads > Tools & Settings > Bulk Actions > Scripts > click "+"
// 2. Paste this entire script into the editor
// 3. Set SHEET_URL below to a Google Sheet you own
// 4. Click "Authorize" and grant permissions
// 5. Click "Run" once to verify it works
// 6. Set schedule: Frequency > Daily > 06:00 AM (account timezone)
// 7. Save
//
// OUTPUT SHEET:
//   Tab name : "Google Ads Daily - [Your Account Name]"  (auto-created)
//   Columns  : Date | Account | Campaign | Spend | Impressions | Clicks | Conversions | ROAS
//
// One row per campaign per day.
// Re-running for the same day is safe -- existing rows are deleted first.

// ---------- CONFIGURATION (only edit this line) ----------
var SHEET_URL = 'https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit';
// ---------------------------------------------------------

var HEADER = ['Date', 'Account', 'Campaign', 'Spend', 'Impressions', 'Clicks', 'Conversions', 'ROAS'];
var MICROS = 1000000;

function main() {
  var account = AdsApp.currentAccount();
  var accountName = account.getName();
  var timezone = account.getTimeZone();

  // Sheet tab is named after the account -- unique per account automatically
  var sheetTab = 'Google Ads Daily - ' + accountName;

  // Yesterday in account timezone
  var yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  var dateStr = Utilities.formatDate(yesterday, timezone, 'yyyy-MM-dd');

  Logger.log('=== Google Ads Export Start ===');
  Logger.log('Account  : ' + accountName);
  Logger.log('Date     : ' + dateStr);
  Logger.log('Sheet tab: ' + sheetTab);

  // Fetch campaign metrics via GAQL
  var query = 'SELECT campaign.name, metrics.cost_micros, metrics.impressions, ' +
              'metrics.clicks, metrics.conversions, metrics.conversions_value ' +
              'FROM campaign ' +
              "WHERE segments.date = '" + dateStr + "' " +
              "AND campaign.status != 'REMOVED'";

  Logger.log('Running GAQL query...');

  var result = AdsApp.search(query);
  var rows = [];

  while (result.hasNext()) {
    var row = result.next();

    var costMicros = row['metrics.cost_micros'] || 0;
    var clicks     = row['metrics.clicks']      || 0;
    var convValue  = row['metrics.conversions_value'] || 0;
    var spend      = costMicros / MICROS;
    var roas       = spend > 0 ? Math.round((convValue / spend) * 100) / 100 : 0;

    var dataRow = [
      dateStr,
      accountName,
      row['campaign.name'],
      spend,
      row['metrics.impressions'] || 0,
      clicks,
      row['metrics.conversions'] || 0,
      roas
    ];

    rows.push(dataRow);
    Logger.log('  Campaign: ' + row['campaign.name'] +
               ' | Spend: ' + spend +
               ' | Conversions: ' + (row['metrics.conversions'] || 0) +
               ' | ROAS: ' + roas);
  }

  Logger.log('Campaigns found: ' + rows.length);

  if (rows.length === 0) {
    Logger.log('No campaign data for ' + dateStr + ' -- nothing written to sheet.');
    return;
  }

  // Open the Google Sheet
  var ss = SpreadsheetApp.openByUrl(SHEET_URL);
  if (!ss) {
    Logger.log('ERROR: Could not open sheet at URL: ' + SHEET_URL);
    return;
  }

  // Auto-create the tab if it does not exist
  var sheet = ss.getSheetByName(sheetTab);
  if (!sheet) {
    sheet = ss.insertSheet(sheetTab);
    Logger.log('Created new tab: ' + sheetTab);
  }

  // Write header row if sheet is empty
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADER);
    Logger.log('Header row written.');
  }

  // Delete existing rows for yesterday (makes re-runs idempotent)
  var lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    var dateValues = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
    var deleteCount = 0;
    // Iterate backwards so row deletion does not shift remaining indices
    for (var i = dateValues.length - 1; i >= 0; i--) {
      if (dateValues[i][0] === dateStr) {
        sheet.deleteRow(i + 2); // +2: rows are 1-indexed and row 1 is the header
        deleteCount++;
      }
    }
    if (deleteCount > 0) {
      Logger.log('Removed ' + deleteCount + ' existing rows for ' + dateStr);
    }
  }

  // Append new rows
  for (var j = 0; j < rows.length; j++) {
    sheet.appendRow(rows[j]);
  }

  Logger.log('SUCCESS: wrote ' + rows.length + ' rows for ' + dateStr +
             ' to tab "' + sheetTab + '"');
  Logger.log('=== Google Ads Export Done ===');
}
