(function () {
  /**
   * URL веб-приложения Apps Script (/exec), которое пишет в лист
   * gid=2020729866 таблицы 1lt7hUCI1Pu2OknbtCjNrUTfpO4iyu1RCjyoRXtSHjpw.
   * Тот же webhook, что у страницы еврокубов, если он уже развёрнут.
   */
  var QUICKBAR_ORDERS_URL = "";

  var PRODUCT = "QuickBar для Changan Lamore";
  var PRICE = "5000";
  var SOURCE = "QuickBar лендинг";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  function statusEl(form) {
    return form.querySelector("[data-order-status]");
  }

  function setStatus(form, kind, text) {
    var node = statusEl(form);
    if (!node) {
      return;
    }
    node.hidden = !text;
    node.className = "order-status" + (kind ? " " + kind : "");
    node.textContent = text || "";
  }

  function copyAliases(data, from, names) {
    var value = data.get(from);
    if (value == null || value === "") {
      return;
    }
    names.forEach(function (name) {
      data.set(name, value);
    });
  }

  function payload(form) {
    var data = new FormData(form);
    if (!data.get("product")) {
      data.set("product", PRODUCT);
    }
    if (!data.get("price")) {
      data.set("price", PRICE);
    }
    if (!data.get("source")) {
      data.set("source", SOURCE);
    }
    if (!data.get("qty")) {
      data.set("qty", "1");
    }
    data.set("timestamp", new Date().toISOString());
    copyAliases(data, "name", ["Имя", "ФИО", "Клиент"]);
    copyAliases(data, "phone", ["Телефон", "Тел"]);
    copyAliases(data, "city", ["Город"]);
    copyAliases(data, "car", ["Авто", "Машина", "Модель"]);
    copyAliases(data, "comment", ["Комментарий", "Сообщение"]);
    copyAliases(data, "product", ["Товар", "Услуга"]);
    copyAliases(data, "source", ["Источник", "Страница"]);
    copyAliases(data, "price", ["Цена", "Сумма"]);
    copyAliases(data, "qty", ["Количество", "Кол-во"]);
    copyAliases(data, "timestamp", ["Дата", "Date"]);
    return data;
  }

  function submitOrder(form) {
    var url = QUICKBAR_ORDERS_URL.trim();
    var data = payload(form);
    if (!url) {
      return Promise.reject(new Error("no-webhook"));
    }
    return fetch(url, {
      method: "POST",
      body: data,
      mode: "no-cors"
    });
  }

  ready(function () {
    document.querySelectorAll("[data-order-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var btn = form.querySelector("[type=submit]");
        setStatus(form, "", "Отправляем заявку…");
        if (btn) {
          btn.disabled = true;
        }
        submitOrder(form)
          .then(function () {
            form.reset();
            setStatus(
              form,
              "ok",
              "Заявка ушла. Перезвоним, согласуем удобное время установки."
            );
          })
          .catch(function () {
            setStatus(
              form,
              "err",
              "Не отправилось. Напишите в ИТ-Мастерскую или позвоните — заявку примем вручную."
            );
          })
          .then(function () {
            if (btn) {
              btn.disabled = false;
            }
          });
      });
    });
  });
})();
