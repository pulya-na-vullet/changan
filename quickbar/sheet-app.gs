/**
 * Заявки → тот же лист, что eurocubes.html
 * https://docs.google.com/spreadsheets/d/1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw/edit?usp=sharing
 *
 * Строка как у еврокубов, без шапки:
 * A дата, B имя, C телефон, D текст заказа, E страница, F статус (вручную).
 *
 * Развернуть: таблица → Расширения → Apps Script → вставить →
 * Веб-приложение, «от моего имени», «все». URL /exec → QUICKBAR_ORDERS_URL.
 * Либо тот же /exec, что уже стоит в eurocubes.html.
 */

var SPREADSHEET_ID = "1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw";
var SHEET_GID = 2020729866;

function doGet(e) {
  if (e && e.parameter && (e.parameter.name || e.parameter.phone)) {
    return writeRow_(paramsFrom_(e));
  }
  return json_({ ok: true, service: "quickbar-orders" });
}

function doPost(e) {
  return writeRow_(paramsFrom_(e));
}

function paramsFrom_(e) {
  var data = {};
  if (e && e.postData && e.postData.contents) {
    try {
      data = JSON.parse(e.postData.contents) || {};
    } catch (err) {
      data = {};
    }
  }
  if (e && e.parameter) {
    var keys = Object.keys(e.parameter);
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      if (data[key] == null || data[key] === "") {
        data[key] = e.parameter[key];
      }
    }
  }
  return data;
}

function writeRow_(data) {
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sheet = sheetByGid_();
    sheet.appendRow([
      data.date || data.timestamp || formatDate_(),
      data.name || data["Имя"] || "",
      data.phone || data["Телефон"] || "",
      data.message || data.comment || data["Комментарий"] || "",
      data.page || data.source || data["Источник"] || "orders.html",
      ""
    ]);
    return json_({ result: "success" });
  } catch (err) {
    return json_({ result: "error", error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function sheetByGid_() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() === SHEET_GID) {
      return sheets[i];
    }
  }
  return ss.getActiveSheet();
}

function formatDate_() {
  return Utilities.formatDate(new Date(), "Europe/Moscow", "dd.MM.yyyy, HH:mm:ss");
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
