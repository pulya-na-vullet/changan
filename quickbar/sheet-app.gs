/**
 * Заявки QuickBar → тот же лист, что и еврокубы.
 *
 * Таблица: https://docs.google.com/spreadsheets/d/1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw
 * Лист gid=2020729866
 *
 * Один раз:
 * 1. Откройте таблицу → Расширения → Apps Script.
 * 2. Вставьте этот файл вместо Code.gs.
 * 3. Развернуть → Новое развёртывание → Веб-приложение
 *    «Выполнять от имени: меня», «Кто имеет доступ: все».
 * 4. Скопируйте URL /exec в QUICKBAR_ORDERS_URL в quickbar/orders.js
 *
 * Если веб-приложение еврокубов уже висит на этом листе — подставьте
 * тот же /exec: скрипт кладёт значения в колонки по заголовкам
 * (Имя, Телефон, Город, Товар, Комментарий, Источник…).
 */

var SPREADSHEET_ID = "1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw";
var SHEET_GID = 2020729866;

var HEADER_ALIASES = {
  timestamp: ["timestamp", "дата", "date", "время"],
  source: ["source", "источник", "страница", "канал"],
  product: ["product", "товар", "услуга", "название", "продукт"],
  name: ["name", "имя", "фио", "клиент", "заказчик"],
  phone: ["phone", "телефон", "тел", "мобильный"],
  city: ["city", "город", "населённый пункт", "нас. пункт", "адрес"],
  car: ["car", "авто", "машина", "модель", "год"],
  comment: ["comment", "комментарий", "сообщение", "примечание", "коммент"],
  price: ["price", "цена", "сумма", "стоимость"],
  qty: ["qty", "количество", "кол-во", "колво"]
};

function doGet() {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, service: "quickbar-orders" }))
    .setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var params = (e && e.parameter) ? e.parameter : {};
    var sheet = sheetByGid_();
    ensureHeaders_(sheet);
    var headers = sheet.getRange(1, 1, 1, Math.max(sheet.getLastColumn(), 1)).getValues()[0];
    var row = headers.map(function (header) {
      return valueForHeader_(header, params);
    });
    sheet.appendRow(row);
    return ContentService
      .createTextOutput(JSON.stringify({ result: "success" }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ result: "error", error: String(err) }))
      .setMimeType(ContentService.MimeType.JSON);
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

function ensureHeaders_(sheet) {
  if (sheet.getLastRow() > 0 && sheet.getLastColumn() > 0) {
    var first = String(sheet.getRange(1, 1).getValue() || "").trim();
    if (first) {
      return;
    }
  }
  sheet.getRange(1, 1, 1, 9).setValues([[
    "Дата", "Источник", "Товар", "Имя", "Телефон", "Город", "Авто", "Комментарий", "Цена"
  ]]);
}

function valueForHeader_(header, params) {
  var key = normalize_(header);
  if (HEADER_ALIASES.timestamp.indexOf(key) !== -1) {
    return params.timestamp || new Date();
  }
  var groups = Object.keys(HEADER_ALIASES);
  for (var i = 0; i < groups.length; i++) {
    var group = groups[i];
    if (HEADER_ALIASES[group].indexOf(key) === -1) {
      continue;
    }
    if (params[group] != null && params[group] !== "") {
      return params[group];
    }
    var aliases = HEADER_ALIASES[group];
    for (var j = 0; j < aliases.length; j++) {
      if (params[aliases[j]] != null && params[aliases[j]] !== "") {
        return params[aliases[j]];
      }
    }
  }
  if (params[header] != null && params[header] !== "") {
    return params[header];
  }
  return "";
}

function normalize_(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/ё/g, "е");
}
